"""Tests for TransactionCreate schema validators."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kryptoskatt.schemas import TransactionCreate


def _make_valid(**overrides) -> dict:
    """Return a dict of valid TransactionCreate fields with optional overrides."""
    base = {
        "source_platform": "TEST",
        "timestamp_utc": datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        "event_type": "BUY",
        "base_coin": "ETH",
        "base_amount": Decimal("1.0"),
    }
    base.update(overrides)
    return base


def test_valid_transaction():
    """A fully valid TransactionCreate is accepted without error."""
    tx = TransactionCreate(**_make_valid())

    assert tx.source_platform == "TEST"
    assert tx.event_type == "BUY"
    assert tx.base_coin == "ETH"
    assert tx.base_amount == Decimal("1.0")
    assert tx.timestamp_utc.tzinfo is not None


def test_zero_amount_raises():
    """base_amount of exactly zero must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionCreate(**_make_valid(base_amount=Decimal("0")))

    errors = exc_info.value.errors()
    assert any("base_amount" in str(e) or "amount" in str(e).lower() for e in errors)


def test_naive_timestamp_raises():
    """A timestamp without tzinfo must raise ValidationError."""
    naive_dt = datetime(2024, 6, 15, 12, 0, 0)  # no tzinfo
    assert naive_dt.tzinfo is None

    with pytest.raises(ValidationError) as exc_info:
        TransactionCreate(**_make_valid(timestamp_utc=naive_dt))

    errors = exc_info.value.errors()
    assert any("timestamp" in str(e).lower() or "timezone" in str(e).lower() for e in errors)


def test_unknown_event_type_raises():
    """An event_type not in the enum must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        TransactionCreate(**_make_valid(event_type="MAGIC"))

    errors = exc_info.value.errors()
    assert any("event_type" in str(e) or "Unknown" in str(e) for e in errors)


def test_negative_fee_amount_accepted():
    """Negative fee_amount is currently accepted (no validator blocks it).

    This test documents the current behaviour. If a validator is added later
    to reject negative fees, this test should be updated to expect a
    ValidationError instead.
    """
    # The schema has no negative-fee validator yet — negative fees are legal
    # (Coinbase itself can return negative fees for spread-based converts).
    tx = TransactionCreate(**_make_valid(fee_coin="SEK", fee_amount=Decimal("-1")))
    assert tx.fee_amount == Decimal("-1")


def test_valid_with_all_optional_fields():
    """A TransactionCreate with all optional fields filled in is accepted."""
    tx = TransactionCreate(
        source_platform="COINBASE",
        timestamp_utc=datetime(2024, 3, 20, 8, 30, 0, tzinfo=UTC),
        event_type="SWAP_OUT",
        base_coin="BTC",
        base_amount=Decimal("-0.01"),
        quote_coin="ETH",
        quote_amount=Decimal("0.15"),
        fee_coin="SEK",
        fee_amount=Decimal("25.50"),
        tx_hash="0xdeadbeef",
        from_address="0xABCD",
        to_address="0x1234",
        price_sek=Decimal("450000.00"),
        raw_payload={"original": "row"},
    )

    assert tx.base_coin == "BTC"
    assert tx.quote_coin == "ETH"
    assert tx.fee_coin == "SEK"
    assert tx.tx_hash == "0xdeadbeef"
    assert tx.from_address == "0xABCD"
    assert tx.to_address == "0x1234"
    assert tx.price_sek == Decimal("450000.00")
    assert tx.raw_payload == {"original": "row"}


def test_all_valid_event_types_accepted():
    """Every value in the EventType enum is accepted by the event_type validator."""
    from kryptoskatt.enums import EventType

    for et in EventType:
        tx = TransactionCreate(**_make_valid(event_type=et.value))
        assert tx.event_type == et.value


def test_positive_base_amount_accepted():
    """Positive base_amount passes the nonzero validator."""
    tx = TransactionCreate(**_make_valid(base_amount=Decimal("0.000001")))
    assert tx.base_amount == Decimal("0.000001")


def test_negative_base_amount_accepted():
    """Negative base_amount (e.g. SELL) passes the nonzero validator."""
    tx = TransactionCreate(**_make_valid(event_type="SELL", base_amount=Decimal("-2.5")))
    assert tx.base_amount == Decimal("-2.5")
