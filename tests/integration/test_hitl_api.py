from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from commerceops.agents.planning import FinancePlan, InventoryPlan, SalesPlan
from commerceops.agents.runtime import SpecialistDependencies, ToolCaller
from commerceops.agents.supervisor.graph import create_supervisor_graph
from commerceops.api.main import app
from commerceops.api.runtime import ConversationRuntime, get_conversation_runtime
from commerceops.graph.state import AgentTask, RoutingPlan
from commerceops.mcp.context import Specialist
from commerceops.mcp.tools.schemas import ToolResult


class FixedClassifier:
    async def classify(self, query: str) -> RoutingPlan:
        return RoutingPlan(
            tasks=[AgentTask(agent="finance", query=query, reason="Expense request")]
        )


class FixedPlanner:
    def __init__(self, value: SalesPlan | InventoryPlan | FinancePlan) -> None:
        self.value = value

    async def plan(self, query: str) -> SalesPlan | InventoryPlan | FinancePlan:
        return self.value


class RecordingFinanceClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> ToolResult:
        self.calls.append((tool_name, arguments))
        return ToolResult(
            ok=True,
            data={
                "transaction": {
                    "id": str(uuid4()),
                    "order_id": None,
                    "type": "EXPENSE",
                    "status": "POSTED",
                    "amount": "1001.00",
                    "description": "Equipment",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            },
            error=None,
            audit_id="audit-transaction",
        )


def _runtime(client: RecordingFinanceClient) -> ConversationRuntime:
    def client_factory(tenant_id: UUID, specialist: Specialist) -> ToolCaller:
        return client

    dependencies = SpecialistDependencies(
        sales_planner=FixedPlanner(SalesPlan(action="clarify")),  # type: ignore[arg-type]
        inventory_planner=FixedPlanner(InventoryPlan(action="clarify")),  # type: ignore[arg-type]
        finance_planner=FixedPlanner(  # type: ignore[arg-type]
            FinancePlan(
                action="create_expense",
                amount=Decimal("1001.00"),
                description="Equipment",
            )
        ),
        client_factory=client_factory,
    )
    graph = create_supervisor_graph(
        FixedClassifier(), dependencies, checkpointer=InMemorySaver()
    )
    return ConversationRuntime(graph=graph)


def test_high_risk_action_interrupts_then_approval_executes_once() -> None:
    finance_client = RecordingFinanceClient()
    runtime = _runtime(finance_client)
    app.dependency_overrides[get_conversation_runtime] = lambda: runtime
    client = TestClient(app)
    headers = {"X-Tenant-ID": str(uuid4()), "X-User-ID": "operator"}
    try:
        pending = client.post(
            "/messages",
            headers=headers,
            json={
                "session_id": "session",
                "message_id": "message",
                "content": "Record a 1001 expense for equipment",
                "content_type": "text",
                "debounce": False,
            },
        )

        assert pending.status_code == 200
        assert pending.json()["status"] == "requires_confirmation"
        assert pending.json()["confirmation"]["action"]["risk_level"] == "high"
        assert finance_client.calls == []

        completed = client.post(
            f"/confirmations/{pending.json()['checkpoint_id']}/approve",
            headers=headers,
        )

        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        assert "recorded successfully" in completed.json()["response"]
        assert [call[0] for call in finance_client.calls] == ["create_transaction"]
    finally:
        app.dependency_overrides.clear()


def test_rejection_does_not_execute_and_checkpoint_is_tenant_scoped() -> None:
    finance_client = RecordingFinanceClient()
    runtime = _runtime(finance_client)
    app.dependency_overrides[get_conversation_runtime] = lambda: runtime
    client = TestClient(app)
    tenant_id = str(uuid4())
    headers = {"X-Tenant-ID": tenant_id, "X-User-ID": "operator"}
    try:
        pending = client.post(
            "/messages",
            headers=headers,
            json={
                "session_id": "session",
                "message_id": "message",
                "content": "Record a large equipment expense",
                "debounce": False,
            },
        ).json()

        unauthorized = client.post(
            f"/confirmations/{pending['checkpoint_id']}/reject",
            headers={"X-Tenant-ID": str(uuid4()), "X-User-ID": "operator"},
        )
        rejected = client.post(
            f"/confirmations/{pending['checkpoint_id']}/reject", headers=headers
        )

        assert unauthorized.status_code == 404
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "failed"
        assert "rejected" in rejected.json()["response"]
        assert finance_client.calls == []
    finally:
        app.dependency_overrides.clear()
