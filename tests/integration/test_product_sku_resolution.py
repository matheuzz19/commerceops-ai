from decimal import Decimal

from sqlalchemy.orm import Session

from commerceops.domain.models import Tenant
from commerceops.services import ProductService


def test_sku_lookup_preserves_tenant_and_active_filters(
    session: Session,
    tenants: tuple[Tenant, Tenant],
) -> None:
    owner, foreign = tenants
    service = ProductService(session)
    expected = service.create(owner.id, "Keyboard", "KEY-01", Decimal("10"))
    service.create(foreign.id, "Foreign Keyboard", "KEY-01", Decimal("20"))
    inactive = service.create(owner.id, "Old Keyboard", "KEY-02", Decimal("5"))
    inactive.active = False
    session.commit()
    assert [row.id for row in service.search(owner.id, "key-01")] == [expected.id]
    assert not service.search(owner.id, "KEY-02")
