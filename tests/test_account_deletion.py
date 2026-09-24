"""Manual-price isolation and complete account erasure."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models import Base
from kryptoskatt.models.account import Account
from kryptoskatt.models.manual_price import ManualPrice
from kryptoskatt.services.account_deletion import OWNED_TABLES, delete_account_data
from kryptoskatt.services.auth import AuthService
from kryptoskatt.services.price import PriceService


@pytest.fixture
def session():
    eng = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


def test_manual_prices_are_private(session):
    a1, _ = AuthService(session).create_account()
    a2, _ = AuthService(session).create_account()
    svc = PriceService(session)
    svc.save_manual_price("GEOD", date(2025, 1, 1), 1, a1.id)
    assert svc.get_manual_price_sek("GEOD", date(2025, 1, 1), a1.id) == 1
    assert svc.get_manual_price_sek("GEOD", date(2025, 1, 1), a2.id) is None


def test_every_owned_table_is_erased(session):
    """Fails when a new model with an owner column is not in OWNED_TABLES."""
    covered = {m.__tablename__ for m, _ in OWNED_TABLES} | {"accounts", "transfer_links"}
    for table in Base.metadata.sorted_tables:
        cols = {c.name for c in table.columns}
        if cols & {"user_id", "account_id"} and table.name not in covered:
            pytest.fail(f"{table.name} holds per-account data but is not erased")


def test_delete_account_removes_everything(session):
    a1, _ = AuthService(session).create_account()
    a2, _ = AuthService(session).create_account()
    PriceService(session).save_manual_price("X", date(2025, 1, 1), 1, a1.id)
    PriceService(session).save_manual_price("X", date(2025, 1, 1), 2, a2.id)
    id1, id2 = a1.id, a2.id
    delete_account_data(session, id1)
    session.expunge_all()
    assert session.get(Account, id1) is None
    assert session.get(Account, id2) is not None
    assert session.query(ManualPrice).count() == 1


def test_export_serialises_all_tables(session):
    import json
    from datetime import UTC, datetime

    from kryptoskatt.models.disposal import Disposal
    from kryptoskatt.services.account_deletion import export_account_data

    a1, _ = AuthService(session).create_account()
    session.add(Disposal(user_id=a1.id, tax_year=2024, coin="BTC",
                         sell_timestamp=datetime(2024, 1, 1, tzinfo=UTC), sell_amount=1,
                         proceeds_sek=2, cost_basis_sek=1, gain_loss_sek=1, gav_at_disposal=1))
    session.commit()
    data = export_account_data(session, a1)
    json.dumps(data)
    assert data["disposals"][0]["coin"] == "BTC"
    assert "user_sessions" not in data


def test_purge_inactive_accounts(session):
    from datetime import UTC, datetime, timedelta

    from kryptoskatt.services.account_deletion import purge_inactive_accounts

    old, _ = AuthService(session).create_account()
    new, _ = AuthService(session).create_account()
    old.last_active_at = datetime.now(UTC) - timedelta(days=800)
    session.commit()
    old_id, new_id = old.id, new.id
    assert purge_inactive_accounts(session, 24) == 1
    session.expunge_all()
    assert session.get(Account, old_id) is None
    assert session.get(Account, new_id) is not None
    assert purge_inactive_accounts(session, 0) == 0
