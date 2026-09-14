"""Validated MCP tool contracts and structured result models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from commerceops.domain.enums import (
    InventoryMovementType,
    OrderStatus,
    PaymentStatus,
    TransactionStatus,
    TransactionType,
)


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchCustomersInput(ToolSchema):
    query: str = Field(min_length=1, max_length=255)
    limit: int = Field(default=10, ge=1, le=100)


class CreateCustomerInput(ToolSchema):
    name: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)


class SearchProductsInput(ToolSchema):
    query: str = Field(min_length=1, max_length=255)
    active_only: bool = True
    limit: int = Field(default=10, ge=1, le=100)


class ListOrdersInput(ToolSchema):
    customer_id: UUID | None = None
    status: OrderStatus | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CreateOrderItemInput(ToolSchema):
    product_id: UUID
    quantity: int = Field(ge=1)


class CreateOrderInput(ToolSchema):
    customer_id: UUID
    items: list[CreateOrderItemInput] = Field(min_length=1, max_length=100)


class UpdateOrderInput(ToolSchema):
    order_id: UUID
    status: OrderStatus
    payment_status: PaymentStatus | None = None

    @model_validator(mode="after")
    def reject_draft_status(self) -> "UpdateOrderInput":
        if self.status == OrderStatus.DRAFT:
            raise ValueError("status must be CONFIRMED, CANCELLED, or FULFILLED")
        return self


class GetInventoryLevelInput(ToolSchema):
    product_id: UUID


class ListInventoryMovementsInput(ToolSchema):
    product_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CreateInventoryMovementInput(ToolSchema):
    product_id: UUID
    movement_type: InventoryMovementType
    quantity: int
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_quantity(self) -> "CreateInventoryMovementInput":
        if self.movement_type in {
            InventoryMovementType.IN,
            InventoryMovementType.OUT,
        } and self.quantity <= 0:
            raise ValueError("IN and OUT quantities must be positive")
        if self.movement_type == InventoryMovementType.ADJUSTMENT and self.quantity == 0:
            raise ValueError("ADJUSTMENT quantity cannot be zero")
        return self


class GetFinancialSummaryInput(ToolSchema):
    period_start: date
    period_end: date


class ListTransactionsInput(ToolSchema):
    type: TransactionType | None = None
    status: TransactionStatus | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CreateTransactionInput(ToolSchema):
    type: TransactionType
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    description: str = Field(min_length=1, max_length=2000)
    order_id: UUID | None = None


class CustomerData(ToolSchema):
    id: UUID
    name: str
    email: str | None
    phone: str | None


class CustomerResultData(ToolSchema):
    customer: CustomerData


class CustomerSearchData(ToolSchema):
    customers: list[CustomerData]


class ProductData(ToolSchema):
    id: UUID
    name: str
    sku: str
    price: Decimal
    active: bool


class ProductSearchData(ToolSchema):
    products: list[ProductData]


class OrderItemData(ToolSchema):
    product_id: UUID
    quantity: int
    unit_price: Decimal


class OrderData(ToolSchema):
    id: UUID
    customer_id: UUID
    status: OrderStatus
    payment_status: PaymentStatus
    total_amount: Decimal
    created_at: datetime
    items: list[OrderItemData]


class OrderResultData(ToolSchema):
    order: OrderData


class OrderListData(ToolSchema):
    orders: list[OrderData]


class InventoryLevelData(ToolSchema):
    product_id: UUID
    available_quantity: int


class InventoryMovementData(ToolSchema):
    id: UUID
    product_id: UUID
    movement_type: InventoryMovementType
    quantity: int
    reason: str
    created_at: datetime


class InventoryMovementResultData(ToolSchema):
    movement: InventoryMovementData


class InventoryMovementListData(ToolSchema):
    movements: list[InventoryMovementData]


class FinancialSummaryData(ToolSchema):
    revenue: Decimal
    expenses: Decimal
    net: Decimal
    transaction_count: int


class TransactionData(ToolSchema):
    id: UUID
    order_id: UUID | None
    type: TransactionType
    status: TransactionStatus
    amount: Decimal
    description: str
    created_at: datetime


class TransactionResultData(ToolSchema):
    transaction: TransactionData


class TransactionListData(ToolSchema):
    transactions: list[TransactionData]


class ToolErrorData(ToolSchema):
    code: str
    message: str


DataT = TypeVar("DataT", bound=BaseModel)


class TypedToolResult(ToolSchema, Generic[DataT]):
    ok: bool
    data: DataT | None
    error: ToolErrorData | None
    audit_id: str


class ToolResult(ToolSchema):
    """Wire-safe envelope shared by every MCP tool."""

    ok: bool
    data: dict[str, JsonValue] | None
    error: ToolErrorData | None
    audit_id: str

    @model_validator(mode="after")
    def validate_shape(self) -> "ToolResult":
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("successful tool results require data and no error")
        if not self.ok and (self.data is not None or self.error is None):
            raise ValueError("failed tool results require an error and no data")
        return self

