"""Code-enforced specialist-to-tool authorization matrix."""

from commerceops.mcp.context import Specialist

SALES_TOOLS = frozenset(
    {
        "search_customers",
        "create_customer",
        "search_products",
        "list_orders",
        "create_order",
        "update_order",
    }
)
INVENTORY_TOOLS = frozenset(
    {
        "get_inventory_level",
        "list_inventory_movements",
        "create_inventory_movement",
    }
)
FINANCE_TOOLS = frozenset(
    {"get_financial_summary", "list_transactions", "create_transaction"}
)

TOOL_AUTHORIZATION: dict[Specialist, frozenset[str]] = {
    Specialist.SALES: SALES_TOOLS,
    Specialist.INVENTORY: INVENTORY_TOOLS,
    Specialist.FINANCE: FINANCE_TOOLS,
    Specialist.GENERAL: frozenset(),
}


def is_authorized(specialist: Specialist, tool_name: str) -> bool:
    return tool_name in TOOL_AUTHORIZATION[specialist]

