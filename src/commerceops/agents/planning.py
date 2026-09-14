"""Structured specialist plans for M5 workflows."""

from collections.abc import Awaitable
from datetime import date
from decimal import Decimal
from typing import Generic, Literal, Protocol, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from commerceops.domain.enums import (
    InventoryMovementType,
    OrderStatus,
    PaymentStatus,
    TransactionStatus,
    TransactionType,
)


class SalesItemPlan(BaseModel):
    product_query: str = Field(min_length=1)
    quantity: int = Field(ge=1)


class SalesPlan(BaseModel):
    action: Literal[
        "search_customers",
        "create_customer",
        "search_products",
        "list_orders",
        "create_order",
        "update_order",
        "clarify",
    ]
    query: str | None = None
    customer_query: str | None = None
    customer_name: str | None = None
    email: str | None = None
    phone: str | None = None
    order_reference: str | None = None
    order_status: OrderStatus | None = None
    payment_status: PaymentStatus | None = None
    items: list[SalesItemPlan] = Field(default_factory=list)
    clarification: str | None = None


class InventoryPlan(BaseModel):
    action: Literal["get_level", "list_movements", "create_movement", "clarify"]
    product_query: str | None = None
    movement_type: InventoryMovementType | None = None
    quantity: int | None = None
    reason: str | None = None
    clarification: str | None = None


class FinancePlan(BaseModel):
    action: Literal["summary", "list_transactions", "create_expense", "clarify"]
    period_start: date | None = None
    period_end: date | None = None
    relative_period: Literal["current_month", "previous_month"] | None = None
    transaction_type: TransactionType | None = None
    transaction_status: TransactionStatus | None = None
    amount: Decimal | None = None
    description: str | None = None
    clarification: str | None = None


PlanT_co = TypeVar("PlanT_co", bound=BaseModel, covariant=True)


class PlanProvider(Protocol, Generic[PlanT_co]):
    def plan(self, query: str) -> Awaitable[PlanT_co]: ...


PlanT = TypeVar("PlanT", bound=BaseModel)


class LangChainPlanProvider(Generic[PlanT]):
    """Tool-free structured planner for one specialist."""

    def __init__(self, model: BaseChatModel, schema: type[PlanT], prompt: str) -> None:
        self._planner = model.with_structured_output(schema, method="json_schema")
        self._prompt = prompt
        self._schema = schema

    async def plan(self, query: str) -> PlanT:
        result = await self._planner.ainvoke(
            [SystemMessage(content=self._prompt), HumanMessage(content=query)]
        )
        return self._schema.model_validate(result)


SALES_PROMPT = """Plan one Sales operation using the schema. Sales owns customers,
product catalog searches, and orders. Use natural-language customer_query and
product_query values; never invent database IDs. Ask for clarification when a
required name, item quantity, or requested state is missing. Do not execute tools."""

INVENTORY_PROMPT = """Plan one Inventory operation using the schema. Every product-
specific request must provide a natural-language product_query; never invent a
database ID. Ask for clarification when required movement details are missing.
Do not execute tools."""

FINANCE_PROMPT = """Plan one Finance operation using the schema. Use relative_period
for 'this month' or 'last month'; otherwise use explicit ISO dates. The M5 write
workflow supports expenses without linked order IDs. Ask for clarification when
required dates, amount, or description is missing. Do not execute tools."""
