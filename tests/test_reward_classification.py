"""Tests for REWARD sub-classification (staking/mining/airdrop/interest)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.models.transaction import Transaction

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


class TestParserClassification:
    def test_bitstamp_staking_reward(self):
        from kryptoskatt.parsers.bitstamp import BitstampParser

        result = BitstampParser().parse(FIXTURES / "bitstamp_sample.csv")
        rewards = [t for t in result.transactions if t.event_type == "REWARD"]
        assert rewards and all(t.reward_type == "staking" for t in rewards)

    def test_okx_staking_yield(self):
        from kryptoskatt.parsers.okx import OkxParser

        result = OkxParser().parse(FIXTURES / "okx_funding_sample.csv")
        rewards = [t for t in result.transactions if t.event_type == "REWARD"]
        assert rewards and rewards[0].reward_type == "staking"

    def test_gateio_airdrop(self):
        from kryptoskatt.parsers.gateio import GateIoParser

        result = GateIoParser().parse(FIXTURES / "gateio_sample.csv")
        rewards = [t for t in result.transactions if t.event_type == "REWARD"]
        assert rewards and rewards[0].reward_type == "airdrop"


class TestT2UsesRewardType:
    def _add_reward(self, db, uid, coin, amount, price, reward_type, platform="test"):
        db.add(Transaction(
            user_id=uid, source_platform=platform,
            timestamp_utc=datetime(2024, 5, 1, tzinfo=UTC),
            event_type="REWARD", base_coin=coin, base_amount=Decimal(str(amount)),
            price_sek=Decimal(str(price)), is_duplicate=False, reward_type=reward_type,
        ))

    def test_income_rows_split_by_reward_type(self, db):
        from kryptoskatt.reports.t2 import T2IncomeReport
        from tests.conftest import make_test_account

        uid = make_test_account(db)
        self._add_reward(db, uid, "ETH", "0.1", "20000", "staking")
        self._add_reward(db, uid, "GEOD", "100", "5", "mining")
        self._add_reward(db, uid, "UNI", "3", "50", None)  # legacy → "reward"
        db.commit()

        report = T2IncomeReport(db, uid).generate(2024)
        categories = {row.category for row in report.income_rows}
        assert "staking" in categories
        assert "mining" in categories
        assert "reward" in categories  # fallback for unclassified


class TestClassifyEndpoint:
    def test_classify_reward_scoped_to_user_and_event(self, db):
        from fastapi.testclient import TestClient

        from kryptoskatt.db import get_db
        from kryptoskatt.services.auth import AuthService
        from kryptoskatt.web import auth as web_auth
        from kryptoskatt.web.app import app

        acc, token = AuthService(db).create_account()
        # A REWARD and a non-REWARD tx
        r = Transaction(
            user_id=acc.id, source_platform="test",
            timestamp_utc=datetime(2024, 5, 1, tzinfo=UTC), event_type="REWARD",
            base_coin="ETH", base_amount=Decimal("0.1"), is_duplicate=False,
        )
        b = Transaction(
            user_id=acc.id, source_platform="test",
            timestamp_utc=datetime(2024, 5, 1, tzinfo=UTC), event_type="BUY",
            base_coin="ETH", base_amount=Decimal("1"), is_duplicate=False,
        )
        db.add_all([r, b])
        db.commit()

        def ov():
            yield db

        app.dependency_overrides[get_db] = ov
        app.dependency_overrides[web_auth._get_db_session] = ov
        client = TestClient(
            app, cookies={"kryptoskatt_session": token},
            follow_redirects=False, headers={"origin": "http://testserver"},
        )
        try:
            resp = client.post(
                "/transactions/classify-reward",
                data={"ids": f"{r.id},{b.id}", "reward_type": "staking"},
            )
            assert resp.status_code == 303
            db.refresh(r)
            db.refresh(b)
            assert r.reward_type == "staking"      # REWARD updated
            assert b.reward_type is None           # non-REWARD untouched
        finally:
            app.dependency_overrides.clear()

    def test_invalid_reward_type_rejected(self, db):
        from fastapi.testclient import TestClient

        from kryptoskatt.db import get_db
        from kryptoskatt.services.auth import AuthService
        from kryptoskatt.web import auth as web_auth
        from kryptoskatt.web.app import app

        acc, token = AuthService(db).create_account()
        db.commit()

        def ov():
            yield db

        app.dependency_overrides[get_db] = ov
        app.dependency_overrides[web_auth._get_db_session] = ov
        client = TestClient(
            app, cookies={"kryptoskatt_session": token},
            follow_redirects=False, headers={"origin": "http://testserver"},
        )
        try:
            resp = client.post(
                "/transactions/classify-reward",
                data={"ids": "1", "reward_type": "bogus"},
            )
            assert resp.status_code == 303
            assert "error" in resp.headers["location"]
        finally:
            app.dependency_overrides.clear()
