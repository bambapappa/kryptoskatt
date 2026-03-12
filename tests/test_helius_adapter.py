"""Tests for HeliusAdapter — focusing on edge cases in _parse_tx."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from kryptoskatt.chains.helius import HeliusAdapter
from kryptoskatt.enums import EventType

OUR_WALLET = "9wystNMv4CC8LNVs3bFb2epYKg7dnrsg77pA3JvNmEKe"
OUR_TOKEN_ACCOUNT = "CAGfWWXbwW3NkbkHFxbhXn1RU7kywHTDaSipsRKeLhR8"
GEODNET_WALLET = "8eznVreusXAyh4HZirLWNjMxgoQdxzqfTi9Uw8gEL2RE"
GEOD_MINT = "CzYSquESBM4qVQiFas6pSMgeFRG4JLiYyNYHQUcNxudc"


@pytest.fixture
def adapter():
    return HeliusAdapter()


def _base_tx(sig="abc123", timestamp=1700000000):
    return {
        "signature": sig,
        "timestamp": timestamp,
        "fee": 5000,
        "feePayer": "someotherwallet",
        "nativeTransfers": [],
        "tokenTransfers": [],
        "accountData": [],
    }


class TestTokenTransfersFallback:
    """accountData fallback catches transfers where toUserAccount is a token account."""

    def test_geodnet_batch_payout_via_accountdata(self, adapter):
        """GEODNET pays 10 wallets at once. toUserAccount = token account (CAGf...),
        not wallet owner (9wyst...). tokenTransfers filter skips it, so we must
        fall back to accountData.tokenBalanceChanges."""
        tx = {
            **_base_tx("geodnet_reward_1"),
            "feePayer": GEODNET_WALLET,
            "tokenTransfers": [
                {
                    "fromUserAccount": GEODNET_WALLET,
                    "toUserAccount": OUR_TOKEN_ACCOUNT,  # token account, not wallet
                    "tokenAmount": 11.993543,
                    "mint": GEOD_MINT,
                }
            ],
            "accountData": [
                {
                    "account": OUR_TOKEN_ACCOUNT,
                    "nativeBalanceDifference": 0,
                    "tokenBalanceChanges": [
                        {
                            "userAccount": OUR_WALLET,  # wallet owner — what we need
                            "tokenAccount": OUR_TOKEN_ACCOUNT,
                            "mint": GEOD_MINT,
                            "rawTokenAmount": {
                                "tokenAmount": "11993543",
                                "decimals": 6,
                            },
                        }
                    ],
                }
            ],
        }

        results = adapter._parse_tx(tx, OUR_WALLET, {})

        assert len(results) == 1
        r = results[0]
        assert r.event_type == EventType.TRANSFER_IN
        assert r.base_amount == Decimal("11.993543")
        assert r.from_address == GEODNET_WALLET
        assert r.to_address == OUR_WALLET
        assert r.tx_hash == "geodnet_reward_1"

    def test_normal_transfer_not_double_counted(self, adapter):
        """When tokenTransfers already has toUserAccount = wallet, accountData
        must not produce a second TRANSFER_IN for the same mint."""
        tx = {
            **_base_tx("normal_transfer"),
            "tokenTransfers": [
                {
                    "fromUserAccount": GEODNET_WALLET,
                    "toUserAccount": OUR_WALLET,  # correctly set to wallet
                    "tokenAmount": 50.0,
                    "mint": GEOD_MINT,
                }
            ],
            "accountData": [
                {
                    "account": OUR_TOKEN_ACCOUNT,
                    "nativeBalanceDifference": 0,
                    "tokenBalanceChanges": [
                        {
                            "userAccount": OUR_WALLET,
                            "tokenAccount": OUR_TOKEN_ACCOUNT,
                            "mint": GEOD_MINT,
                            "rawTokenAmount": {"tokenAmount": "50000000", "decimals": 6},
                        }
                    ],
                }
            ],
        }

        results = adapter._parse_tx(tx, OUR_WALLET, {})
        transfer_ins = [r for r in results if r.event_type == EventType.TRANSFER_IN]
        assert len(transfer_ins) == 1
        assert transfer_ins[0].base_amount == Decimal("50.0")

    def test_outgoing_accountdata_not_captured(self, adapter):
        """Negative token balance change (outgoing) must not create a TRANSFER_IN."""
        tx = {
            **_base_tx("outgoing"),
            "tokenTransfers": [
                {
                    "fromUserAccount": OUR_WALLET,
                    "toUserAccount": GEODNET_WALLET,
                    "tokenAmount": 100.0,
                    "mint": GEOD_MINT,
                }
            ],
            "accountData": [
                {
                    "account": OUR_TOKEN_ACCOUNT,
                    "nativeBalanceDifference": 0,
                    "tokenBalanceChanges": [
                        {
                            "userAccount": OUR_WALLET,
                            "tokenAccount": OUR_TOKEN_ACCOUNT,
                            "mint": GEOD_MINT,
                            "rawTokenAmount": {"tokenAmount": "-100000000", "decimals": 6},
                        }
                    ],
                }
            ],
        }

        results = adapter._parse_tx(tx, OUR_WALLET, {})
        transfer_ins = [r for r in results if r.event_type == EventType.TRANSFER_IN]
        assert len(transfer_ins) == 0
