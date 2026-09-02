"""Finance service with explicit transaction status semantics."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from commerceops.domain.enums import TransactionStatus, TransactionType
from commerceops.domain.invariants import DomainError, require_positive_amount
from commerceops.domain.models import Transaction
from commerceops.repositories import FinanceRepository, OrderRepository


@dataclass(frozen=True)
class FinancialSummary:
    revenue: Decimal
    expenses: Decimal
    transaction_count: int

    @property
    def net(self) -> Decimal:
        return self.revenue - self.expenses


class FinanceService:
    def __init__(
        self,
        session: Session,
        finance_repository: FinanceRepository | None = None,
        order_repository: OrderRepository | None = None,
    ) -> None:
        self.session = session
        self.finance_repository = finance_repository or FinanceRepository()
        self.order_repository = order_repository or OrderRepository()

    def summary(self, tenant_id: UUID, period_start: date, period_end: date) -> FinancialSummary:
        if period_start > period_end:
            raise DomainError("INVALID_PERIOD", "Period start must not be after period end.")
        revenue, expenses, count = self.finance_repository.summary(
            self.session, tenant_id, period_start, period_end
        )
        return FinancialSummary(revenue, expenses, count)

    def list_transactions(
        self,
        tenant_id: UUID,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        limit: int = 20,
    ) -> Sequence[Transaction]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return self.finance_repository.list(
            self.session, tenant_id, transaction_type, status, limit
        )

    def record_transaction(
        self,
        tenant_id: UUID,
        transaction_type: TransactionType,
        amount: Decimal,
        description: str,
        order_id: UUID | None = None,
        status: TransactionStatus = TransactionStatus.POSTED,
    ) -> Transaction:
        require_positive_amount(amount)
        if (
            order_id is not None
            and self.order_repository.get(self.session, tenant_id, order_id) is None
        ):
            raise DomainError("ORDER_NOT_FOUND", "Order was not found.")
        transaction = Transaction(
            tenant_id=tenant_id,
            type=transaction_type,
            status=status,
            amount=amount,
            description=description.strip(),
            order_id=order_id,
        )
        self.finance_repository.add(self.session, transaction)
        self.session.flush()
        return transaction

    def record_expense(self, tenant_id: UUID, amount: Decimal, description: str) -> Transaction:
        return self.record_transaction(tenant_id, TransactionType.EXPENSE, amount, description)
