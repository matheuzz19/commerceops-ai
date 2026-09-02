"""Deterministic customer application service."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from commerceops.domain.models import Customer
from commerceops.repositories import CustomerRepository


class CustomerService:
    def __init__(self, session: Session, repository: CustomerRepository | None = None) -> None:
        self.session = session
        self.repository = repository or CustomerRepository()

    def create(
        self, tenant_id: UUID, name: str, email: str | None = None, phone: str | None = None
    ) -> Customer:
        customer = Customer(tenant_id=tenant_id, name=name.strip(), email=email, phone=phone)
        self.repository.add(self.session, customer)
        self.session.flush()
        return customer

    def search(self, tenant_id: UUID, query: str, limit: int = 10) -> Sequence[Customer]:
        return self.repository.search(
            self.session, tenant_id, query.strip(), _validated_limit(limit)
        )

    def get(self, tenant_id: UUID, customer_id: UUID) -> Customer | None:
        return self.repository.get(self.session, tenant_id, customer_id)


def _validated_limit(limit: int) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return limit
