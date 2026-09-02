"""SQLAlchemy persistence models for the CommerceOps business domain."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from commerceops.domain.enums import (
    InventoryMovementType,
    OrderStatus,
    PaymentStatus,
    TransactionStatus,
    TransactionType,
    UserRole,
)


class Base(DeclarativeBase):
    """Base class used by migrations and all ORM models."""


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    users: Mapped[list[User]] = relationship(back_populates="tenant")
    customers: Mapped[list[Customer]] = relationship(back_populates="tenant")
    products: Mapped[list[Product]] = relationship(back_populates="tenant")
    orders: Mapped[list[Order]] = relationship(back_populates="tenant")
    inventory_movements: Mapped[list[InventoryMovement]] = relationship(back_populates="tenant")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), nullable=False, default=UserRole.OPERATOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    tenant: Mapped[Tenant] = relationship(back_populates="users")
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    tenant: Mapped[Tenant] = relationship(back_populates="customers")
    orders: Mapped[list[Order]] = relationship(back_populates="customer")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    tenant: Mapped[Tenant] = relationship(back_populates="products")
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="product")
    inventory_movements: Mapped[list[InventoryMovement]] = relationship(back_populates="product")
    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=20), nullable=False, default=OrderStatus.DRAFT
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=20),
        nullable=False,
        default=PaymentStatus.UNPAID,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    tenant: Mapped[Tenant] = relationship(back_populates="orders")
    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="order_items")


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[InventoryMovementType] = mapped_column(
        Enum(InventoryMovementType, native_enum=False, length=20), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    tenant: Mapped[Tenant] = relationship(back_populates="inventory_movements")
    product: Mapped[Product] = relationship(back_populates="inventory_movements")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
    )
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, native_enum=False, length=20), nullable=False
    )
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, native_enum=False, length=20),
        nullable=False,
        default=TransactionStatus.PENDING,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    tenant: Mapped[Tenant] = relationship(back_populates="transactions")
    order: Mapped[Order | None] = relationship(back_populates="transactions")
