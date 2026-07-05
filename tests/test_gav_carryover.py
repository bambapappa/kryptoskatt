"""Tests for the year-to-year GAV carryover report."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.engine.gav import GavEngine
from kryptoskatt.enums import EventType
from kryptoskatt.models.base import Base
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.reports.gav_carryover import GavCarryoverReport


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


def _tx(session, ts, event, coin, amount, price):
    session.add(
        Transaction(
            user_id=1,
            source_platform="TEST",
            timestamp_utc=ts,
            event_type=event.value,
            base_coin=coin,
            base_amount=Decimal(amount),
            price_sek=Decimal(price) if price is not None else None,
        )
    )


def test_carryover_opening_and_closing(session):
    # 2023: buy 2 BTC @ 100000 → closing 2 BTC, cost 200000
    _tx(session, datetime(2023, 3, 1, tzinfo=UTC), EventType.BUY, "BTC", "2", "100000")
    # 2024: buy 1 more @ 200000, then sell 1 @ 300000
    _tx(session, datetime(2024, 2, 1, tzinfo=UTC), EventType.BUY, "BTC", "1", "200000")
    _tx(session, datetime(2024, 6, 1, tzinfo=UTC), EventType.SELL, "BTC", "1", "300000")
    session.commit()

    GavEngine(session, user_id=1).calculate()  # full history ledger

    report = GavCarryoverReport(session, user_id=1).generate(2024)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.coin == "BTC"

    # Opening (end of 2023): 2 BTC, cost 200000, GAV 100000
    assert row.opening_units == Decimal("2.00000000")
    assert row.opening_cost_sek == Decimal("200000.00")
    assert row.opening_gav_sek == Decimal("100000.00")

    # After 2024 buy: 3 BTC / 400000 cost → GAV 133333.33. Sell 1 removes GAV cost.
    # Closing: 2 BTC, cost 400000 - 133333.33... = 266666.67
    assert row.closing_units == Decimal("2.00000000")
    assert row.closing_cost_sek == Decimal("266666.67")

    # Deltas: units unchanged (net 0), cost up by ~66666.67
    assert row.units_delta == Decimal("0.00000000")
    assert row.cost_delta_sek == Decimal("66666.67")


def test_first_year_has_zero_opening(session):
    _tx(session, datetime(2024, 3, 1, tzinfo=UTC), EventType.BUY, "ETH", "10", "20000")
    session.commit()
    GavEngine(session, user_id=1).calculate()

    report = GavCarryoverReport(session, user_id=1).generate(2024)
    row = next(r for r in report.rows if r.coin == "ETH")
    assert row.opening_units == Decimal("0.00000000")
    assert row.opening_cost_sek == Decimal("0.00")
    assert row.closing_units == Decimal("10.00000000")
    assert row.closing_cost_sek == Decimal("200000.00")


def test_fully_sold_coin_shows_closing_zero(session):
    _tx(session, datetime(2023, 3, 1, tzinfo=UTC), EventType.BUY, "SOL", "5", "1000")
    _tx(session, datetime(2024, 4, 1, tzinfo=UTC), EventType.SELL, "SOL", "5", "1500")
    session.commit()
    GavEngine(session, user_id=1).calculate()

    report = GavCarryoverReport(session, user_id=1).generate(2024)
    row = next(r for r in report.rows if r.coin == "SOL")
    assert row.opening_units == Decimal("5.00000000")
    assert row.closing_units == Decimal("0.00000000")
    assert row.closing_cost_sek == Decimal("0.00")
    assert report.closing_total_cost_sek == Decimal("0.00")
