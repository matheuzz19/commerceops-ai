"""Idempotent synthetic fixtures for local development and demonstrations."""

from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from commerceops.domain.enums import (
    InventoryMovementType,
    OrderStatus,
    PaymentStatus,
    TransactionStatus,
    TransactionType,
    UserRole,
)
from commerceops.domain.models import (
    Customer,
    InventoryMovement,
    Order,
    OrderItem,
    Product,
    Tenant,
    Transaction,
    User,
)

SEED_NAMESPACE = UUID("8fa5c8c6-f2d3-4b25-a532-93f2d7dd49ba")


def _seed_id(name: str) -> UUID:
    return uuid5(SEED_NAMESPACE, name)


def _add_if_missing(
    session: Session, model: type[object], identifier: UUID, **values: object
) -> None:
    if session.get(model, identifier) is None:
        session.add(model(id=identifier, **values))  # type: ignore[call-arg]


def seed_database(session: Session) -> None:
    """Add a small, deterministic dataset for two isolated synthetic tenants.

    The caller controls commit/rollback, allowing this function to be reused by
    local setup scripts and transactional tests.
    """
    northwind_id = _seed_id("tenant:sample-north")
    southwind_id = _seed_id("tenant:sample-south")
    _add_if_missing(session, Tenant, northwind_id, name="Sample North Store")
    _add_if_missing(session, Tenant, southwind_id, name="Sample South Store")

    north_user_id = _seed_id("user:sample-north:admin")
    north_customer_id = _seed_id("customer:sample-north:river")
    south_customer_id = _seed_id("customer:sample-south:harbor")
    north_product_id = _seed_id("product:sample-north:keyboard")
    south_product_id = _seed_id("product:sample-south:lamp")
    north_order_id = _seed_id("order:sample-north:001")

    _add_if_missing(
        session,
        User,
        north_user_id,
        tenant_id=northwind_id,
        email="admin@sample-north.test",
        role=UserRole.ADMIN,
    )
    _add_if_missing(
        session,
        Customer,
        north_customer_id,
        tenant_id=northwind_id,
        name="River Example",
        email="river@example.test",
        phone="+15550100",
    )
    _add_if_missing(
        session,
        Customer,
        south_customer_id,
        tenant_id=southwind_id,
        name="Harbor Example",
        email="harbor@example.test",
        phone="+15550200",
    )
    _add_if_missing(
        session,
        Product,
        north_product_id,
        tenant_id=northwind_id,
        name="Compact Keyboard",
        sku="NORTH-KEY-01",
        price=Decimal("49.90"),
        active=True,
    )
    _add_if_missing(
        session,
        Product,
        south_product_id,
        tenant_id=southwind_id,
        name="Desk Lamp",
        sku="SOUTH-LAMP-01",
        price=Decimal("35.00"),
        active=True,
    )
    _add_if_missing(
        session,
        Order,
        north_order_id,
        tenant_id=northwind_id,
        customer_id=north_customer_id,
        status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.UNPAID,
        total_amount=Decimal("99.80"),
    )
    _add_if_missing(
        session,
        OrderItem,
        _seed_id("order-item:sample-north:001:1"),
        tenant_id=northwind_id,
        order_id=north_order_id,
        product_id=north_product_id,
        quantity=2,
        unit_price=Decimal("49.90"),
    )
    _add_if_missing(
        session,
        InventoryMovement,
        _seed_id("movement:sample-north:opening"),
        tenant_id=northwind_id,
        product_id=north_product_id,
        movement_type=InventoryMovementType.IN,
        quantity=25,
        reason="Synthetic opening stock",
    )
    _add_if_missing(
        session,
        InventoryMovement,
        _seed_id("movement:sample-south:opening"),
        tenant_id=southwind_id,
        product_id=south_product_id,
        movement_type=InventoryMovementType.IN,
        quantity=12,
        reason="Synthetic opening stock",
    )
    _add_if_missing(
        session,
        Transaction,
        _seed_id("transaction:sample-north:pending-revenue"),
        tenant_id=northwind_id,
        order_id=north_order_id,
        type=TransactionType.REVENUE,
        status=TransactionStatus.PENDING,
        amount=Decimal("99.80"),
        description="Synthetic pending order revenue",
    )
    _add_if_missing(
        session,
        Transaction,
        _seed_id("transaction:sample-south:expense"),
        tenant_id=southwind_id,
        order_id=None,
        type=TransactionType.EXPENSE,
        status=TransactionStatus.POSTED,
        amount=Decimal("20.00"),
        description="Synthetic operating expense",
    )

    session.flush()
