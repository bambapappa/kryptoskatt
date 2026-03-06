"""Tests for the GavEngine (Genomsnittsmetoden / Average Cost Method)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from decimal import Decimal

from kryptoskatt.models.base import Base
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.gav_ledger import GavLedger
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.engine.gav import GavEngine, CalculationResult
from datetime import datetime, timezone


@pytest.fixture
def db_session():
    """Create an in-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _create_tx(
    session: Session,
    timestamp_utc: datetime,
    event_type: str,
    base_coin: str,
    base_amount: Decimal,
    quote_coin: str | None = None,
    quote_amount: Decimal | None = None,
    fee_coin: str | None = None,
    fee_amount: Decimal | None = None,
    price_sek: Decimal | None = None,
    tx_hash: str | None = None,
    wallet_id: int | None = None,
) -> Transaction:
    """Helper to create a Transaction in the test database."""
    tx = Transaction(
        source_platform="TEST",
        timestamp_utc=timestamp_utc,
        event_type=event_type,
        base_coin=base_coin,
        base_amount=base_amount,
        quote_coin=quote_coin,
        quote_amount=quote_amount,
        fee_coin=fee_coin,
        fee_amount=fee_amount,
        price_sek=price_sek,
        tx_hash=tx_hash,
        import_batch_id=None,
        wallet_id=wallet_id,
    )
    session.add(tx)
    session.commit()
    return tx


def _create_transfer_link(
    session: Session,
    tx_out_id: int,
    tx_in_id: int,
) -> TransferLink:
    """Helper to create a TransferLink in the test database."""
    link = TransferLink(
        tx_out_id=tx_out_id,
        tx_in_id=tx_in_id,
        match_method="MANUAL",
        confidence=Decimal("1.0"),
    )
    session.add(link)
    session.commit()
    return link


