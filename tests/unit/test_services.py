from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from commerceops.domain.enums import InventoryMovementType, TransactionStatus, TransactionType
from commerceops.domain.invariants import DomainError
from commerceops.domain.models import Tenant
from commerceops.services import (
    CustomerService,
    FinanceService,
    InventoryService,
    OrderItemRequest,
    OrderService,
    ProductService,
)


def test_inventory_uses_an_auditable_ledger(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    product = ProductService(session).create(tenant.id, "Widget", "WIDGET-01", Decimal("10.00"))
    inventory = InventoryService(session)

    inventory.create_movement(tenant.id, product.id, InventoryMovementType.IN, 10, "Opening stock")
    inventory.create_movement(tenant.id, product.id, InventoryMovementType.OUT, 3, "Sale")
    inventory.create_movement(tenant.id, product.id, InventoryMovementType.ADJUSTMENT, -2, "Count")

    assert inventory.get_level(tenant.id, product.id) == 5
    assert len(inventory.list_movements(tenant.id, product.id)) == 3

    with pytest.raises(DomainError, match="stock negative") as error:
        inventory.create_movement(tenant.id, product.id, InventoryMovementType.OUT, 6, "Too many")
    assert error.value.code == "INSUFFICIENT_STOCK"


def test_order_total_is_calculated_from_tenant_owned_active_products(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    customer = CustomerService(session).create(tenant.id, "Taylor Example")
    product = ProductService(session).create(tenant.id, "Widget", "WIDGET-01", Decimal("12.50"))

    order = OrderService(session).create(
        tenant.id, customer.id, [OrderItemRequest(product.id, quantity=2)]
    )

    assert order.total_amount == Decimal("25.00")
    assert order.items[0].unit_price == Decimal("12.50")


def test_services_do_not_expose_or_write_cross_tenant_records(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant_one, tenant_two = tenants
    customer = CustomerService(session).create(tenant_one.id, "Taylor Example")
    product = ProductService(session).create(tenant_one.id, "Widget", "WIDGET-01", Decimal("12.50"))

    assert CustomerService(session).get(tenant_two.id, customer.id) is None
    assert ProductService(session).get(tenant_two.id, product.id) is None

    with pytest.raises(DomainError) as error:
        OrderService(session).create(
            tenant_two.id, customer.id, [OrderItemRequest(product.id, quantity=1)]
        )
    assert error.value.code == "CUSTOMER_NOT_FOUND"


def test_financial_summary_includes_only_posted_transactions(
    session: Session, tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = tenants
    finance = FinanceService(session)
    finance.record_transaction(tenant.id, TransactionType.REVENUE, Decimal("100.00"), "Sale")
    finance.record_expense(tenant.id, Decimal("30.00"), "Hosting")
    finance.record_transaction(
        tenant.id,
        TransactionType.REVENUE,
        Decimal("15.00"),
        "Pending sale",
        status=TransactionStatus.PENDING,
    )

    summary = finance.summary(tenant.id, date.today(), date.today())

    assert summary.revenue == Decimal("100.00")
    assert summary.expenses == Decimal("30.00")
    assert summary.net == Decimal("70.00")
    assert summary.transaction_count == 2
