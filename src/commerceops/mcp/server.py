"""CommerceOps MCP server exposing authorized, tenant-scoped business tools."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from uuid import UUID

from mcp.server import MCPServer

from commerceops.domain.enums import (
    InventoryMovementType,
    OrderStatus,
    PaymentStatus,
    TransactionStatus,
    TransactionType,
)
from commerceops.mcp.context import FixedRuntimeContextProvider, RuntimeContextProvider
from commerceops.mcp.tools.executor import SessionFactory, ToolExecutor, default_session_factory
from commerceops.mcp.tools.schemas import ToolResult


def create_mcp_server(
    context_provider: RuntimeContextProvider | None = None,
    session_factory: SessionFactory = default_session_factory,
) -> MCPServer:
    """Build a server whose trusted identity is invisible to tool callers."""
    executor = ToolExecutor(
        context_provider or FixedRuntimeContextProvider(None), session_factory
    )
    server = MCPServer(
        "CommerceOps AI",
        instructions="Use only the tools assigned to the active specialist.",
    )

    def call(name: str, arguments: Mapping[str, object]) -> ToolResult:
        return executor.execute(name, arguments)

    @server.tool()
    def search_customers(query: str, limit: int = 10) -> ToolResult:
        """Search tenant-owned customers by name."""
        return call("search_customers", {"query": query, "limit": limit})

    @server.tool()
    def create_customer(
        name: str, email: str | None = None, phone: str | None = None
    ) -> ToolResult:
        """Create a customer in the active tenant."""
        return call("create_customer", {"name": name, "email": email, "phone": phone})

    @server.tool()
    def search_products(
        query: str, active_only: bool = True, limit: int = 10
    ) -> ToolResult:
        """Search tenant-owned products."""
        return call(
            "search_products",
            {"query": query, "active_only": active_only, "limit": limit},
        )

    @server.tool()
    def list_orders(
        customer_id: UUID | None = None,
        status: OrderStatus | None = None,
        limit: int = 20,
    ) -> ToolResult:
        """List tenant-owned orders with optional customer and status filters."""
        return call(
            "list_orders",
            {"customer_id": customer_id, "status": status, "limit": limit},
        )

    @server.tool()
    def create_order(customer_id: UUID, items: list[dict[str, object]]) -> ToolResult:
        """Create an order using previously resolved customer and product IDs."""
        return call("create_order", {"customer_id": customer_id, "items": items})

    @server.tool()
    def update_order(
        order_id: UUID,
        status: OrderStatus,
        payment_status: PaymentStatus | None = None,
    ) -> ToolResult:
        """Update a tenant-owned order."""
        return call(
            "update_order",
            {"order_id": order_id, "status": status, "payment_status": payment_status},
        )

    @server.tool()
    def get_inventory_level(product_id: UUID) -> ToolResult:
        """Get the current ledger-derived stock for a tenant-owned product."""
        return call("get_inventory_level", {"product_id": product_id})

    @server.tool()
    def list_inventory_movements(
        product_id: UUID | None = None, limit: int = 20
    ) -> ToolResult:
        """List tenant-owned inventory ledger entries."""
        return call(
            "list_inventory_movements", {"product_id": product_id, "limit": limit}
        )

    @server.tool()
    def create_inventory_movement(
        product_id: UUID,
        movement_type: InventoryMovementType,
        quantity: int,
        reason: str,
    ) -> ToolResult:
        """Add an entry to the inventory ledger."""
        return call(
            "create_inventory_movement",
            {
                "product_id": product_id,
                "movement_type": movement_type,
                "quantity": quantity,
                "reason": reason,
            },
        )

    @server.tool()
    def get_financial_summary(period_start: date, period_end: date) -> ToolResult:
        """Summarize posted tenant transactions for an inclusive date period."""
        return call(
            "get_financial_summary",
            {"period_start": period_start, "period_end": period_end},
        )

    @server.tool()
    def list_transactions(
        type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        limit: int = 20,
    ) -> ToolResult:
        """List tenant-owned financial transactions."""
        return call(
            "list_transactions", {"type": type, "status": status, "limit": limit}
        )

    @server.tool()
    def create_transaction(
        type: TransactionType,
        amount: Decimal,
        description: str,
        order_id: UUID | None = None,
    ) -> ToolResult:
        """Create a revenue or expense transaction in the active tenant."""
        return call(
            "create_transaction",
            {
                "type": type,
                "amount": amount,
                "description": description,
                "order_id": order_id,
            },
        )

    return server


mcp = create_mcp_server()


def main() -> None:
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8001,
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
