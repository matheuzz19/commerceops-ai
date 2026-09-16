from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Generic, TypeVar, cast
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from commerceops.agents.finance.graph import make_finance_specialist
from commerceops.agents.inventory.graph import make_inventory_specialist
from commerceops.agents.planning import (
    FinancePlan,
    InventoryPlan,
    SalesItemPlan,
    SalesPlan,
)
from commerceops.agents.runtime import SpecialistDependencies, ToolCaller
from commerceops.agents.sales.graph import make_sales_specialist
from commerceops.agents.supervisor.graph import create_supervisor_graph
from commerceops.domain.enums import InventoryMovementType
from commerceops.domain.models import Order, Tenant, Transaction
from commerceops.graph.state import AgentState, AgentTask, RoutingPlan, SpecialistResult
from commerceops.mcp.client import CommerceOpsMCPClient
from commerceops.mcp.context import Specialist, ToolRuntimeContext
from commerceops.mcp.tools.schemas import ToolResult
from commerceops.services import (
    CustomerService,
    FinanceService,
    InventoryService,
    OrderItemRequest,
    OrderService,
    ProductService,
)

PlanT = TypeVar("PlanT")


class FixedPlanner(Generic[PlanT]):
    def __init__(self, value: PlanT) -> None:
        self.value = value

    async def plan(self, query: str) -> PlanT:
        return self.value


class FixedClassifier:
    def __init__(self, plan: RoutingPlan) -> None:
        self.value = plan

    async def classify(self, query: str) -> RoutingPlan:
        return self.value


@contextmanager
def _reuse_session(session: Session) -> Generator[Session, None, None]:
    yield session


def _client_factory(session: Session):  # type: ignore[no-untyped-def]
    def factory(
        tenant_id: UUID,
        specialist: Specialist,
        approval_grants: frozenset[str] = frozenset(),
    ) -> ToolCaller:
        return CommerceOpsMCPClient(
            ToolRuntimeContext(
                tenant_id=tenant_id,
                specialist=specialist,
                approval_grants=approval_grants,
            ),
            lambda: _reuse_session(session),
        )

    return factory


def _independent_client_factory(session: Session):  # type: ignore[no-untyped-def]
    bind = session.get_bind()

    @contextmanager
    def new_session() -> Generator[Session, None, None]:
        with Session(bind) as worker_session:
            yield worker_session

    def factory(tenant_id: UUID, specialist: Specialist) -> ToolCaller:
        return CommerceOpsMCPClient(
            ToolRuntimeContext(tenant_id=tenant_id, specialist=specialist), new_session
        )

    return factory


def _state(tenant: Tenant, agent: str, query: str) -> AgentState:
    return {
        "tenant_id": str(tenant.id),
        "user_id": "test-user",
        "session_id": "test-session",
        "specialist_task": AgentTask(agent=agent, query=query, reason="test"),  # type: ignore[arg-type]
        "task_index": 0,
    }


def _result(update: dict[str, object]) -> SpecialistResult:
    results = cast(list[SpecialistResult], update["specialist_results"])
    return results[0]


