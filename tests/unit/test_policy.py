from uuid import uuid4

from commerceops.graph.policy import (
    PolicyContext,
    classify_risk,
    evaluate_batch,
    evaluate_policy,
    propose_action,
)
from commerceops.graph.state import ResolvedEntity
from commerceops.mcp.context import Specialist


def test_policy_enforces_scope_schema_and_entity_resolution() -> None:
    tenant_id = str(uuid4())
    customer_id = str(uuid4())
    product_id = str(uuid4())
    action = propose_action(
        "create_order",
        {
            "customer_id": customer_id,
            "items": [{"product_id": product_id, "quantity": 1}],
        },
    )

    denied_scope = evaluate_policy(
        action, PolicyContext(tenant_id, Specialist.INVENTORY)
    )
    unresolved = evaluate_policy(
        action, PolicyContext(tenant_id, Specialist.SALES)
    )
    allowed = evaluate_policy(
        action,
        PolicyContext(
            tenant_id,
            Specialist.SALES,
            [
                ResolvedEntity(
                    entity_type="customer",
                    id=customer_id,
                    display_name="Customer",
                    source_tool_call_id="customer-audit",
                ),
                ResolvedEntity(
                    entity_type="product",
                    id=product_id,
                    display_name="Product",
                    source_tool_call_id="product-audit",
                ),
            ],
        ),
    )

    assert denied_scope.allowed is False
    assert "TOOL_OUT_OF_SCOPE" in denied_scope.violations
    assert unresolved.allowed is False
    assert unresolved.violations == ["CUSTOMER_NOT_RESOLVED", "PRODUCT_NOT_RESOLVED"]
    assert allowed.allowed is True
    assert allowed.requires_confirmation is False


def test_risk_classification_uses_configured_high_risk_rules() -> None:
    assert classify_risk(
        "update_order", {"status": "CANCELLED", "payment_status": None}
    ) == "high"
    assert classify_risk(
        "create_inventory_movement",
        {"movement_type": "OUT", "quantity": 4},
        available_quantity=3,
    ) == "high"
    assert classify_risk(
        "create_transaction", {"amount": "1000.01"}
    ) == "high"
    assert classify_risk("search_products", {"query": "keyboard"}) == "low"


def test_more_than_five_writes_requires_confirmation() -> None:
    context = PolicyContext(str(uuid4()), Specialist.SALES)
    actions = [
        propose_action(
            "create_customer",
            {"name": f"Customer {index}", "email": None, "phone": None},
        )
        for index in range(6)
    ]

    decision = evaluate_batch(actions, context)

    assert decision.allowed is True
    assert decision.requires_confirmation is True
    assert decision.violations == ["BATCH_WRITE_LIMIT_EXCEEDED"]
