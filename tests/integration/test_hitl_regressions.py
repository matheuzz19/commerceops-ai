"""Regression coverage for checkpoint-stable approvals and safe parallel writes."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from commerceops.agents.planning import FinancePlan, InventoryPlan, SalesItemPlan, SalesPlan
from commerceops.agents.runtime import SpecialistDependencies
from commerceops.agents.supervisor.graph import create_supervisor_graph
from commerceops.api.runtime import ConversationRuntime
from commerceops.api.schemas import MessageRequest
from commerceops.config import settings
from commerceops.graph.state import AgentState, AgentTask, Department, RoutingPlan, SpecialistResult
from commerceops.mcp.tools.schemas import ToolResult

PlanT = TypeVar("PlanT")


class SequencePlanner(Generic[PlanT]):
    def __init__(self, *plans: PlanT) -> None:
        self.plans = plans
        self.calls = 0

    async def plan(self, query: str) -> PlanT:
        plan = self.plans[min(self.calls, len(self.plans) - 1)]
        self.calls += 1
        return plan


class Classifier:
    def __init__(self, *agents: Department) -> None:
        self.agents = agents

    async def classify(self, query: str) -> RoutingPlan:
        return RoutingPlan(tasks=[
            AgentTask(agent=agent, query=query, reason="Regression fixture")
            for agent in self.agents
        ])


class RecordingClient:
    def __init__(self, *, fail_write: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.product_id = str(uuid4())
        self.customer_id = str(uuid4())
        self.fail_write = fail_write

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> ToolResult:
        self.calls.append((tool_name, dict(arguments)))
        # Yield inside execution so competing approval requests really overlap.
        await asyncio.sleep(0)
        if self.fail_write and tool_name.startswith("create_"):
            raise ConnectionError("Synthetic uncertain tool execution")
        now = datetime.now(UTC).isoformat()
        if tool_name == "search_customers":
            data = {"customers": [{
                "id": self.customer_id, "name": "Synthetic", "email": None, "phone": None,
            }]}
        elif tool_name == "search_products":
            data = {"products": [{
                "id": self.product_id, "name": "Keyboard", "sku": "KEY",
                "price": "10.00", "active": True,
            }]}
        elif tool_name == "create_inventory_movement":
            data = {"movement": {
                "id": str(uuid4()), "product_id": arguments["product_id"],
                "movement_type": arguments["movement_type"], "quantity": arguments["quantity"],
                "reason": arguments["reason"], "created_at": now,
            }}
        elif tool_name == "create_customer":
            data = {"customer": {
                "id": str(uuid4()), "name": arguments["name"], "email": None, "phone": None,
            }}
        elif tool_name == "create_order":
            data = {"order": {
                "id": str(uuid4()), "customer_id": arguments["customer_id"], "status": "DRAFT",
                "payment_status": "UNPAID", "total_amount": "40.00", "created_at": now,
                "items": [{
                    "product_id": self.product_id, "quantity": 1, "unit_price": "10.00",
                } for _ in range(4)],
            }}
        else:
            assert tool_name == "create_transaction"
            data = {"transaction": {
                "id": str(uuid4()), "order_id": None, "type": "EXPENSE", "status": "POSTED",
                "amount": arguments["amount"], "description": arguments["description"],
                "created_at": now,
            }}
        return ToolResult(ok=True, data=data, error=None, audit_id=str(uuid4()))

    @property
    def writes(self) -> list[tuple[str, dict[str, object]]]:
        return [call for call in self.calls if call[0].startswith("create_")]


def expense(amount: str = "1001") -> FinancePlan:
    return FinancePlan(action="create_expense", amount=Decimal(amount), description="Equipment")


def build_runtime(
    client: RecordingClient,
    *,
    classifier: Classifier | None = None,
    finance: SequencePlanner[FinancePlan] | None = None,
    sales: SequencePlanner[SalesPlan] | None = None,
    inventory: SequencePlanner[InventoryPlan] | None = None,
) -> ConversationRuntime:
    dependencies = SpecialistDependencies(
        sales_planner=sales or SequencePlanner(SalesPlan(action="clarify")),
        inventory_planner=inventory or SequencePlanner(InventoryPlan(action="clarify")),
        finance_planner=finance or SequencePlanner(expense()),
        client_factory=lambda *args: client,
    )
    graph = create_supervisor_graph(
        classifier or Classifier("finance"), dependencies, checkpointer=InMemorySaver()
    )
    return ConversationRuntime(graph=graph)


async def submit(runtime: ConversationRuntime, tenant_id: str):
    return await runtime.submit(
        MessageRequest(session_id="session", message_id=str(uuid4()), content="Synthetic request"),
        tenant_id, "operator",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("next_amount", ["10", "2001"])
@pytest.mark.parametrize("approved", [True, False])
async def test_resume_never_replans_or_changes_the_reviewed_action(
    next_amount: str, approved: bool,
) -> None:
    client = RecordingClient()
    planner = SequencePlanner(expense(), expense(next_amount))
    runtime = build_runtime(client, finance=planner)
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)
    assert pending.confirmation["action"]["arguments"]["amount"] == "1001"
    assert client.writes == []

    response = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=approved)

    assert planner.calls == 1
    assert response.status == ("completed" if approved else "failed")
    if approved:
        assert len(client.writes) == 1
        assert client.writes[0][1]["amount"] == "1001"
    else:
        assert client.writes == []
    assert await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=True) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_parallel_writes_are_reviewed_together_before_any_execution(approved: bool) -> None:
    client = RecordingClient()
    inventory = SequencePlanner(InventoryPlan(
        action="create_movement", product_query="Keyboard", movement_type="IN",
        quantity=101, reason="Synthetic delivery",
    ))
    runtime = build_runtime(
        client, classifier=Classifier("sales", "finance", "inventory"),
        sales=SequencePlanner(SalesPlan(action="create_customer", customer_name="Synthetic")),
        inventory=inventory,
    )
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)

    assert pending.status == "requires_confirmation"
    assert [action["tool_name"] for action in pending.confirmation["actions"]] == [
        "create_customer", "create_transaction", "create_inventory_movement",
    ]
    assert client.writes == []
    reviewed_product = pending.confirmation["actions"][2]["arguments"]["product_id"]
    # A changed lookup result must not change the already-resolved write target.
    client.product_id = str(uuid4())
    response = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=approved)

    assert response.status == ("completed" if approved else "failed")
    assert inventory.calls == 1
    assert sum(name == "search_products" for name, _ in client.calls) == 1
    if approved:
        assert len(client.writes) == 3
        movement = next(args for name, args in client.writes if name == "create_inventory_movement")
        assert movement["product_id"] == reviewed_product
    else:
        assert client.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("first_approval", [True, False])
async def test_competing_approvals_and_rejections_consume_checkpoint_once(
    first_approval: bool,
) -> None:
    client = RecordingClient()
    runtime = build_runtime(client)
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)

    responses = await asyncio.gather(
        runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=first_approval),
        runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=True),
    )

    assert responses[0].status == ("completed" if first_approval else "failed")
    assert responses[1] is None
    assert len(client.writes) == int(first_approval)


@pytest.mark.asyncio
async def test_wrong_user_cannot_consume_an_approval() -> None:
    client = RecordingClient()
    runtime = build_runtime(client)
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)

    unauthorized = await runtime.resume(
        pending.checkpoint_id, tenant_id, "other-user", approved=True
    )
    assert unauthorized is None
    assert client.writes == []
    response = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=True)
    assert response.status == "completed"
    assert len(client.writes) == 1


@pytest.mark.asyncio
async def test_uncertain_write_failure_cannot_be_replayed_through_approval() -> None:
    client = RecordingClient(fail_write=True)
    runtime = build_runtime(client)
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)

    response = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=True)

    assert response.status == "failed"
    assert "inspect" in response.response
    assert "Synthetic" not in response.response
    assert await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=True) is None
    assert len(client.writes) == 1


@pytest.mark.asyncio
async def test_same_thread_clears_every_per_request_collection() -> None:
    client = RecordingClient()
    classifier = Classifier("inventory")
    runtime = build_runtime(client, classifier=classifier, inventory=SequencePlanner(InventoryPlan(
        action="create_movement", product_query="Keyboard", movement_type="IN",
        quantity=1, reason="Synthetic delivery",
    )))
    config = {"configurable": {"thread_id": "reused-session"}}
    raw = {
        "tenant_id": str(uuid4()), "user_id": "operator", "session_id": "session",
        "message_id": "first", "content": "Receive keyboard", "content_type": "text",
    }
    first = await runtime.graph.ainvoke(raw, config=config)
    assert len(first["specialist_results"]) == 1
    for key in ("resolved_entities", "proposed_actions", "tool_results", "prepared_writes"):
        assert first[key]

    classifier.agents = ("general",)
    raw.update(message_id="second", content="Hello")
    second = await runtime.graph.ainvoke(raw, config=config)

    assert len(second["specialist_results"]) == 1
    assert second["specialist_results"][0].agent == "general"
    for key in ("resolved_entities", "proposed_actions", "tool_results", "prepared_writes"):
        assert second[key] == []
    assert "Expense" not in second["final_response"]


@pytest.mark.asyncio
async def test_runtime_exposes_and_resumes_every_parallel_interrupt_by_id() -> None:
    executed: list[str] = []

    def worker(agent: Department):
        def review(state: AgentState) -> dict[str, object]:
            decision = interrupt({"message": f"Approve {agent}", "action": {"agent": agent}})
            if decision["approved"]:
                executed.append(agent)
            return {"specialist_results": [SpecialistResult(
                task_index=0 if agent == "sales" else 1, agent=agent,
                query=agent, response="Approved" if decision["approved"] else "Rejected",
            )]}
        return review

    builder = StateGraph(AgentState)
    for agent in ("sales", "finance"):
        builder.add_node(agent, worker(agent))
        builder.add_edge(START, agent)
        builder.add_edge(agent, END)
    runtime = ConversationRuntime(graph=builder.compile(checkpointer=InMemorySaver()))
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)

    entries = pending.confirmation["interrupts"]
    assert len(entries) == 2
    assert len({entry["interrupt_id"] for entry in entries}) == 2
    assert executed == []
    response = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=True)

    assert response.status == "completed"
    assert sorted(executed) == ["finance", "sales"]


@pytest.mark.asyncio
async def test_total_write_count_is_checked_across_specialists_before_execution() -> None:
    client = RecordingClient()
    runtime = build_runtime(
        client, classifier=Classifier("sales", "finance"),
        sales=SequencePlanner(SalesPlan(
            action="create_order", customer_query="Synthetic",
            items=[SalesItemPlan(product_query="Keyboard", quantity=1) for _ in range(4)],
        )),
        finance=SequencePlanner(expense("10")),
    )
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)

    assert pending.status == "requires_confirmation"
    assert "6 writes" in pending.confirmation["risk_reason"]
    assert len(pending.confirmation["actions"]) == 2
    assert client.writes == []
    response = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=True)
    assert response.status == "completed"
    assert {name for name, _ in client.writes} == {"create_order", "create_transaction"}


@pytest.mark.asyncio
async def test_preparation_error_blocks_every_write_in_the_request() -> None:
    class InvalidProductClient(RecordingClient):
        async def call_tool(
            self, tool_name: str, arguments: Mapping[str, object]
        ) -> ToolResult:
            if tool_name == "search_products":
                return ToolResult(ok=True, data={"unexpected": True}, error=None, audit_id="audit")
            return await super().call_tool(tool_name, arguments)

    client = InvalidProductClient()
    runtime = build_runtime(
        client, classifier=Classifier("finance", "inventory"),
        finance=SequencePlanner(expense("10")),
        inventory=SequencePlanner(InventoryPlan(
            action="create_movement", product_query="Keyboard", movement_type="IN",
            quantity=1, reason="Synthetic delivery",
        )),
    )
    response = await submit(runtime, str(uuid4()))
    assert response.status == "failed"
    assert client.writes == []


@pytest.mark.asyncio
async def test_batch_rejection_uses_saved_policy_even_if_threshold_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingClient()
    runtime = build_runtime(
        client, classifier=Classifier("sales", "finance"),
        sales=SequencePlanner(SalesPlan(
            action="create_order", customer_query="Synthetic",
            items=[SalesItemPlan(product_query="Keyboard", quantity=1) for _ in range(4)],
        )),
        finance=SequencePlanner(expense("10")),
    )
    tenant_id = str(uuid4())
    pending = await submit(runtime, tenant_id)
    assert pending.status == "requires_confirmation"
    monkeypatch.setattr(settings, "max_batch_write", 100)

    response = await runtime.resume(pending.checkpoint_id, tenant_id, "operator", approved=False)

    assert response.status == "failed"
    assert client.writes == []


@pytest.mark.asyncio
async def test_a_new_interrupt_gets_a_new_approval_handle() -> None:
    executed: list[str] = []

    def step(name: str):
        def review(state: AgentState) -> dict[str, object]:
            decision = interrupt({"message": f"Approve {name}", "action": {"name": name}})
            if decision["approved"]:
                executed.append(name)
            return {}
        return review

    builder = StateGraph(AgentState)
    builder.add_node("first", step("first"))
    builder.add_node("second", step("second"))
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    runtime = ConversationRuntime(graph=builder.compile(checkpointer=InMemorySaver()))
    tenant_id = str(uuid4())
    first = await submit(runtime, tenant_id)
    second = await runtime.resume(first.checkpoint_id, tenant_id, "operator", approved=True)

    assert second.status == "requires_confirmation"
    assert second.checkpoint_id != first.checkpoint_id
    assert executed == ["first"]
    assert await runtime.resume(first.checkpoint_id, tenant_id, "operator", approved=True) is None
    completed = await runtime.resume(second.checkpoint_id, tenant_id, "operator", approved=True)
    assert completed.status == "completed"
    assert executed == ["first", "second"]