@pytest.mark.asyncio
async def test_sales_create_order_resolves_customer_and_product_before_write(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    CustomerService(session).create(tenant.id, "River Example")
    ProductService(session).create(
        tenant.id, "Compact Keyboard", "KEY-01", Decimal("49.90")
    )
    session.commit()
    planner = FixedPlanner(
        SalesPlan(
            action="create_order",
            customer_query="River Example",
            items=[SalesItemPlan(product_query="Compact Keyboard", quantity=2)],
        )
    )
    node = make_sales_specialist(planner, _client_factory(session))

    update = await node(_state(tenant, "sales", "Create an order"))

    assert "created successfully" in _result(update).response
    assert session.query(Order).count() == 1
    records = cast(list[dict[str, object]], update["tool_results"])
    assert [record["tool_name"] for record in records] == [
        "search_customers",
        "search_products",
        "create_order",
    ]
    assert len(cast(list[object], update["resolved_entities"])) == 2


@pytest.mark.asyncio
async def test_sales_does_not_write_when_product_resolution_is_ambiguous(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    CustomerService(session).create(tenant.id, "River Example")
    ProductService(session).create(tenant.id, "Widget Small", "W-1", Decimal("5.00"))
    ProductService(session).create(tenant.id, "Widget Large", "W-2", Decimal("9.00"))
    session.commit()
    node = make_sales_specialist(
        FixedPlanner(SalesPlan(
            action="create_order", customer_query="River Example",
            items=[SalesItemPlan(product_query="Widget", quantity=1)],
        )),
        _client_factory(session),
    )

    update = await node(_state(tenant, "sales", "Order a widget"))

    assert "Multiple products matched" in _result(update).response
    assert session.query(Order).count() == 0
    records = cast(list[dict[str, object]], update["tool_results"])
    assert "create_order" not in [record["tool_name"] for record in records]


@pytest.mark.asyncio
async def test_inventory_resolves_product_before_level_lookup(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    product = ProductService(session).create(
        tenant.id, "Compact Keyboard", "KEY-01", Decimal("49.90")
    )
    InventoryService(session).create_movement(
        tenant.id, product.id, InventoryMovementType.IN, 12, "Opening stock"
    )
    session.commit()
    node = make_inventory_specialist(
        FixedPlanner(InventoryPlan(action="get_level", product_query="Compact Keyboard")),
        _client_factory(session),
    )

    update = await node(_state(tenant, "inventory", "Check keyboard stock"))

    assert _result(update).response == "Available quantity: 12."
    records = cast(list[dict[str, object]], update["tool_results"])
    assert [record["tool_name"] for record in records] == [
        "search_products",
        "get_inventory_level",
    ]


@pytest.mark.asyncio
async def test_inventory_movement_uses_resolved_product_id(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    product = ProductService(session).create(
        tenant.id, "Compact Keyboard", "KEY-01", Decimal("49.90")
    )
    session.commit()
    node = make_inventory_specialist(
        FixedPlanner(InventoryPlan(
            action="create_movement", product_query="Compact Keyboard",
            movement_type=InventoryMovementType.IN, quantity=5, reason="Delivery",
        )),
        _client_factory(session),
    )

    update = await node(_state(tenant, "inventory", "Receive five keyboards"))

    assert "created successfully" in _result(update).response
    assert InventoryService(session).get_level(tenant.id, product.id) == 5
    assert len(cast(list[object], update["resolved_entities"])) == 1


@pytest.mark.asyncio
async def test_approved_negative_inventory_movement_resumes_with_trusted_grant(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    product = ProductService(session).create(
        tenant.id, "Compact Keyboard", "KEY-01", Decimal("49.90")
    )
    InventoryService(session).create_movement(
        tenant.id, product.id, InventoryMovementType.IN, 1, "Opening stock"
    )
    session.commit()
    dependencies = SpecialistDependencies(
        sales_planner=FixedPlanner(SalesPlan(action="clarify")),
        inventory_planner=FixedPlanner(
            InventoryPlan(
                action="create_movement",
                product_query="Compact Keyboard",
                movement_type=InventoryMovementType.OUT,
                quantity=2,
                reason="Approved exception",
            )
        ),
        finance_planner=FixedPlanner(FinancePlan(action="clarify")),
        client_factory=_client_factory(session),
    )
    graph = create_supervisor_graph(
        FixedClassifier(
            RoutingPlan(
                tasks=[
                    AgentTask(
                        agent="inventory",
                        query="Remove two keyboards",
                        reason="Inventory movement",
                    )
                ]
            )
        ),
        dependencies,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "negative-stock-test"}}

    pending = await graph.ainvoke(
        {
            "tenant_id": str(tenant.id),
            "user_id": "operator",
            "session_id": "session",
            "message_id": "message",
            "content": "Remove two keyboards",
            "content_type": "text",
        },
        config=config,
    )

    assert pending["__interrupt__"][0].value["risk_reason"] == (
        "The movement would make inventory negative."
    )
    assert InventoryService(session).get_level(tenant.id, product.id) == 1

    completed = await graph.ainvoke(Command(resume={"approved": True}), config=config)

    assert "created successfully" in completed["final_response"]
    assert InventoryService(session).get_level(tenant.id, product.id) == -1


@pytest.mark.asyncio
async def test_finance_records_expense_only_after_verified_tool_result(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    node = make_finance_specialist(
        FixedPlanner(FinancePlan(
            action="create_expense", amount=Decimal("25.00"), description="Office supplies"
        )),
        _client_factory(session),
    )

    update = await node(_state(tenant, "finance", "Record office supplies expense"))

    assert "recorded successfully" in _result(update).response
    assert session.query(Transaction).count() == 1


@pytest.mark.asyncio
async def test_finance_derives_current_month_deterministically(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    FinanceService(session).record_expense(tenant.id, Decimal("25.00"), "Office supplies")
    session.commit()
    node = make_finance_specialist(
        FixedPlanner(FinancePlan(action="summary", relative_period="current_month")),
        _client_factory(session),
    )

    update = await node(_state(tenant, "finance", "Show this month's summary"))

    assert "expenses: 25.00" in _result(update).response


class InvalidOutputClient:
    async def call_tool(self, tool_name: str, arguments: object) -> ToolResult:
        return ToolResult(ok=True, data={"unexpected": True}, error=None, audit_id="audit")


@pytest.mark.asyncio
async def test_invalid_tool_output_never_produces_success_claim(
    tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    node = make_finance_specialist(
        FixedPlanner(FinancePlan(action="list_transactions")),
        lambda tenant_id, specialist: InvalidOutputClient(),
    )

    update = await node(_state(tenant, "finance", "List transactions"))

    result = _result(update)
    assert result.error == "TOOL_FAILED"
    assert "success" not in result.response.casefold()
    records = cast(list[dict[str, object]], update["tool_results"])
    envelope = cast(dict[str, object], records[0]["result"])
    error = cast(dict[str, object], envelope["error"])
    assert error["code"] == "INVALID_TOOL_OUTPUT"


@pytest.mark.asyncio
async def test_supervisor_executes_parallel_sales_and_inventory_read_workflows(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    CustomerService(session).create(tenant.id, "River Example")
    product = ProductService(session).create(
        tenant.id, "Compact Keyboard", "KEY-01", Decimal("49.90")
    )
    InventoryService(session).create_movement(
        tenant.id, product.id, InventoryMovementType.IN, 7, "Opening stock"
    )
    session.commit()
    routing_plan = RoutingPlan(tasks=[
        AgentTask(agent="sales", query="Find River Example", reason="Customer search"),
        AgentTask(agent="inventory", query="Check Compact Keyboard", reason="Stock lookup"),
    ])
    dependencies = SpecialistDependencies(
        sales_planner=FixedPlanner(SalesPlan(action="search_customers", query="River Example")),
        inventory_planner=FixedPlanner(InventoryPlan(
            action="get_level", product_query="Compact Keyboard"
        )),
        finance_planner=FixedPlanner(FinancePlan(action="clarify")),
        client_factory=_independent_client_factory(session),
    )
    graph = create_supervisor_graph(FixedClassifier(routing_plan), dependencies)

    result = await graph.ainvoke({
        "tenant_id": str(tenant.id), "user_id": "user", "session_id": "session",
        "message_id": "message", "content": "Find River Example and check keyboard stock",
        "content_type": "text",
    })

    assert [item.agent for item in result["specialist_results"]] == ["sales", "inventory"]
    assert "River Example" in result["specialist_results"][0].response
    assert result["specialist_results"][1].response == "Available quantity: 7."
    assert {record["tool_name"] for record in result["tool_results"]} == {
        "search_customers", "search_products", "get_inventory_level",
    }


@pytest.mark.asyncio
async def test_remaining_mvp_specialist_workflows_execute_through_mcp(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    customer = CustomerService(session).create(tenant.id, "River Example")
    product = ProductService(session).create(
        tenant.id, "Compact Keyboard", "KEY-01", Decimal("49.90")
    )
    InventoryService(session).create_movement(
        tenant.id, product.id, InventoryMovementType.IN, 4, "Opening stock"
    )
    OrderService(session).create(
        tenant.id, customer.id, [OrderItemRequest(product.id, 1)]
    )
    FinanceService(session).record_expense(tenant.id, Decimal("10.00"), "Supplies")
    session.commit()
    client_factory = _client_factory(session)

    create_customer = make_sales_specialist(
        FixedPlanner(SalesPlan(action="create_customer", customer_name="New Customer")),
        client_factory,
    )
    search_products = make_sales_specialist(
        FixedPlanner(SalesPlan(action="search_products", query="Keyboard")), client_factory
    )
    list_orders = make_sales_specialist(
        FixedPlanner(SalesPlan(action="list_orders", customer_query="River Example")),
        client_factory,
    )
    list_movements = make_inventory_specialist(
        FixedPlanner(
            InventoryPlan(action="list_movements", product_query="Compact Keyboard")
        ),
        client_factory,
    )
    list_transactions = make_finance_specialist(
        FixedPlanner(FinancePlan(action="list_transactions")), client_factory
    )

    updates = [
        await create_customer(_state(tenant, "sales", "Create a customer")),
        await search_products(_state(tenant, "sales", "Search keyboards")),
        await list_orders(_state(tenant, "sales", "List River orders")),
        await list_movements(_state(tenant, "inventory", "List keyboard movements")),
        await list_transactions(_state(tenant, "finance", "List transactions")),
    ]

    responses = [_result(update).response for update in updates]
    assert "created successfully" in responses[0]
    assert "Compact Keyboard" in responses[1]
    assert responses[2] == "Found 1 order(s)."
    assert responses[3] == "Found 1 inventory movement(s)."
    assert responses[4] == "Found 1 transaction(s)."
