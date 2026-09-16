"""Deterministic tool policy and human approval controls."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

from commerceops.config import settings
from commerceops.graph.state import ProposedAction, ResolvedEntity
from commerceops.mcp.authorization import is_authorized
from commerceops.mcp.context import Specialist
from commerceops.mcp.tools.schemas import (
    CreateCustomerInput,
    CreateInventoryMovementInput,
    CreateOrderInput,
    CreateTransactionInput,
    GetFinancialSummaryInput,
    GetInventoryLevelInput,
    ListInventoryMovementsInput,
    ListOrdersInput,
    ListTransactionsInput,
    SearchCustomersInput,
    SearchProductsInput,
    UpdateOrderInput,
)

RiskLevel = Literal["low", "medium", "high"]

READ_TOOLS = frozenset(
    {
        "search_customers", "search_products", "list_orders", "get_inventory_level",
        "list_inventory_movements", "get_financial_summary", "list_transactions",
    }
)
WRITE_TOOLS = frozenset(
    {
        "create_customer",
        "create_order",
        "update_order",
        "create_inventory_movement",
        "create_transaction",
    }
)
TOOL_INPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "search_customers": SearchCustomersInput,
    "create_customer": CreateCustomerInput,
    "search_products": SearchProductsInput,
    "list_orders": ListOrdersInput,
    "create_order": CreateOrderInput,
    "update_order": UpdateOrderInput,
    "get_inventory_level": GetInventoryLevelInput,
    "list_inventory_movements": ListInventoryMovementsInput,
    "create_inventory_movement": CreateInventoryMovementInput,
    "get_financial_summary": GetFinancialSummaryInput,
    "list_transactions": ListTransactionsInput,
    "create_transaction": CreateTransactionInput,
}


class PolicyDecision(BaseModel):
    allowed: bool
    requires_confirmation: bool
    reason: str
    violations: list[str]


@dataclass(frozen=True)
class PolicyContext:
    tenant_id: str
    specialist: Specialist
    resolved_entities: Sequence[ResolvedEntity] = ()
    available_quantity: int | None = None


def classify_risk(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    available_quantity: int | None = None,
) -> RiskLevel:
    if tool_name in READ_TOOLS:
        return "low"
    if tool_name == "update_order" and (
        arguments.get("status") == "CANCELLED" or arguments.get("payment_status") == "REFUNDED"
    ):
        return "high"
    if tool_name == "create_inventory_movement":
        quantity = _integer(arguments.get("quantity"))
        if abs(quantity) > settings.large_inventory_movement:
            return "high"
        if (
            arguments.get("movement_type") == "OUT"
            and available_quantity is not None
            and available_quantity - quantity < 0
        ):
            return "high"
    if tool_name == "create_transaction":
        try:
            amount = Decimal(str(arguments.get("amount", "0")))
        except InvalidOperation:
            amount = Decimal("0")
        if amount > settings.large_transaction_amount:
            return "high"
    return "medium"


def propose_action(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    available_quantity: int | None = None,
) -> ProposedAction:
    risk = classify_risk(tool_name, arguments, available_quantity=available_quantity)
    return ProposedAction(
        tool_name=tool_name,
        arguments=dict(arguments),
        risk_level=risk,
        requires_confirmation=risk == "high",
    )


def evaluate_policy(
    action: ProposedAction,
    context: PolicyContext,
    *,
    proposed_write_count: int = 1,
) -> PolicyDecision:
    """Validate scope, trusted context, schema, resolution, batching, and risk."""

    violations: list[str] = []
    try:
        UUID(context.tenant_id)
    except ValueError:
        violations.append("INVALID_TENANT_CONTEXT")

    if not is_authorized(context.specialist, action.tool_name):
        violations.append("TOOL_OUT_OF_SCOPE")

    schema = TOOL_INPUT_SCHEMAS.get(action.tool_name)
    if schema is None:
        violations.append("UNKNOWN_TOOL")
    else:
        try:
            schema.model_validate(action.arguments)
        except ValidationError:
            violations.append("INVALID_TOOL_INPUT")

    if action.tool_name in WRITE_TOOLS:
        violations.extend(_resolution_violations(action, context.resolved_entities))

    if violations:
        return PolicyDecision(
            allowed=False,
            requires_confirmation=False,
            reason="The proposed action violates runtime policy.",
            violations=_deduplicate(violations),
        )

    if proposed_write_count > settings.max_batch_write:
        return PolicyDecision(
            allowed=True,
            requires_confirmation=True,
            reason=f"The request proposes {proposed_write_count} writes; approval is required.",
            violations=["BATCH_WRITE_LIMIT_EXCEEDED"],
        )

    if action.risk_level == "high":
        return PolicyDecision(
            allowed=True,
            requires_confirmation=True,
            reason=_risk_reason(action, context.available_quantity),
            violations=[],
        )

    return PolicyDecision(
        allowed=True,
        requires_confirmation=False,
        reason=f"{action.risk_level.title()}-risk action is allowed.",
        violations=[],
    )


def evaluate_batch(
    actions: Sequence[ProposedAction], context: PolicyContext
) -> PolicyDecision:
    """Evaluate a proposed batch without ever partially executing it."""

    write_count = sum(action.tool_name in WRITE_TOOLS for action in actions)
    decisions = [
        evaluate_policy(action, context, proposed_write_count=write_count) for action in actions
    ]
    violations = _deduplicate(
        [violation for decision in decisions for violation in decision.violations]
    )
    if any(not decision.allowed for decision in decisions):
        return PolicyDecision(
            allowed=False,
            requires_confirmation=False,
            reason="At least one proposed action violates runtime policy.",
            violations=violations,
        )
    if any(decision.requires_confirmation for decision in decisions):
        return PolicyDecision(
            allowed=True,
            requires_confirmation=True,
            reason="The proposed action batch requires approval.",
            violations=violations,
        )
    return PolicyDecision(
        allowed=True,
        requires_confirmation=False,
        reason="The proposed action batch is allowed.",
        violations=[],
    )


def require_policy_approval(
    action: ProposedAction,
    context: PolicyContext,
    *,
    proposed_write_count: int = 1,
) -> tuple[PolicyDecision, bool]:
    """Evaluate an action and pause the graph when explicit approval is required."""

    decision = evaluate_policy(action, context, proposed_write_count=proposed_write_count)
    if not decision.allowed:
        return decision, False
    if not decision.requires_confirmation:
        return decision, True

    response = interrupt(
        {
            "message": "Please approve this action.",
            "action": action.model_dump(mode="json"),
            "risk_reason": decision.reason,
        }
    )
    approved = response is True or (
        isinstance(response, Mapping) and response.get("approved") is True
    )
    return decision, approved


def approval_grants(
    action: ProposedAction, *, available_quantity: int | None = None
) -> frozenset[str]:
    if (
        action.tool_name == "create_inventory_movement"
        and action.arguments.get("movement_type") == "OUT"
        and available_quantity is not None
        and available_quantity - _integer(action.arguments.get("quantity")) < 0
    ):
        return frozenset({"negative_inventory"})
    return frozenset()


def _resolution_violations(
    action: ProposedAction, entities: Sequence[ResolvedEntity]
) -> list[str]:
    resolved = {(entity.entity_type, entity.id) for entity in entities}
    arguments = action.arguments
    violations: list[str] = []
    if action.tool_name == "create_order":
        if ("customer", str(arguments.get("customer_id", ""))) not in resolved:
            violations.append("CUSTOMER_NOT_RESOLVED")
        items = arguments.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping) and (
                    "product", str(item.get("product_id", ""))
                ) not in resolved:
                    violations.append("PRODUCT_NOT_RESOLVED")
    elif action.tool_name == "update_order":
        if ("order", str(arguments.get("order_id", ""))) not in resolved:
            violations.append("ORDER_NOT_RESOLVED")
    elif action.tool_name == "create_inventory_movement":
        if ("product", str(arguments.get("product_id", ""))) not in resolved:
            violations.append("PRODUCT_NOT_RESOLVED")
    elif action.tool_name == "create_transaction" and arguments.get("order_id") is not None:
        if ("order", str(arguments["order_id"])) not in resolved:
            violations.append("ORDER_NOT_RESOLVED")
    return _deduplicate(violations)


def _risk_reason(action: ProposedAction, available_quantity: int | None) -> str:
    if action.tool_name == "update_order":
        return "Cancellation or refund-like order changes are high risk."
    if action.tool_name == "create_transaction":
        return "The transaction amount exceeds the configured approval threshold."
    if action.tool_name == "create_inventory_movement":
        quantity = _integer(action.arguments.get("quantity"))
        if (
            action.arguments.get("movement_type") == "OUT"
            and available_quantity is not None
            and available_quantity - quantity < 0
        ):
            return "The movement would make inventory negative."
        return "The inventory movement exceeds the configured approval threshold."
    return "The action is classified as high risk."


def _integer(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))