class TestSimpleBuyThenSell:
    """Test basic buy then sell scenario."""

    def test_simple_buy_then_sell(self, db_session: Session):
        """Buy 1 ETH @ 20000 SEK, Sell 0.5 ETH @ 25000 SEK."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            quote_coin="SEK",
            quote_amount=Decimal("20000"),
            price_sek=Decimal("20000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-0.5"),
            quote_coin="SEK",
            quote_amount=Decimal("12500"),
            price_sek=Decimal("25000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.proceeds_sek == Decimal("12500")
        assert disposal.cost_basis_sek == Decimal("10000")
        assert disposal.gain_loss_sek == Decimal("2500")
        assert disposal.gav_at_disposal == Decimal("20000")
        assert isinstance(disposal.proceeds_sek, Decimal)
        assert isinstance(disposal.cost_basis_sek, Decimal)
        assert isinstance(disposal.gain_loss_sek, Decimal)


class TestGavAveraging:
    """Test GAV averaging logic."""

    def test_gav_averaging(self, db_session: Session):
        """Buy 1 ETH @ 20000, Buy 1 ETH @ 30000, GAV = 25000. Sell 1."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("20000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 2, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("30000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-1"),
            price_sek=Decimal("35000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.gav_at_disposal == Decimal("25000")
        assert disposal.cost_basis_sek == Decimal("25000")
        assert disposal.proceeds_sek == Decimal("35000")
        assert disposal.gain_loss_sek == Decimal("10000")


class TestSwapCreatesDisposalAndAcquisition:
    """Test SWAP_OUT creates disposal and SWAP_IN creates acquisition."""

    def test_swap_creates_disposal_and_acquisition(self, db_session: Session):
        """SWAP_OUT 0.01 BTC (price 400000) + SWAP_IN 0.15 ETH."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.02"),
            price_sek=Decimal("400000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SWAP_OUT",
            base_coin="BTC",
            base_amount=Decimal("-0.01"),
            price_sek=Decimal("400000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 1, tzinfo=timezone.utc),
            event_type="SWAP_IN",
            base_coin="ETH",
            base_amount=Decimal("0.15"),
            price_sek=Decimal("26667"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 1
        btc_disposal = result.disposals[0]
        assert btc_disposal.coin == "BTC"
        assert btc_disposal.sell_amount == Decimal("0.01")
        assert btc_disposal.cost_basis_sek == Decimal("4000")
        assert btc_disposal.proceeds_sek == Decimal("4000")
        assert btc_disposal.gain_loss_sek == Decimal("0")

        gav_entries = db_session.query(GavLedger).order_by(GavLedger.timestamp).all()
        assert len(gav_entries) == 3


class TestRewardAsAcquisition:
    """Test REWARD events are treated as acquisitions."""

    def test_reward_as_acquisition(self, db_session: Session):
        """Receive 100 GEOD @ 5 SEK."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="REWARD",
            base_coin="GEOD",
            base_amount=Decimal("100"),
            price_sek=Decimal("5"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 0
        gav_entries = db_session.query(GavLedger).filter(GavLedger.coin == "GEOD").all()
        assert len(gav_entries) == 1
        assert gav_entries[0].total_cost_sek == Decimal("500")
        assert gav_entries[0].total_amount == Decimal("100")
        assert gav_entries[0].gav_per_unit_sek == Decimal("5")


class TestTransferNoTaxImpact:
    """Test transfers with TransferLink are non-taxable."""

    def test_transfer_no_tax_impact(self, db_session: Session):
        """Own-wallet transfer with TransferLink."""
        buy_tx = _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1"),
            price_sek=Decimal("400000"),
        )
        transfer_out_tx = _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="TRANSFER_OUT",
            base_coin="BTC",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("400000"),
        )
        transfer_in_tx = _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 5, 0, tzinfo=timezone.utc),
            event_type="TRANSFER_IN",
            base_coin="BTC",
            base_amount=Decimal("0.5"),
            price_sek=Decimal("400000"),
        )
        _create_transfer_link(
            db_session,
            tx_out_id=transfer_out_tx.id,
            tx_in_id=transfer_in_tx.id,
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 0
        gav_entries = (
            db_session.query(GavLedger)
            .filter(GavLedger.coin == "BTC")
            .order_by(GavLedger.timestamp)
            .all()
        )
        assert len(gav_entries) == 3
        final_entry = gav_entries[-1]
        assert final_entry.total_amount == Decimal("1")
        assert final_entry.total_cost_sek == Decimal("400000")


class TestUnknownPriceWarning:
    """Test handling of unknown prices."""

    def test_unknown_price_warning(self, db_session: Session):
        """Sell coin with no price_sek."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1"),
            price_sek=Decimal("400000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="BTC",
            base_amount=Decimal("-0.5"),
            price_sek=None,
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.proceeds_sek == Decimal("0")
        assert disposal.cost_basis_sek == Decimal("200000")
        assert disposal.gain_loss_sek == Decimal("-200000")
        assert len(result.warnings) > 0
        warning_found = any("Unknown price" in w for w in result.warnings)
        assert warning_found


class TestFullSellAndRebuy:
    """Test selling all holdings resets GAV."""

    def test_full_sell_and_rebuy(self, db_session: Session):
        """Sell all holdings then rebuy."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("20000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-1"),
            price_sek=Decimal("30000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("25000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.gain_loss_sek == Decimal("10000")

        gav_entries = (
            db_session.query(GavLedger)
            .filter(GavLedger.coin == "ETH")
            .order_by(GavLedger.timestamp)
            .all()
        )
        final_entry = gav_entries[-1]
        assert final_entry.total_amount == Decimal("1")
        assert final_entry.total_cost_sek == Decimal("25000")
        assert final_entry.gav_per_unit_sek == Decimal("25000")


class TestMultiYearCalculation:
    """Test multi-year calculation."""

    def test_multi_year_calculation(self, db_session: Session):
        """2023 buy + 2024 buy + 2024 sell."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("15000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("25000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("30000"),
        )

        engine = GavEngine(db_session)
        result_2024 = engine.calculate(year=2024)

        assert len(result_2024.disposals) == 1
        disposal = result_2024.disposals[0]
        assert disposal.gav_at_disposal == Decimal("20000")
        assert disposal.cost_basis_sek == Decimal("10000")
        assert disposal.proceeds_sek == Decimal("15000")
        assert disposal.gain_loss_sek == Decimal("5000")


class TestAllArithmeticIsDecimal:
    """Verify all arithmetic uses Decimal."""

    def test_all_arithmetic_is_decimal(self, db_session: Session):
        """Verify Disposal fields are Decimal instances."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1"),
            price_sek=Decimal("400000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="BTC",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("500000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        disposal = result.disposals[0]
        assert isinstance(disposal.sell_amount, Decimal)
        assert isinstance(disposal.proceeds_sek, Decimal)
        assert isinstance(disposal.cost_basis_sek, Decimal)
        assert isinstance(disposal.gain_loss_sek, Decimal)
        assert isinstance(disposal.gav_at_disposal, Decimal)
        assert isinstance(disposal.tax_year, int)


class TestGavLedgerCreatedPerEvent:
    """Verify GavLedger entries are created for every processed event."""

    def test_gav_ledger_created_per_event(self, db_session: Session):
        """Every processed event creates a GavLedger entry."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1"),
            price_sek=Decimal("400000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 2, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("10"),
            price_sek=Decimal("2000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 3, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="BTC",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("450000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        all_entries = db_session.query(GavLedger).all()
        assert len(all_entries) == 3

        btc_entries = db_session.query(GavLedger).filter(GavLedger.coin == "BTC").all()
        assert len(btc_entries) == 2
        eth_entries = db_session.query(GavLedger).filter(GavLedger.coin == "ETH").all()
        assert len(eth_entries) == 1


class TestSellMoreThanOwnedWarning:
    """Test graceful handling when selling more than owned."""

    def test_sell_more_than_owned_warning(self, db_session: Session):
        """Try to sell more than held."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.5"),
            price_sek=Decimal("400000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="BTC",
            base_amount=Decimal("-1"),
            price_sek=Decimal("500000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.warnings) > 0
        warning_found = any("Selling" in w and "but only" in w for w in result.warnings)
        assert warning_found

        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.sell_amount == Decimal("0.5")
        assert disposal.cost_basis_sek == Decimal("200000")
        assert disposal.proceeds_sek == Decimal("250000")
        assert disposal.gain_loss_sek == Decimal("50000")

        gav_entries = (
            db_session.query(GavLedger)
            .filter(GavLedger.coin == "BTC")
            .order_by(GavLedger.timestamp)
            .all()
        )
        final_entry = gav_entries[-1]
        assert final_entry.total_amount == Decimal("0")


class TestAcquisitionsBeforeDisposalsSameTimestamp:
    """Test acquisitions processed before disposals at same timestamp."""

    def test_acquisitions_before_disposals_same_timestamp(self, db_session: Session):
        """At same timestamp, BUY processed before SELL."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("20000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("25000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.gav_at_disposal == Decimal("20000")
        assert disposal.cost_basis_sek == Decimal("10000")


class TestFeeHandling:
    """Test fee handling in acquisitions."""

    def test_fee_handling_in_acquisition(self, db_session: Session):
        """Fee in same coin adds to cost basis."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("20000"),
            fee_coin="ETH",
            fee_amount=Decimal("0.01"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        gav_entries = db_session.query(GavLedger).filter(GavLedger.coin == "ETH").all()
        entry = gav_entries[0]
        assert entry.total_cost_sek == Decimal("20200")
        assert entry.total_amount == Decimal("1")
        assert entry.gav_per_unit_sek == Decimal("20200")


class TestYearFiltering:
    """Test year filtering in calculation."""

    def test_calculate_without_year_returns_all_disposals(self, db_session: Session):
        """calculate() without year returns all disposals."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2023, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("15000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2023, 12, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("20000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("0.5"),
            price_sek=Decimal("25000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 12, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("30000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate()

        assert len(result.disposals) == 2

    def test_calculate_with_year_filter(self, db_session: Session):
        """calculate(year=2024) returns only 2024 disposals."""
        _create_tx(
            db_session,
            timestamp_utc=datetime(2023, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("15000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2023, 12, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("20000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("0.5"),
            price_sek=Decimal("25000"),
        )
        _create_tx(
            db_session,
            timestamp_utc=datetime(2024, 12, 1, 10, 0, 0, tzinfo=timezone.utc),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-0.5"),
            price_sek=Decimal("30000"),
        )

        engine = GavEngine(db_session)
        result = engine.calculate(year=2024)

        assert len(result.disposals) == 1
        assert result.disposals[0].tax_year == 2024
