from sqlalchemy import func, select
from sqlalchemy.orm import Session

from commerceops.db.seed import seed_database
from commerceops.domain.models import Customer, Tenant


def test_synthetic_seed_is_multi_tenant_and_idempotent(session: Session) -> None:
    session.query(Customer).delete()
    session.query(Tenant).delete()
    session.commit()

    seed_database(session)
    seed_database(session)
    session.commit()

    assert session.scalar(select(func.count(Tenant.id))) == 2
    assert session.scalar(select(func.count(Customer.id))) == 2
