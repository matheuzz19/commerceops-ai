from decimal import Decimal

from commerceops.agents.planning import FinancePlan


def test_finance_transport_uses_simple_strings_and_retains_exact_decimal_validation() -> None:
    amount_schema = FinancePlan.model_json_schema()["properties"]["amount"]["anyOf"]
    assert {"type": "string"} in amount_schema
    assert all("pattern" not in option for option in amount_schema)
    plan = FinancePlan(action="create_expense", amount="0.10", description="Synthetic expense")
    assert plan.amount == Decimal("0.10")
