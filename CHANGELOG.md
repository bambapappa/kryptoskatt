# Changelog

All notable changes to KryptoSkatt are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [0.5.0] — 2026-07

### Added
- Background jobs for fetch-all and tax calculation: long-running actions no longer block the request (and no longer time out behind reverse proxies); the actions page shows live progress
- Per-account coin blacklist (migration 013) — one account's hidden spam coins no longer affect other accounts on the same instance
- Custom chain API keys are encrypted at rest (Fernet) when `SECRET_KEY` is set; legacy plaintext values keep working
- Repository governance: CODEOWNERS, Dependabot (pip/actions/docker) and CodeQL security scanning

### Security
- Session tokens are now stored as SHA-256 hashes in the database — a database leak no longer exposes usable session tokens. **Existing sessions are invalidated on upgrade; log in again with your account ID.**
- Rate limiting (10/min per IP) on login and account creation, both web and REST API
- Coin blacklist endpoints (`/year/{year}/blacklist-coin`, `/year/{year}/unblacklist-coin`) now require authentication
- Report downloads use unique private temp files instead of predictable `/tmp` paths
- Extended security headers: `Content-Security-Policy`, `Strict-Transport-Security` (HTTPS), `Permissions-Policy`; `X-Content-Type-Options` on all responses
- Docker: runtime image no longer contains gcc or dev/test dependencies; added container `HEALTHCHECK`; `no-new-privileges` in docker-compose
- CI: least-privilege workflow permissions and `pip-audit` dependency vulnerability scanning

### Changed
- **License changed from MIT to Apache License 2.0** (adds explicit patent grant); added `NOTICE` file
- Dependency floors raised across the board (FastAPI ≥0.115, SQLAlchemy ≥2.0.36, Pydantic ≥2.10, etc.); verified against latest releases
- Python 3.13 added to supported versions
- `AuthService.create_session()` now returns `(UserSession, raw_token)` instead of a `UserSession`
- `web/app.py` (2 800 lines) split into per-domain routers under `web/routes/`; shared dependencies in `web/deps.py` and `web/templating.py`

---

## [0.4.0] — 2025

### Added
- Custom chain support: users can configure custom Blockscout/Etherscan-compatible chains via the web UI
- Help tooltips throughout the web UI
- T2 manual income entry management
- Exponential backoff retry on all external API calls
- Onboarding flow with multi-chain EVM address support
- GDPR account export and deletion (API and web)
- GitHub Actions CI/CD pipeline with Docker image publishing to GHCR

### Changed
- Dashboard now shows T2/transfers links per tax year
- Fetch deduplication improved: zero-value and failed transactions are skipped
- Address matching is now case-insensitive for EVM chains

### Fixed
- Etherscan adapter: skip transactions where `base_amount` is zero
- Transfer matching: use SQL `extract()` instead of `strftime()` for PostgreSQL compatibility
- Riksbanken exchange rate series name corrected (`SEKUSDPMI`)
- Cookie `Secure` flag auto-detected based on whether the request arrived over HTTPS
- Docker: templates and data files now correctly included in installed package

---

## [0.3.0] — 2025

### Added
- Web UI redesign with Nordic official aesthetic
- Actions dashboard with fetch-all, calculate, and dedup buttons
- Unknown addresses view — surfaces unmatched TRANSFER_OUT addresses
- T2 income/cost report
- Net position report (current holdings)
- Audit export (full transaction list with disposal linkage)
- Wallet categories (exchange, hardware, software, custodial, other)
- Helius Solana adapter (higher quality than Solscan — returns wallet-owner addresses)
- CSV price history import (bulk load historical prices from CoinGecko/CMC exports)
- Swap-implied pricing: infers missing prices from matched swap pairs
- GAV history view (per-coin ledger of all cost-basis changes)
- Flagged issues report (missing prices, negative balances, unlinked transfers)

### Changed
- Frontend migrated away from PicoCSS to custom Nordic theme
- Packaging: templates and static files now included in `pip install`

### Fixed
- GAV sort order: acquisitions now correctly sort before disposals at identical timestamps
- Transfer cost basis calculation
- Fetch deduplication when re-importing the same chain

---

## [0.2.0] — 2024

### Added
- FastAPI web server with Jinja2 templates
- K4 tax form report generation (CSV and console output)
- GAV calculation engine implementing genomsnittsmetoden (average cost method)
- Deduplication engine (exact tx\_hash matching + heuristic time-window matching)
- Transfer matching engine (TX\_HASH, AMOUNT\_TIME, and MANUAL methods)
- CoinGecko price service with database caching and Riksbanken SEK conversion
- Blockchain adapters: Etherscan v2 (ETH/Polygon/BNB/Base/Arbitrum), Solscan v2 (Solana), Blockstream (Bitcoin), Tronscan (TRON), VeChain Stats, Subscan (PEAQ/Substrate), XRPL (XRP), Chainweb (Kadena)
- CSV/TSV parsers: Coinbase, Coinbase Advanced Trade, Crypto.com, MEXC, Binance, KuCoin, Kraken, Bybit, Ledger Live, manual swap
- Wallet registry with CLI commands (`wallet add/list/remove`)
- Multi-tenant isolation: every account's data scoped by `user_id`
- Anonymous accounts (no email/password; identified by random passphrase)
- REST API v1 (`/api/v1/`)

---

## [0.1.0] — 2024

### Added
- Project skeleton with Docker and PostgreSQL setup
- Alembic database migration infrastructure
- SQLAlchemy ORM models (Transaction, Wallet, Account, Session, etc.)
- Pydantic schemas and enums (`EventType`, `Chain`, `Platform`)
- CLI entry point (`kryptoskatt`) with Typer
- Application configuration via pydantic-settings (`.env` file)
- Pytest infrastructure and smoke tests

---

[Unreleased]: https://github.com/Bambapappa/kryptoskatt/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Bambapappa/kryptoskatt/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Bambapappa/kryptoskatt/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Bambapappa/kryptoskatt/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Bambapappa/kryptoskatt/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Bambapappa/kryptoskatt/releases/tag/v0.1.0
