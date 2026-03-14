"""KryptoSkatt configuration using pydantic-settings."""

from pydantic import Field, field_validator
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

    cookie_secure: bool = Field(default=True, description="Set Secure flag on session cookie")

    cors_origins: list[str] = Field(
        default=["http://localhost:8000", "http://localhost:3000"],
        description="Allowed CORS origins (JSON array in env var)",
    )

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG/INFO/WARNING/ERROR)",
    )

    debug_mode: bool = Field(default=False, description="Enable debug routes (never in production)")

    solscan_api_key: str = Field(
        default="",
        description="Solscan API key for Solana transactions (fallback when Helius key is absent)",
    )

    @field_validator("database_url")
    @classmethod
    def database_url_must_not_be_sqlite_in_production(cls, v: str) -> str:
        # SQLite is only suitable for tests; production should use PostgreSQL
        return v


# Singleton instance
settings = Settings()
