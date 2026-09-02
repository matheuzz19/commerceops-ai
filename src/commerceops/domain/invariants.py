"""Business constants and deterministic validation helpers."""

from decimal import Decimal

MAX_BATCH_WRITE = 5
LARGE_INVENTORY_MOVEMENT = 100
LARGE_TRANSACTION_AMOUNT = Decimal("1000.00")


class DomainError(Exception):
    """A safe, stable error that application boundaries may translate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_positive_quantity(quantity: int) -> None:
    if quantity <= 0:
        raise DomainError("INVALID_QUANTITY", "Quantity must be positive.")


def require_positive_amount(amount: Decimal) -> None:
    if amount <= Decimal("0"):
        raise DomainError("INVALID_AMOUNT", "Amount must be positive.")
