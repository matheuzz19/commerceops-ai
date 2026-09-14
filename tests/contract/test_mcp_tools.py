from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from commerceops.domain.models import Tenant
from commerceops.mcp.client import CommerceOpsMCPClient
from commerceops.mcp.context import (
    FixedRuntimeContextProvider,
    Specialist,
    ToolRuntimeContext,
)
from commerceops.mcp.server import create_mcp_server
from commerceops.services import CustomerService, OrderItemRequest, OrderService, ProductService


def _session_factory(session: Session) -> Callable[[], AbstractContextManager[Session]]:
    @contextmanager
    def factory() -> Iterator[Session]:
        yield session

    return factory


def _client(
    session: Session, tenant: Tenant, specialist: Specialist
) -> CommerceOpsMCPClient:
    return CommerceOpsMCPClient(
        ToolRuntimeContext(tenant_id=tenant.id, specialist=specialist),
        _session_factory(session),
    )


def _assert_envelope(result: object, *, ok: bool) -> None:
    payload = result.model_dump(mode="json")  # type: ignore[attr-defined]
    assert set(payload) == {"ok", "data", "error", "audit_id"}
    assert payload["ok"] is ok
    UUID(payload["audit_id"])
    if ok:
        assert payload["data"] is not None
        assert payload["error"] is None
    else:
        assert payload["data"] is None
        assert set(payload["error"]) == {"code", "message"}


