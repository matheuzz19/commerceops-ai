"""Tenant-scoped persistence operations.

Services use these small repositories instead of constructing unscoped queries.
That makes the tenant filter an unavoidable part of every business access path.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from commerceops.domain.enums import InventoryMovementType, TransactionStatus, TransactionType
from commerceops.domain.models import (
    Customer,
    InventoryMovement,
    Order,
    Product,
    Transaction,
)


class CustomerRepository:
    def get(self, session: Session, tenant_id: UUID, customer_id: UUID) -> Customer | None:
        return session.scalar(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
        )

    def search(
        self, session: Session, tenant_id: UUID, query: str, limit: int = 10
    ) -> Sequence[Customer]:
        statement = (
            select(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.name.ilike(f"%{query}%"))
            .order_by(Customer.name)
            .limit(limit)
        )
        return session.scalars(statement).all()

    def add(self, session: Session, customer: Customer) -> Customer:
        session.add(customer)
        return customer


class ProductRepository:
    def get(self, session: Session, tenant_id: UUID, product_id: UUID) -> Product | None:
        return session.scalar(
            select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id)
        )

    def get_many(
        self, session: Session, tenant_id: UUID, product_ids: set[UUID]
    ) -> Sequence[Product]:
        if not product_ids:
            return []
        statement = select(Product).where(
            Product.tenant_id == tenant_id,
            Product.id.in_(product_ids),
        )
        return session.scalars(statement).all()

    def search(
        self,
        session: Session,
        tenant_id: UUID,
        query: str,
        active_only: bool = True,
        limit: int = 10,
    ) -> Sequence[Product]:
        statement = select(Product).where(
            Product.tenant_id == tenant_id,
            Product.name.ilike(f"%{query}%"),
        )
        if active_only:
            statement = statement.where(Product.active.is_(True))
        return session.scalars(statement.order_by(Product.name).limit(limit)).all()

    def add(self, session: Session, product: Product) -> Product:
        session.add(product)
        return product


class OrderRepository:
    def get(self, session: Session, tenant_id: UUID, order_id: UUID) -> Order | None:
        return session.scalar(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.tenant_id == tenant_id, Order.id == order_id)
        )

    def list_for_customer(
        self, session: Session, tenant_id: UUID, customer_id: UUID | None = None, limit: int = 20
    ) -> Sequence[Order]:
        statement = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.tenant_id == tenant_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        if customer_id is not None:
            statement = statement.where(Order.customer_id == customer_id)
        return session.scalars(statement).all()

    def add(self, session: Session, order: Order) -> Order:
        session.add(order)
        return order


class InventoryRepository:
    def stock_level(self, session: Session, tenant_id: UUID, product_id: UUID) -> int:
        signed_quantity = case(
            (
                InventoryMovement.movement_type == InventoryMovementType.IN,
                InventoryMovement.quantity,
            ),
            (
                InventoryMovement.movement_type == InventoryMovementType.OUT,
                -InventoryMovement.quantity,
            ),
            else_=InventoryMovement.quantity,
        )
        statement = select(func.coalesce(func.sum(signed_quantity), 0)).where(
            InventoryMovement.tenant_id == tenant_id,
            InventoryMovement.product_id == product_id,
        )
        return int(session.scalar(statement) or 0)

    def list(
        self, session: Session, tenant_id: UUID, product_id: UUID | None = None, limit: int = 20
    ) -> Sequence[InventoryMovement]:
        statement = (
            select(InventoryMovement)
            .where(InventoryMovement.tenant_id == tenant_id)
            .order_by(InventoryMovement.created_at.desc())
            .limit(limit)
        )
        if product_id is not None:
            statement = statement.where(InventoryMovement.product_id == product_id)
        return session.scalars(statement).all()

    def add(self, session: Session, movement: InventoryMovement) -> InventoryMovement:
        session.add(movement)
        return movement


class FinanceRepository:
    def list(
        self,
        session: Session,
        tenant_id: UUID,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        limit: int = 20,
    ) -> Sequence[Transaction]:
        statement = (
            select(Transaction)
            .where(Transaction.tenant_id == tenant_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        if transaction_type is not None:
            statement = statement.where(Transaction.type == transaction_type)
        if status is not None:
            statement = statement.where(Transaction.status == status)
        return session.scalars(statement).all()

    def summary(
        self, session: Session, tenant_id: UUID, period_start: date, period_end: date
    ) -> tuple[Decimal, Decimal, int]:
        revenue = func.coalesce(
            func.sum(
                case((Transaction.type == TransactionType.REVENUE, Transaction.amount), else_=0)
            ),
            0,
        )
        expenses = func.coalesce(
            func.sum(
                case((Transaction.type == TransactionType.EXPENSE, Transaction.amount), else_=0)
            ),
            0,
        )
        statement = select(revenue, expenses, func.count(Transaction.id)).where(
            Transaction.tenant_id == tenant_id,
            Transaction.status == TransactionStatus.POSTED,
            Transaction.created_at >= period_start,
            Transaction.created_at < period_end.fromordinal(period_end.toordinal() + 1),
        )
        result = session.execute(statement).one()
        return Decimal(result[0]), Decimal(result[1]), int(result[2])

    def add(self, session: Session, transaction: Transaction) -> Transaction:
        session.add(transaction)
        return transaction
