"""KryptoSkatt configuration using pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql://kryptoskatt:kryptoskatt@db:5432/kryptoskatt",
        description="PostgreSQL database connection URL",
    )

    # API Keys (empty by default - user must provide their own)
    etherscan_api_key: str = Field(
        default="",
        description="Etherscan API key for Ethereum transactions",
    )
    helius_api_key: str = Field(
        default="",
        description="Helius API key for Solana transactions",
    )
    coingecko_api_key: str = Field(
        default="",
        description="CoinGecko API key for price data",
    )
    coinbase_api_key: str = Field(
        default="",
        description="Coinbase API key for exchange data",
    )
    subscan_api_key: str = Field(
        default="",
        description="Subscan API key for Substrate-based chains (PEAQ etc.)",
    )
    tronscan_api_key: str = Field(
        default="",
        description="Tronscan API key for TRON network transactions",
    )
    vechainstats_api_key: str = Field(
        default="",
        description="VeChain Stats API key for VeChain network transactions",
    )
    coinapi_api_key: str = Field(
        default="",
        description="CoinAPI.io API key for historical price data",
    )

    # Local price history directory (pre-loaded CSV exports from CoinGecko/CMC)
    price_history_dir: str = Field(
        default="PriceHistory",
        description="Directory containing historical price CSV files (relative to CWD or absolute)",
    )


# Singleton instance
settings = Settings()
