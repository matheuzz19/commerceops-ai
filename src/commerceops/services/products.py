"""Deterministic product application service."""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from commerceops.domain.invariants import require_positive_amount
from commerceops.domain.models import Product
from commerceops.repositories import ProductRepository


class ProductService:
    def __init__(self, session: Session, repository: ProductRepository | None = None) -> None:
        self.session = session
        self.repository = repository or ProductRepository()

    def create(
        self, tenant_id: UUID, name: str, sku: str, price: Decimal, active: bool = True
    ) -> Product:
        require_positive_amount(price)
        product = Product(
            tenant_id=tenant_id,
            name=name.strip(),
            sku=sku.strip(),
            price=price,
            active=active,
        )
        self.repository.add(self.session, product)
        self.session.flush()
        return product

    def search(
        self, tenant_id: UUID, query: str, active_only: bool = True, limit: int = 10
    ) -> Sequence[Product]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return self.repository.search(self.session, tenant_id, query.strip(), active_only, limit)

    def get(self, tenant_id: UUID, product_id: UUID) -> Product | None:
        return self.repository.get(self.session, tenant_id, product_id)
