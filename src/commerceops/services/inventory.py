"""Inventory ledger service."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from commerceops.domain.enums import InventoryMovementType
from commerceops.domain.invariants import DomainError, require_positive_quantity
from commerceops.domain.models import InventoryMovement
from commerceops.repositories import InventoryRepository, ProductRepository


class InventoryService:
    def __init__(
        self,
        session: Session,
        inventory_repository: InventoryRepository | None = None,
        product_repository: ProductRepository | None = None,
    ) -> None:
        self.session = session
        self.inventory_repository = inventory_repository or InventoryRepository()
        self.product_repository = product_repository or ProductRepository()

    def get_level(self, tenant_id: UUID, product_id: UUID) -> int:
        self._require_product(tenant_id, product_id)
        return self.inventory_repository.stock_level(self.session, tenant_id, product_id)

    def list_movements(
        self, tenant_id: UUID, product_id: UUID | None = None, limit: int = 20
    ) -> Sequence[InventoryMovement]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if product_id is not None:
            self._require_product(tenant_id, product_id)
        return self.inventory_repository.list(self.session, tenant_id, product_id, limit)

    def create_movement(
        self,
        tenant_id: UUID,
        product_id: UUID,
        movement_type: InventoryMovementType,
        quantity: int,
        reason: str,
    ) -> InventoryMovement:
        self._require_product(tenant_id, product_id)
        if movement_type in {InventoryMovementType.IN, InventoryMovementType.OUT}:
            require_positive_quantity(quantity)
        elif quantity == 0:
            raise DomainError("INVALID_QUANTITY", "Adjustment quantity cannot be zero.")

        if movement_type == InventoryMovementType.OUT:
            available = self.inventory_repository.stock_level(self.session, tenant_id, product_id)
            if available - quantity < 0:
                raise DomainError(
                    "INSUFFICIENT_STOCK",
                    "Inventory movement would make stock negative.",
                )

        movement = InventoryMovement(
            tenant_id=tenant_id,
            product_id=product_id,
            movement_type=movement_type,
            quantity=quantity,
            reason=reason.strip(),
        )
        self.inventory_repository.add(self.session, movement)
        self.session.flush()
        return movement

    def _require_product(self, tenant_id: UUID, product_id: UUID) -> None:
        if self.product_repository.get(self.session, tenant_id, product_id) is None:
            raise DomainError("PRODUCT_NOT_FOUND", "Product was not found.")
