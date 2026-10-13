import os
from collections.abc import Generator
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from commerceops.domain.models import Base, Tenant


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """A fresh PostgreSQL schema for deterministic backend tests."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("TEST_DATABASE_URL must point to the isolated PostgreSQL test database.")
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql") or url.database != "commerceops_test":
        pytest.fail("TEST_DATABASE_URL must use the PostgreSQL database named commerceops_test.")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        db_session.add_all([Tenant(name="Tenant One"), Tenant(name="Tenant Two")])
        db_session.commit()
        yield db_session
        db_session.rollback()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def tenants(session: Session) -> tuple[Tenant, Tenant]:
    return tuple(session.query(Tenant).order_by(Tenant.name).all())  # type: ignore[return-value]


@pytest.fixture
def redis_context() -> Generator[tuple[Redis, str], None, None]:
    url = os.environ.get("TEST_REDIS_URL")
    if url is None or urlparse(url).path != "/15":
        pytest.fail("TEST_REDIS_URL must point to isolated Redis database 15.")
    client = Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
    client.ping()
    prefix = "commerceops:test:" + uuid4().hex
    try:
        yield client, prefix
    finally:
        keys = list(client.scan_iter(match=prefix + ":*"))
        if keys:
            client.delete(*keys)
        client.close()
