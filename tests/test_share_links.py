"""Tests for read-only accountant share links."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.share_link import ShareLink
from kryptoskatt.services import share_links as sl


@pytest.fixture
def session():
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    make_test_account(sess)
    yield sess
    sess.close()


def test_create_returns_raw_token_and_stores_only_hash(session):
    raw = sl.create_share_link(session, 1, days=30, label="Revisor")
    assert raw and len(raw) > 20
    link = session.query(ShareLink).one()
    assert link.token_hash != raw  # only the hash is stored
    assert link.label == "Revisor"


def test_resolve_valid_token(session):
    raw = sl.create_share_link(session, 1, days=30)
    link = sl.resolve_share_link(session, raw)
    assert link is not None
    assert link.account_id == 1


def test_resolve_wrong_token_returns_none(session):
    sl.create_share_link(session, 1, days=30)
    assert sl.resolve_share_link(session, "not-a-real-token") is None


def test_resolve_expired_returns_none(session):
    raw = sl.create_share_link(session, 1, days=30)
    link = session.query(ShareLink).one()
    link.expires_at = datetime.now(UTC) - timedelta(days=1)
    session.commit()
    assert sl.resolve_share_link(session, raw) is None


def test_revoked_link_does_not_resolve(session):
    raw = sl.create_share_link(session, 1, days=30)
    link = session.query(ShareLink).one()
    assert sl.revoke_share_link(session, 1, link.id) is True
    assert sl.resolve_share_link(session, raw) is None
    assert sl.list_share_links(session, 1) == []


def test_revoke_other_account_denied(session):
    raw = sl.create_share_link(session, 1, days=30)
    link = session.query(ShareLink).one()
    assert sl.revoke_share_link(session, 999, link.id) is False
    assert sl.resolve_share_link(session, raw) is not None


def test_days_are_clamped(session):
    sl.create_share_link(session, 1, days=100000, label="x")
    link = session.query(ShareLink).order_by(ShareLink.id.desc()).first()
    expires = link.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    assert expires <= datetime.now(UTC) + timedelta(days=sl.MAX_DAYS + 1)
