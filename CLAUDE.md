# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**KryptoSkatt** — Swedish crypto tax calculation CLI/web tool. Implements Swedish GAV (genomsnittsmetoden / average cost method) for capital gains reporting. Outputs K4 tax form summaries.

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run all tests
pytest

# Run single test file
pytest tests/test_gav.py

# Run single test
pytest tests/test_gav.py::test_buy_and_sell

# Lint
ruff check src/

# Run CLI
kryptoskatt --help

# Start web server
kryptoskatt serve --host 0.0.0.0 --port 8000

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Docker — starts web server automatically (migrations run on boot)
docker-compose up -d

# Run CLI commands in the running container
docker-compose exec app kryptoskatt <command>

# Example: import a file (copy it into the container first)
docker cp myfile.csv kryptoskatt-app:/tmp/
docker-compose exec app kryptoskatt import --file /tmp/myfile.csv

# Example: calculate
docker-compose exec app kryptoskatt calculate 2024
```

## Architecture

### Data flow
1. **Import** CSV/TSV from exchanges (Coinbase, Crypto.com, MEXC) or fetch on-chain (Etherscan/Solscan) → `Transaction` rows in DB
2. **Dedup** (`engine/dedup.py`) marks duplicate `Transaction.is_duplicate = True`
3. **Transfer matching** (`engine/transfers.py`) links TRANSFER_OUT ↔ TRANSFER_IN via `TransferLink`
4. **GAV calculation** (`engine/gav.py`) processes all non-duplicate transactions chronologically → `Disposal` + `GavLedger` rows
5. **Reports** (`reports/`) read disposals/ledger → K4 summaries, GAV history, flagged issues
6. **Web** (`web/app.py`) FastAPI app with Jinja2 templates serving the reports

### Key domain rules
- All monetary amounts use `Decimal` (never `float`)
- Timestamps are always UTC
- Unlinked `TRANSFER_OUT` is treated as a taxable disposal
- At same timestamp: acquisitions (BUY/SWAP_IN/REWARD) sort before disposals (SELL/SWAP_OUT)
- GAV resets to zero cost when holdings reach exactly zero units

### EventType enum (enums.py)
`BUY | SELL | SWAP_IN | SWAP_OUT | TRANSFER_IN | TRANSFER_OUT | REWARD | FEE | UNKNOWN`

### Database (SQLAlchemy sync, not async)
Despite `sqlalchemy[asyncio]` being listed as a dependency, the DB layer (`db.py`) uses synchronous SQLAlchemy. `get_session()` returns a plain `Session`. The `[asyncio]` extra is there for potential future use. Don't add `async_sessionmaker` unless intentionally migrating.

### Config
`config.py` uses `pydantic-settings`. All settings come from env vars or `.env` file. The singleton `settings` object is imported directly where needed.

### Tests
- All tests in `tests/`, fixtures in `tests/fixtures/`
- `conftest.py` provides `TransactionCreate` schema fixtures — use these, not raw dicts
- Tests use an in-memory or test-configured DB (check individual test files for DB setup)
- `asyncio_mode = "auto"` in `pyproject.toml` — async tests just need `async def`

### Parser interface
Each parser in `parsers/` exposes a `parse(file_path: Path) -> list[TransactionCreate]` function. Parsers must normalize to `Decimal` amounts and UTC timestamps before returning.

### Blockchain search depth
- **Etherscan**: fetches complete history from block 0 to latest (no limit)
- **Solscan**: fetches complete history via cursor-based pagination (`before_hash`) — all pages
