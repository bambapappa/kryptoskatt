"""Tests for the Riksbank USD/SEK rate service."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kryptoskatt.services.riksbank import get_usd_sek_rate


@pytest.fixture
def mock_httpx_client():
    """Patch httpx.Client used in riksbank module."""
    with patch("kryptoskatt.services.riksbank.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_client


class TestGetUsdSekRate:
    def test_get_rate_mocked(self, mock_httpx_client):
        """Returns the most recent Decimal rate from a valid API response."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"date": "2024-01-12", "value": 10.42},
            {"date": "2024-01-15", "value": 10.55},
        ]
        mock_httpx_client.get.return_value = mock_resp

        result = get_usd_sek_rate(date(2024, 1, 15))

        assert result == Decimal("10.55")

    def test_get_rate_returns_nearest_prior_day_on_weekend(self, mock_httpx_client):
        """Returns the last available rate when target_date has no observation."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        # Saturday 2024-01-13 has no entry; last available is Friday 2024-01-12
        mock_resp.json.return_value = [
            {"date": "2024-01-10", "value": 10.30},
            {"date": "2024-01-11", "value": 10.35},
            {"date": "2024-01-12", "value": 10.42},
        ]
        mock_httpx_client.get.return_value = mock_resp

        result = get_usd_sek_rate(date(2024, 1, 13))

        assert result == Decimal("10.42")

    def test_get_rate_empty_response_returns_none(self, mock_httpx_client):
        """Returns None when the API returns an empty list."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = []
        mock_httpx_client.get.return_value = mock_resp

        result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_get_rate_network_error_returns_none(self, mock_httpx_client):
        """Returns None when httpx raises an exception."""
        mock_httpx_client.get.side_effect = Exception("connection refused")

        result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_get_rate_http_error_returns_none(self, mock_httpx_client):
        """Returns None when raise_for_status raises (e.g. 500 response)."""
        import httpx as _httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_httpx_client.get.return_value = mock_resp

        result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_get_rate_non_list_response_returns_none(self, mock_httpx_client):
        """Returns None when API returns unexpected format (dict instead of list)."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"observations": [{"date": "2024-01-15", "value": 10.5}]}
        mock_httpx_client.get.return_value = mock_resp

        result = get_usd_sek_rate(date(2024, 1, 15))

        assert result is None

    def test_return_type_is_decimal(self, mock_httpx_client):
        """Returned value is always Decimal, never float."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{"date": "2024-06-01", "value": 10.7654}]
        mock_httpx_client.get.return_value = mock_resp

        result = get_usd_sek_rate(date(2024, 6, 1))

        assert isinstance(result, Decimal)
