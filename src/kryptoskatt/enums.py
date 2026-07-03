"""Enums shared between models and schemas."""

from enum import StrEnum


class Chain(StrEnum):
    """Supported blockchain networks."""

    SOLANA = "SOLANA"
    ETHEREUM = "ETHEREUM"
    POLYGON = "POLYGON"
    BNB = "BNB"
    KADENA = "KADENA"
    TRON = "TRON"
    VECHAIN = "VECHAIN"
    PEAQ = "PEAQ"
    ALEO = "ALEO"
    RIPPLE = "RIPPLE"
    BITCOIN = "BITCOIN"
    BASE = "BASE"
    MXC_ZKEVM = "MXC_ZKEVM"
    ARBITRUM = "ARBITRUM"
    UNKNOWN = "UNKNOWN"


class Platform(StrEnum):
    """Data sources for transactions."""

    COINBASE = "COINBASE"
    CRYPTO_COM = "CRYPTO_COM"
    MEXC = "MEXC"
    ON_CHAIN = "ON_CHAIN"
    MANUAL = "MANUAL"


class EventType(StrEnum):
    """Transaction event types."""

    BUY = "BUY"
    SELL = "SELL"
    SWAP_IN = "SWAP_IN"
    SWAP_OUT = "SWAP_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    REWARD = "REWARD"
    FEE = "FEE"
    UNKNOWN = "UNKNOWN"


class RewardType(StrEnum):
    """Sub-classification of REWARD events for Swedish income (T2) reporting.

    Staking/lending/interest are typically kapitalinkomst; mining is often
    tjänst/hobby. The distinction matters for how income is declared, so we
    keep it explicit rather than lumping all rewards together.
    """

    STAKING = "staking"
    MINING = "mining"
    AIRDROP = "airdrop"
    INTEREST = "interest"
    OTHER = "other"


class MatchMethod(StrEnum):
    """How transfer links are matched."""

    TX_HASH = "TX_HASH"
    AMOUNT_TIME = "AMOUNT_TIME"
    MANUAL = "MANUAL"


class PriceSource(StrEnum):
    """Where price data comes from."""

    COINGECKO = "COINGECKO"
    COINAPI = "COINAPI"
    MANUAL = "MANUAL"
    EXCHANGE_REPORTED = "EXCHANGE_REPORTED"
