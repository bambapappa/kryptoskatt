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


@pytest.fixture
def mock_httpx():
    """Mock httpx client."""
    with patch("kryptoskatt.services.price.httpx.Client") as mock_client_class:
        # Create mock for context manager
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_client


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
        # Pre-populate cache
        cached = PriceCache(
            coin_id="ethereum",
            date=date(2024, 6, 15),
            price_sek=Decimal("25000.00"),
            source="COINGECKO",
        )
        db_session.add(cached)
        db_session.commit()

        # Call get_price_sek - should return cached value
        result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert result == Decimal("25000.00")

    def test_cache_miss_fetches_from_api(self, price_service, mock_httpx):
        """Test that cache miss triggers API call."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "market_data": {
                "current_price": {
                    "sek": 25000.00,
                }
            }
        }
        mock_httpx.get.return_value = mock_response

        result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert result == Decimal("25000.00")
        mock_httpx.get.assert_called_once()

    def test_unknown_coin_returns_none(self, price_service):
        """Test that unknown coin returns None."""
        result = price_service.get_price_sek("geod", date(2024, 6, 15))

        assert result is None

    def test_api_404_returns_none(self, price_service, mock_httpx):
        """Test that 404 from API returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx.get.return_value = mock_response

        result = price_service.get_price_sek("nonexistent-coin", date(2024, 6, 15))

        assert result is None

    def test_api_rate_limit_429_returns_none(self, price_service, mock_httpx):
        """Test that 429 rate limit returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_httpx.get.return_value = mock_response

        result = price_service.get_price_sek("ethereum", date(2024, 6, 15))
        # Should return None on rate limit (no retry in this test)
        assert result is None

    def test_api_error_returns_none(self, price_service, mock_httpx):
        """Test that API error returns None."""
        mock_httpx.get.side_effect = Exception("Network error")

        result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert result is None

    def test_price_saved_to_cache(self, price_service, db_session, mock_httpx):
        """Test that fetched price is saved to cache."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "market_data": {
                "current_price": {
                    "sek": 25000.00,
                }
            }
        }
        mock_httpx.get.return_value = mock_response

        price_service.get_price_sek("ethereum", date(2024, 6, 15))

        # Verify cached in DB
        cached = (
            db_session.query(PriceCache)
            .filter_by(coin_id="ethereum", date=date(2024, 6, 15))
            .first()
        )

        assert cached is not None
        assert cached.price_sek == Decimal("25000.00")
        assert cached.source == "COINGECKO"

    def test_second_call_uses_cache(self, price_service, db_session, mock_httpx):
        """Test that second call for same coin/date uses cache."""
        # First call - mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "market_data": {
                "current_price": {
                    "sek": 25000.00,
                }
            }
        }
        mock_httpx.get.return_value = mock_response

        # First call
        result1 = price_service.get_price_sek("ethereum", date(2024, 6, 15))
        assert result1 == Decimal("25000.00")
        assert mock_httpx.get.call_count == 1

        # Second call - should use cache
        result2 = price_service.get_price_sek("ethereum", date(2024, 6, 15))
        assert result2 == Decimal("25000.00")
        # API should NOT be called again
        assert mock_httpx.get.call_count == 1

    def test_coingecko_date_format(self, price_service, mock_httpx):
        """Test that CoinGecko API uses DD-MM-YYYY format."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"market_data": {"current_price": {"sek": 25000.00}}}
        mock_httpx.get.return_value = mock_response

        price_service.get_price_sek("ethereum", date(2024, 6, 15))

        # Verify the date param uses DD-MM-YYYY format
        call_args = mock_httpx.get.call_args
        called_params = call_args[1].get("params", {})
        assert called_params.get("date") == "15-06-2024", (
            f"Expected '15-06-2024' in params, got: {called_params}"
        )


class TestPriceServiceBatch:
    """Tests for PriceService.get_prices_batch method."""

    def test_batch_all_cached(self, price_service, db_session):
        """Test batch returns all cached prices without API calls."""
        # Pre-populate cache
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

    def test_batch_mixed_cache_and_api(self, price_service, db_session, mock_httpx):
        """Test batch with some cached, some needing API."""
        # Pre-populate one cache entry
        cached = PriceCache(
            coin_id="bitcoin",
            date=date(2024, 6, 15),
            price_sek=Decimal("500000.00"),
            source="COINGECKO",
        )
        db_session.add(cached)
        db_session.commit()

        # Mock API for ethereum
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"market_data": {"current_price": {"sek": 25000.00}}}
        mock_httpx.get.return_value = mock_response

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
    def test_api_key_in_header(self, mock_settings, price_service, mock_httpx):
        """Test that API key is included in request header."""
        mock_settings.coingecko_api_key = "test-api-key-123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"market_data": {"current_price": {"sek": 25000.00}}}
        mock_httpx.get.return_value = mock_response

        price_service.get_price_sek("ethereum", date(2024, 6, 15))

        # Verify headers
        call_kwargs = mock_httpx.get.call_args[1]
        assert "headers" in call_kwargs
        assert call_kwargs["headers"]["x-cg-demo-api-key"] == "test-api-key-123"

    @patch("kryptoskatt.services.price.settings")
    def test_no_api_key_no_header(self, mock_settings, price_service, mock_httpx):
        """Test that no API key means no custom header."""
        mock_settings.coingecko_api_key = ""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"market_data": {"current_price": {"sek": 25000.00}}}
        mock_httpx.get.return_value = mock_response

        price_service.get_price_sek("ethereum", date(2024, 6, 15))

        # Verify no custom header added
        call_kwargs = mock_httpx.get.call_args[1]
        # Should not have x-cg-demo-api-key header when no API key
        if "headers" in call_kwargs:
            assert "x-cg-demo-api-key" not in call_kwargs["headers"]


class TestDecimalConversion:
    """Tests for Decimal conversion from float."""

    def test_float_converted_to_decimal(self, price_service, mock_httpx):
        """Test that float prices are converted to Decimal."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # API returns float (JSON number)
        mock_response.json.return_value = {"market_data": {"current_price": {"sek": 25000.50}}}
        mock_httpx.get.return_value = mock_response

        result = price_service.get_price_sek("ethereum", date(2024, 6, 15))

        assert isinstance(result, Decimal)
        assert result == Decimal("25000.50")
