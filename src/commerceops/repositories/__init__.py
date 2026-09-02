"""Tenant-scoped repository implementations."""

from commerceops.repositories.core import (
    CustomerRepository,
    FinanceRepository,
    InventoryRepository,
    OrderRepository,
    ProductRepository,
)

__all__ = [
    "CustomerRepository",
    "FinanceRepository",
    "InventoryRepository",
    "OrderRepository",
    "ProductRepository",
]
