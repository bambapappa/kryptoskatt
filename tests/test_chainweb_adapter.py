"""Tests for ChainwebAdapter (Kadena)."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kryptoskatt.chains.chainweb import ChainwebAdapter
from kryptoskatt.enums import Chain, EventType


ADDRESS = "k:abc123def456"


@pytest.fixture
def adapter():
    return ChainwebAdapter()


def _make_item(from_account: str, to_account: str, amount: str = "5.0", token: str = "coin") -> dict:
    return {
        "requestKey": "abc-req-key-001",
        "fromAccount": from_account,
        "toAccount": to_account,
        "amount": amount,
        "token": token,
        "blockTime": "2024-01-15T10:00:00.000Z",
        "height": 4000000,
    }


def _mock_client(responses: list[dict]):
    """Return a context-manager-compatible mock that yields responses in sequence."""
    mock_client = MagicMock()
    side_effects = []
    for r in responses:
        m = MagicMock()
        m.json.return_value = r
        m.raise_for_status = MagicMock()
        side_effects.append(m)
    mock_client.get.side_effect = side_effects
    return mock_client


class TestChainwebAdapterSupportedChains:
    def test_supported_chains_includes_kadena(self, adapter):
        assert Chain.KADENA in adapter.supported_chains()

    def test_supported_chains_length(self, adapter):
        assert len(adapter.supported_chains()) == 1


class TestChainwebAdapterFetchTransferIn:
    def test_fetch_returns_transfer_in(self, adapter):
        """toAccount == address → TRANSFER_IN."""
        items = [_make_item(from_account="k:sender999", to_account=ADDRESS)]
        empty: list = []

        client = _mock_client([items, empty])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert len(result) == 1
        tx = result[0]
        assert tx.event_type == EventType.TRANSFER_IN.value

    def test_fetch_transfer_in_populates_fields(self, adapter):
        items = [_make_item(from_account="k:sender999", to_account=ADDRESS, amount="12.5")]
        empty: list = []

        client = _mock_client([items, empty])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        tx = result[0]
        assert tx.base_amount == Decimal("12.5")
        assert tx.tx_hash == "abc-req-key-001"
        assert tx.to_address == ADDRESS


class TestChainwebAdapterFetchTransferOut:
    def test_fetch_returns_transfer_out(self, adapter):
        """fromAccount == address → TRANSFER_OUT."""
        items = [_make_item(from_account=ADDRESS, to_account="k:recipient777")]
        empty: list = []

        client = _mock_client([items, empty])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert len(result) == 1
        assert result[0].event_type == EventType.TRANSFER_OUT.value


class TestChainwebAdapterTokenNormalization:
    def test_fetch_normalizes_coin_token_to_kda(self, adapter):
        """token='coin' → base_coin='KDA'."""
        items = [_make_item(from_account="k:sender", to_account=ADDRESS, token="coin")]
        empty: list = []

        client = _mock_client([items, empty])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert result[0].base_coin == "KDA"

    def test_fetch_token_contract_normalized(self, adapter):
        """token='free.hypercent.prod-hype-coin' → last segment uppercased."""
        items = [_make_item(from_account="k:sender", to_account=ADDRESS, token="free.hypercent")]
        empty: list = []

        client = _mock_client([items, empty])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert result[0].base_coin == "HYPERCENT"


class TestChainwebAdapterPagination:
    def test_fetch_paginates(self, adapter):
        """First call returns PAGE_SIZE items, second returns 0 → two API calls total."""
        page1 = [_make_item(from_account="k:s", to_account=ADDRESS)] * ChainwebAdapter.PAGE_SIZE
        page2: list = []

        client = _mock_client([page1, page2])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            with patch("kryptoskatt.chains.chainweb.time.sleep"):  # skip delays
                result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert client.get.call_count == 2
        assert len(result) == ChainwebAdapter.PAGE_SIZE

    def test_fetch_stops_when_partial_page(self, adapter):
        """Partial page (< PAGE_SIZE) → only one API call."""
        page1 = [_make_item(from_account="k:s", to_account=ADDRESS)] * 5
        client = _mock_client([page1])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert client.get.call_count == 1
        assert len(result) == 5


class TestChainwebAdapterEdgeCases:
    def test_unrelated_tx_skipped(self, adapter):
        """tx where neither from nor to matches address is skipped."""
        items = [_make_item(from_account="k:other1", to_account="k:other2")]
        client = _mock_client([items])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert result == []

    def test_api_error_returns_empty(self, adapter):
        """HTTP error → logs and returns empty list."""
        client = MagicMock()
        client.get.side_effect = Exception("Connection refused")
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert result == []

    def test_all_amounts_are_decimal(self, adapter):
        """base_amount is always a Decimal instance."""
        items = [_make_item(from_account="k:s", to_account=ADDRESS, amount="99.123456")]
        empty: list = []
        client = _mock_client([items, empty])
        with patch("kryptoskatt.chains.chainweb.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(return_value=client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = adapter.fetch_transactions(ADDRESS, Chain.KADENA)

        assert isinstance(result[0].base_amount, Decimal)
