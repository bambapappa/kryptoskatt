"""KryptoSkatt configuration using pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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
    solscan_api_key: str = Field(
        default="",
        description="Solscan API key for Solana transactions",
    )
    coingecko_api_key: str = Field(
        default="",
        description="CoinGecko API key for price data",
    )
    coinbase_api_key: str = Field(
        default="",
        description="Coinbase API key for exchange data",
    )


# Singleton instance
settings = Settings()
