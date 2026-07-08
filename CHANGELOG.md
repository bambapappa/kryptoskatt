# Changelog

All notable changes to KryptoSkatt are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- **Per-account API keys**: each account can store its own Etherscan/Helius/Solscan/Tronscan/VeChainStats/Subscan keys (encrypted at rest) instead of sharing the instance-wide keys; adapters fall back to the instance key when an account has none. Managed on the settings page (migration 015)
- **Read-only share links for accountants**: generate a time-limited, revocable link (hashed token, migration 016) that shows an account's K4 summary, GAV carryover and net positions without login and without any way to change data
- **Year-to-year GAV carryover report**: per-coin opening (carried in from the previous year) and closing holdings/cost-basis, with a web page, CSV download and `report --format carryover` CLI export
- **NFT ledger import** (`nft` platform): records NFT buys/sells in SEK as unique per-token assets (`NFT:<collection>#<token_id>`) that flow through the GAV engine into K4/SRU; Ledger NFT operations are tagged for auditability
- **Free exchange price fallbacks**: Binance and Kraken public OHLC (USD/USDT close → SEK via Riksbank) are tried after CoinGecko and before CoinAPI, filling prices for coins missing from the CoinGecko map without an API key
- **Bitcoin xpub/ypub/zpub support**: derive all addresses from an extended public key (BIP32 → P2PKH/P2SH-P2WPKH/P2WPKH) with a gap-limit scan against Blockstream; `kryptoskatt wallet add-xpub` and a web form. Only public keys are handled
- **REWARD classification** (staking/mining/airdrop/interest/other): parsers auto-classify where the source states it (Bitstamp, OKX, Gate.io, Kraken); the T2 income report groups by type; manual classification via `/transactions/classify-reward` (migration 014)
- **Web UI internationalisation**: Swedish default with an English translation of the navigation/footer and a language switcher in the header; incremental `t()` mechanism with graceful fallback
- **SRU export for Skatteverket** (K4 section D — cryptocurrencies): generates `INFO.SRU` + `BLANKETTER.SRU` for upload via the tax agency's "Filöverföring" service. Available on the year page (downloads a ZIP after entering personnummer/name) and via the CLI (`kryptoskatt report <year> --format sru --personnummer … --namn …`). Handles fractional *antal* with comma decimals, whole-krona amounts, and pagination across multiple K4 pages (7 rows each)
- New exchange parsers with auto-detection: **Bitstamp** (v1 + v2 transaction exports), **OKX** (trading statement + funding bill) and **Gate.io** (account bill), incl. sample fixtures and tests
- GitHub link in the site footer

### Changed
- **Dependencies bumped to latest** across the board (FastAPI ≥0.139, SQLAlchemy ≥2.0.51, Pydantic ≥2.13, uvicorn ≥0.50, cryptography ≥49, Typer ≥0.26, and the dev tools); verified against the full test suite, mypy and ruff
- **Docker runtime image now uses Python 3.13**; the build takes an `APP_VERSION` build-arg that busts the dependency layer so every new image automatically re-resolves dependencies to the latest versions allowed by `pyproject.toml`
- CI now runs `mypy` type checking (gradual: the core is checked; the chain-adapter and web layers are exempted until they can be tightened); CI tests on Python 3.13; Docker Compose and the CI database moved to **PostgreSQL 18**, with a configurable `POSTGRES_IMAGE` so an existing instance can pin its current major during an upgrade (a dump/restore is needed to actually move to a new major — see README)

### Fixed
- Security: fixed an IDOR in `/transactions/bulk-tag` which updated rows by id without scoping to the current account; also fixed pre-existing broken CLI `wallet` commands (missing user_id)
- The `kryptoskatt issues <year>` CLI command was broken (it constructed `FlaggedIssuesGenerator` without the required `user_id` and crashed); it now scopes to the legacy account
- **CSV re-import protection**: uploading the same export file twice no longer duplicates rows — identical rows already in the database are skipped and reported as duplicates (previously the "duplicates skipped" count was always 0 and every re-upload doubled the data)

---

## [0.5.0] — 2026-07

### Added
- Background jobs for fetch-all and tax calculation: long-running actions no longer block the request (and no longer time out behind reverse proxies); the actions page shows live progress
- Per-account coin blacklist (migration 013) — one account's hidden spam coins no longer affect other accounts on the same instance
- Custom chain API keys are encrypted at rest (Fernet) when `SECRET_KEY` is set; legacy plaintext values keep working
- Repository governance: CODEOWNERS, Dependabot (pip/actions/docker) and CodeQL security scanning
- CSRF protection: Origin/Referer validation on all state-changing requests (defense-in-depth on top of SameSite=Lax)
- Free-text search on the transactions page (tx hash, addresses, coin)
- Account ID shown as a QR code on the account-created page (scan to bring it to your phone)
- Migrations are serialized across replicas with a PostgreSQL advisory lock
- `LOG_LEVEL` is now applied to the root logger and uvicorn on `kryptoskatt serve`

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
- Switched from psycopg2 to **psycopg 3** (`postgresql://` URLs are routed to the new driver automatically); the Docker build no longer needs gcc/libpq-dev
- All 15 copies of the DB session dependency consolidated into `kryptoskatt.db.get_db`
- Docker entrypoint: worker count via `WEB_CONCURRENCY` (default 1 — rate limiter and job manager are per-process) and trusted proxy config via `FORWARDED_ALLOW_IPS`
- Version string single-sourced from `kryptoskatt.__version__` (pyproject reads it dynamically)
- Settings page shows session IDs instead of session token prefixes

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
