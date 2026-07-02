"""Tests for the Riksbank USD/SEK rate service."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from kryptoskatt.services.riksbank import get_usd_sek_rate


def _mock_response(data) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = data
    return m


class TestGetUsdSekRate:
    def test_get_rate_mocked(self):
        """Returns the most recent Decimal rate from a valid API response."""
        resp = _mock_response([
            {"date": "2024-01-12", "value": 10.42},
            {"date": "2024-01-15", "value": 10.55},
        ])
        with patch("kryptoskatt.services.riksbank.get_with_retry", return_value=resp):
            result = get_usd_sek_rate(date(2024, 1, 15))

        assert result == Decimal("10.55")

    def test_get_rate_returns_nearest_prior_day_on_weekend(self):
        """Returns the last available rate when target_date has no observation."""
        resp = _mock_response([
            {"date": "2024-01-10", "value": 10.30},
            {"date": "2024-01-11", "value": 10.35},
            {"date": "2024-01-12", "value": 10.42},
        ])
        with patch("kryptoskatt.services.riksbank.get_with_retry", return_value=resp):
            result = get_usd_sek_rate(date(2024, 1, 13))

        assert result == Decimal("10.42")

    def test_get_rate_empty_response_returns_none(self):
        """Returns None when the API returns an empty list."""
        resp = _mock_response([])
        with patch("kryptoskatt.services.riksbank.get_with_retry", return_value=resp):
            result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_get_rate_network_error_returns_none(self):
        """Returns None when get_with_retry raises an exception."""
        with patch(
            "kryptoskatt.services.riksbank.get_with_retry",
            side_effect=Exception("connection refused"),
        ):
            result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_get_rate_http_error_returns_none(self):
        """Returns None when raise_for_status raises (e.g. 500 response)."""
        import httpx as _httpx

        resp = MagicMock()
        resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        with patch("kryptoskatt.services.riksbank.get_with_retry", return_value=resp):
            result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_get_rate_non_list_response_returns_none(self):
        """Returns None when API returns unexpected format (dict instead of list)."""
        resp = _mock_response({"observations": [{"date": "2024-01-15", "value": 10.5}]})
        with patch("kryptoskatt.services.riksbank.get_with_retry", return_value=resp):
            result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_return_type_is_decimal(self):
        """Returned value is always Decimal, never float."""
        resp = _mock_response([{"date": "2024-06-01", "value": 10.7654}])
        with patch("kryptoskatt.services.riksbank.get_with_retry", return_value=resp):
            result = get_usd_sek_rate(date(2024, 6, 1))

        assert isinstance(result, Decimal)
