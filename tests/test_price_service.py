"""Tests for PriceService - CoinGecko price fetching with caching."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.price_cache import PriceCache
from kryptoskatt.services.price import COIN_ID_MAP, PriceService, resolve_coin_id


@pytest.fixture
def db_session():
    """In-memory SQLite session for testing."""
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    make_test_account(session)
    yield session
    session.close()


@pytest.fixture
def price_service(db_session):
    """PriceService instance with test session."""
    return PriceService(db_session)


def _mock_response(status_code: int = 200, data: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = data or {}
    return m


class TestResolveCoinId:
    """Tests for coin ID resolution."""

    def test_resolve_known_coin_uppercase(self):
        """Test resolving known coin symbol (uppercase)."""
        assert resolve_coin_id("BTC") == "bitcoin"
        assert resolve_coin_id("ETH") == "ethereum"
        assert resolve_coin_id("SOL") == "solana"

    def test_resolve_known_coin_lowercase(self):
        """Test resolving known coin symbol (lowercase)."""
        assert resolve_coin_id("btc") == "bitcoin"
        assert resolve_coin_id("eth") == "ethereum"

    def test_resolve_unknown_coin_returns_none(self):
        """Test that unknown coin returns None."""
        assert resolve_coin_id("UNKNOWN") is None
        assert resolve_coin_id("FAKETOKEN") is None

    def test_resolve_depin_coins(self):
        """DePIN tokens are mapped to their CoinGecko IDs."""
        assert resolve_coin_id("GEOD") == "geodnet"
        assert resolve_coin_id("ONO") == "onocoy"

    def test_coin_id_map_contains_expected_coins(self):
        """Verify COIN_ID_MAP has expected coins."""
        expected = [
            "BTC",
            "ETH",
            "SOL",
            "XRP",
            "BNB",
            "VET",
            "KDA",
            "TRX",
            "POL",
            "MATIC",
            "HNT",
            "PEAQ",
            "ALEO",
        ]
        for coin in expected:
            assert coin in COIN_ID_MAP, f"Missing {coin} in COIN_ID_MAP"


class TestPriceServiceGetPriceSek:
    """Tests for PriceService.get_price_sek method."""

    def test_cache_hit_returns_cached_price(self, price_service, db_session):
        """Test that cache hit returns cached price without API call."""
        cached = PriceCache(
            coin_id="ethereum",
            date=date(2024, 6, 15),
            price_sek=Decimal("25000.00"),
            source="COINGECKO",
        )
        db_session.add(cached)
        db_session.commit()

        result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert result == Decimal("25000.00")

    def test_cache_miss_fetches_from_api(self, price_service):
        """Test that cache miss triggers API call."""
        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.00}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp) as mock_get:
            result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert result == Decimal("25000.00")
        mock_get.assert_called_once()

    def test_unknown_coin_returns_none(self, price_service):
        """Test that unknown coin returns None."""
        result = price_service.get_price_sek("geod", date(2024, 6, 15))

        assert result is None

    def test_api_404_returns_none(self, price_service):
        """Test that 404 from API returns None."""
        resp = _mock_response(404)
        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            result = price_service.get_price_sek("nonexistent-coin", date(2024, 6, 15))

        assert result is None

    def test_api_rate_limit_429_returns_none(self, price_service):
        """Test that 429 rate limit returns None."""
        resp = _mock_response(429)
        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert result is None

    def test_api_error_returns_none(self, price_service):
        """Test that API error returns None."""
        with patch(
            "kryptoskatt.services.price.get_with_retry",
            side_effect=Exception("Network error"),
        ):
            result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert result is None

    def test_price_saved_to_cache(self, price_service, db_session):
        """Test that fetched price is saved to cache."""
        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.00}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            price_service.get_price_sek("ethereum", date(2024, 6, 15))

        cached = (
            db_session.query(PriceCache)
            .filter_by(coin_id="ethereum", date=date(2024, 6, 15))
            .first()
        )

        assert cached is not None
        assert cached.price_sek == Decimal("25000.00")
        assert cached.source == "COINGECKO"

    def test_second_call_uses_cache(self, price_service, db_session):
        """Test that second call for same coin/date uses cache."""
        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.00}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp) as mock_get:
            result1 = price_service.get_price_sek("ethereum", date(2024, 6, 15))
            assert result1 == Decimal("25000.00")
            assert mock_get.call_count == 1

            result2 = price_service.get_price_sek("ethereum", date(2024, 6, 15))
            assert result2 == Decimal("25000.00")
            assert mock_get.call_count == 1

    def test_coingecko_date_format(self, price_service):
        """Test that CoinGecko API uses DD-MM-YYYY format."""
        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.00}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp) as mock_get:
            price_service.get_price_sek("ethereum", date(2024, 6, 15))

        call_kwargs = mock_get.call_args.kwargs
        called_params = call_kwargs.get("params", {})
        assert called_params.get("date") == "15-06-2024", (
            f"Expected '15-06-2024' in params, got: {called_params}"
        )


class TestPriceServiceBatch:
    """Tests for PriceService.get_prices_batch method."""

    def test_batch_all_cached(self, price_service, db_session):
        """Test batch returns all cached prices without API calls."""
        cache_entries = [
            PriceCache(
                coin_id="bitcoin",
                date=date(2024, 6, 15),
                price_sek=Decimal("500000.00"),
                source="COINGECKO",
            ),
            PriceCache(
                coin_id="ethereum",
                date=date(2024, 6, 15),
                price_sek=Decimal("25000.00"),
                source="COINGECKO",
            ),
        ]
        for entry in cache_entries:
            db_session.add(entry)
        db_session.commit()

        requests = [
            ("bitcoin", date(2024, 6, 15)),
            ("ethereum", date(2024, 6, 15)),
        ]

        result = price_service.get_prices_batch(requests)

        assert result[("bitcoin", date(2024, 6, 15))] == Decimal("500000.00")
        assert result[("ethereum", date(2024, 6, 15))] == Decimal("25000.00")

    def test_batch_mixed_cache_and_api(self, price_service, db_session):
        """Test batch with some cached, some needing API."""
        cached = PriceCache(
            coin_id="bitcoin",
            date=date(2024, 6, 15),
            price_sek=Decimal("500000.00"),
            source="COINGECKO",
        )
        db_session.add(cached)
        db_session.commit()

        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.00}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            requests = [
                ("bitcoin", date(2024, 6, 15)),
                ("ethereum", date(2024, 6, 15)),
            ]
            result = price_service.get_prices_batch(requests)

        assert result[("bitcoin", date(2024, 6, 15))] == Decimal("500000.00")
        assert result[("ethereum", date(2024, 6, 15))] == Decimal("25000.00")

    def test_batch_unknown_coin_returns_none(self, price_service):
        """Test batch returns None for unknown coin."""
        requests = [
            ("UNKNOWN", date(2024, 6, 15)),
        ]

        result = price_service.get_prices_batch(requests)
        assert result[("UNKNOWN", date(2024, 6, 15))] is None


class TestPriceServiceWithApiKey:
    """Tests for PriceService with API key."""

    @patch("kryptoskatt.services.price.settings")
    def test_api_key_in_header(self, mock_settings, price_service):
        """Test that API key is included in request header."""
        mock_settings.coingecko_api_key = "test-api-key-123"

        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.00}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp) as mock_get:
            price_service.get_price_sek("ethereum", date(2024, 6, 15))

        call_kwargs = mock_get.call_args.kwargs
        assert "headers" in call_kwargs
        assert call_kwargs["headers"]["x-cg-demo-api-key"] == "test-api-key-123"

    @patch("kryptoskatt.services.price.settings")
    def test_no_api_key_no_header(self, mock_settings, price_service):
        """Test that no API key means no custom header."""
        mock_settings.coingecko_api_key = ""

        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.00}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp) as mock_get:
            price_service.get_price_sek("ethereum", date(2024, 6, 15))

        call_kwargs = mock_get.call_args.kwargs
        if "headers" in call_kwargs:
            assert "x-cg-demo-api-key" not in call_kwargs["headers"]


class TestDecimalConversion:
    """Tests for Decimal conversion from float."""

    def test_float_converted_to_decimal(self, price_service):
        """Test that float prices are converted to Decimal."""
        resp = _mock_response(200, {"market_data": {"current_price": {"sek": 25000.50}}})

        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert isinstance(result, Decimal)
        assert result == Decimal("25000.50")


class TestExchangeOhlcFallback:
    """Tests for the free Binance/Kraken OHLC price fallbacks."""

    def test_binance_price_converts_usd_to_sek(self, price_service):
        # Daily kline: close = 50000 USDT
        candle = [[1718409600000, "49000", "51000", "48000", "50000", "10.0"]]
        resp = _mock_response(200, candle)
        with (
            patch("kryptoskatt.services.price.get_with_retry", return_value=resp) as mock_get,
            patch(
                "kryptoskatt.services.price.get_usd_sek_rate",
                return_value=Decimal("10.5"),
            ),
        ):
            price = price_service.fetch_binance_price("BTC", date(2024, 6, 15))

        assert price == Decimal("525000.0")
        # Uses the USDT pair
        assert mock_get.call_args.kwargs["params"]["symbol"] == "BTCUSDT"

    def test_binance_caches_result(self, price_service, db_session):
        candle = [[1718409600000, "1", "1", "1", "2000", "1"]]
        resp = _mock_response(200, candle)
        with (
            patch("kryptoskatt.services.price.get_with_retry", return_value=resp),
            patch("kryptoskatt.services.price.get_usd_sek_rate", return_value=Decimal("10")),
        ):
            price_service.fetch_binance_price("ETH", date(2024, 6, 15))

        cached = (
            db_session.query(PriceCache)
            .filter(PriceCache.coin_id == "ETH", PriceCache.date == date(2024, 6, 15))
            .first()
        )
        assert cached is not None
        assert cached.source == "BINANCE"
        assert Decimal(str(cached.price_sek)) == Decimal("20000")

    def test_binance_empty_klines_returns_none(self, price_service):
        resp = _mock_response(200, [])
        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            assert price_service.fetch_binance_price("BTC", date(2020, 1, 1)) is None

    def test_binance_skips_stablecoins(self, price_service):
        with patch("kryptoskatt.services.price.get_with_retry") as mock_get:
            assert price_service.fetch_binance_price("USDT", date(2024, 6, 15)) is None
        mock_get.assert_not_called()

    def test_binance_no_fx_rate_returns_none(self, price_service):
        candle = [[1718409600000, "1", "1", "1", "50000", "1"]]
        resp = _mock_response(200, candle)
        with (
            patch("kryptoskatt.services.price.get_with_retry", return_value=resp),
            patch("kryptoskatt.services.price.get_usd_sek_rate", return_value=None),
        ):
            assert price_service.fetch_binance_price("BTC", date(2024, 6, 15)) is None

    def test_kraken_price_matches_day_and_converts(self, price_service):
        target = date(2024, 6, 15)
        ts = int(__import__("datetime").datetime(2024, 6, 15, tzinfo=__import__("datetime").UTC).timestamp())
        payload = {
            "error": [],
            "result": {
                "XXBTZUSD": [
                    [ts - 86400, "1", "1", "1", "40000", "1", "1", 1],
                    [ts, "1", "1", "1", "50000", "1", "1", 1],
                ],
                "last": ts,
            },
        }
        resp = _mock_response(200, payload)
        with (
            patch("kryptoskatt.services.price.get_with_retry", return_value=resp) as mock_get,
            patch("kryptoskatt.services.price.get_usd_sek_rate", return_value=Decimal("10")),
        ):
            price = price_service.fetch_kraken_price("BTC", target)

        assert price == Decimal("500000")
        # BTC maps to Kraken's XBT asset code
        assert mock_get.call_args.kwargs["params"]["pair"] == "XBTUSD"

    def test_kraken_error_returns_none(self, price_service):
        resp = _mock_response(200, {"error": ["EQuery:Unknown asset pair"], "result": {}})
        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            assert price_service.fetch_kraken_price("FAKE", date(2024, 6, 15)) is None

    def test_kraken_day_not_in_window_returns_none(self, price_service):
        ts = int(__import__("datetime").datetime(2024, 1, 1, tzinfo=__import__("datetime").UTC).timestamp())
        payload = {"error": [], "result": {"XETHZUSD": [[ts, "1", "1", "1", "3000", "1", "1", 1]], "last": ts}}
        resp = _mock_response(200, payload)
        with patch("kryptoskatt.services.price.get_with_retry", return_value=resp):
            # Ask for a different day than the one candle present
            assert price_service.fetch_kraken_price("ETH", date(2024, 6, 15)) is None