@pytest.mark.asyncio
async def test_all_mvp_tools_work_through_mcp_with_structured_success_results(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    product = ProductService(session).create(
        tenant.id, "Widget", "WIDGET-MCP", Decimal("12.50")
    )
    session.commit()

    sales = _client(session, tenant, Specialist.SALES)
    created_customer = await sales.call_tool(
        "create_customer",
        {"name": "Taylor Example", "email": "taylor@example.test", "phone": None},
    )
    _assert_envelope(created_customer, ok=True)
    customer_id = created_customer.data["customer"]["id"]  # type: ignore[index]

    results = [
        await sales.call_tool("search_customers", {"query": "Taylor"}),
        await sales.call_tool("search_products", {"query": "Widget"}),
    ]
    created_order = await sales.call_tool(
        "create_order",
        {
            "customer_id": customer_id,
            "items": [{"product_id": str(product.id), "quantity": 2}],
        },
    )
    results.append(created_order)
    order_id = created_order.data["order"]["id"]  # type: ignore[index]
    results.extend(
        [
            await sales.call_tool(
                "list_orders", {"customer_id": customer_id, "status": "DRAFT"}
            ),
            await sales.call_tool(
                "update_order", {"order_id": order_id, "status": "CONFIRMED"}
            ),
        ]
    )

    inventory = _client(session, tenant, Specialist.INVENTORY)
    results.extend(
        [
            await inventory.call_tool("search_products", {"query": "Widget"}),
            await inventory.call_tool(
                "create_inventory_movement",
                {
                    "product_id": str(product.id),
                    "movement_type": "IN",
                    "quantity": 8,
                    "reason": "Opening stock",
                },
            ),
            await inventory.call_tool(
                "get_inventory_level", {"product_id": str(product.id)}
            ),
            await inventory.call_tool(
                "list_inventory_movements", {"product_id": str(product.id)}
            ),
        ]
    )

    finance = _client(session, tenant, Specialist.FINANCE)
    results.extend(
        [
            await finance.call_tool(
                "create_transaction",
                {
                    "type": "EXPENSE",
                    "amount": "25.00",
                    "description": "Packaging",
                    "order_id": None,
                },
            ),
            await finance.call_tool("list_transactions", {"type": "EXPENSE"}),
            await finance.call_tool(
                "get_financial_summary",
                {"period_start": date.today().isoformat(), "period_end": date.today().isoformat()},
            ),
        ]
    )

    for result in results:
        _assert_envelope(result, ok=True)
    assert created_order.data is not None
    assert created_order.data["order"]["total_amount"] == "25.00"  # type: ignore[index]


@pytest.mark.asyncio
async def test_invalid_input_returns_a_structured_failure_envelope(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    result = await _client(session, tenant, Specialist.SALES).call_tool(
        "search_customers", {"query": "", "limit": 0}
    )

    _assert_envelope(result, ok=False)
    assert result.error is not None
    assert result.error.code == "INVALID_INPUT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("search_customers", {"query": "x"}),
        ("create_customer", {"name": "x"}),
        ("search_products", {"query": "x"}),
        ("list_orders", {}),
        (
            "create_order",
            {"customer_id": str(uuid4()), "items": [{"product_id": str(uuid4()), "quantity": 1}]},
        ),
        ("update_order", {"order_id": str(uuid4()), "status": "CONFIRMED"}),
        ("get_inventory_level", {"product_id": str(uuid4())}),
        ("list_inventory_movements", {}),
        (
            "create_inventory_movement",
            {
                "product_id": str(uuid4()),
                "movement_type": "IN",
                "quantity": 1,
                "reason": "x",
            },
        ),
        (
            "get_financial_summary",
            {"period_start": "2026-01-01", "period_end": "2026-01-31"},
        ),
        ("list_transactions", {}),
        (
            "create_transaction",
            {"type": "EXPENSE", "amount": "1.00", "description": "x"},
        ),
    ],
)
async def test_general_specialist_is_denied_every_tool(
    session: Session,
    tenants: tuple[Tenant, Tenant],
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    tenant, _ = tenants
    result = await _client(session, tenant, Specialist.GENERAL).call_tool(tool_name, arguments)

    _assert_envelope(result, ok=False)
    assert result.error is not None
    assert result.error.code == "TOOL_UNAUTHORIZED"


@pytest.mark.asyncio
async def test_cross_tenant_ids_are_rejected_by_service_boundaries(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_one, tenant_two = tenants
    customer = CustomerService(session).create(tenant_one.id, "Tenant One Customer")
    product = ProductService(session).create(
        tenant_one.id, "Private Product", "PRIVATE-MCP", Decimal("10.00")
    )
    order = OrderService(session).create(
        tenant_one.id, customer.id, [OrderItemRequest(product.id, 1)]
    )
    session.commit()

    sales_result = await _client(session, tenant_two, Specialist.SALES).call_tool(
        "create_order",
        {
            "customer_id": str(customer.id),
            "items": [{"product_id": str(product.id), "quantity": 1}],
        },
    )
    inventory_result = await _client(
        session, tenant_two, Specialist.INVENTORY
    ).call_tool("get_inventory_level", {"product_id": str(product.id)})
    finance_result = await _client(session, tenant_two, Specialist.FINANCE).call_tool(
        "create_transaction",
        {
            "type": "REVENUE",
            "amount": "10.00",
            "description": "Foreign order",
            "order_id": str(order.id),
        },
    )

    assert sales_result.error is not None
    assert sales_result.error.code == "CUSTOMER_NOT_FOUND"
    assert inventory_result.error is not None
    assert inventory_result.error.code == "PRODUCT_NOT_FOUND"
    assert finance_result.error is not None
    assert finance_result.error.code == "ORDER_NOT_FOUND"


@pytest.mark.asyncio
async def test_tool_schemas_never_expose_tenant_id(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    server = create_mcp_server(
        FixedRuntimeContextProvider(
            ToolRuntimeContext(tenant_id=tenant.id, specialist=Specialist.SALES)
        ),
        _session_factory(session),
    )

    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools()

    assert len(result.tools) == 12
    for tool in result.tools:
        assert "tenant_id" not in tool.input_schema.get("properties", {})


@pytest.mark.asyncio
async def test_model_cannot_override_trusted_tenant_context(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_one, tenant_two = tenants
    result = await _client(session, tenant_one, Specialist.SALES).call_tool(
        "search_customers", {"query": "x", "tenant_id": str(tenant_two.id)}
    )

    _assert_envelope(result, ok=False)
    assert result.error is not None
    assert result.error.code == "INVALID_INPUT"
