# Contributing to KryptoSkatt

Thank you for your interest in contributing! KryptoSkatt is a Swedish crypto tax calculator — contributions that improve accuracy, add exchange support, or improve usability are especially welcome.

## Getting started

### Prerequisites
- Python 3.12+
- PostgreSQL 14+ (or Docker)
- Git

### Local setup

```bash
git clone https://github.com/YOUR_USERNAME/kryptoskatt.git
cd kryptoskatt

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env
# Edit .env — at minimum set DATABASE_URL

alembic upgrade head
```

Run tests to verify setup:

```bash
pytest
```

## Development workflow

1. **Fork** the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Write tests** for any new functionality. Tests live in `tests/` and run against an in-memory SQLite database.

3. **Run the test suite** and lint before committing:
   ```bash
   pytest
   ruff check src/
   ```

4. **Commit** with a conventional commit message:
   ```
   feat(parsers): add Bitstamp CSV parser
   fix(gav): handle zero-amount transactions gracefully
   docs: update API reference for /wallets endpoint
   ```

5. **Open a pull request** against `main` with a clear description of what changed and why.

## What to contribute

### High-value contributions
- **New exchange parsers** — see `src/kryptoskatt/parsers/` for examples. Each parser exposes `parse(file_path: Path) -> list[TransactionCreate]`.
- **New blockchain adapters** — see `src/kryptoskatt/chains/base.py` for the interface. Implement `supported_chains()` and `fetch_transactions()`.
- **Bug fixes** — especially in the GAV engine or transfer matching logic.
- **Test coverage** — more tests for edge cases in `engine/gav.py` are always welcome.

### Please avoid
- Changing the core GAV algorithm without strong justification and Skatteverket citations.
- Adding dependencies that require a C compiler (use pure-Python alternatives where possible).
- Adding features that store personally identifiable information.

## Adding a new exchange parser

1. Create `src/kryptoskatt/parsers/my_exchange.py`
2. Implement `parse(file_path: Path) -> list[TransactionCreate]`
3. Register it in `src/kryptoskatt/parsers/__init__.py` and the platform map in `cli/import_cmd.py`
4. Add fixture files to `tests/fixtures/` and write parser tests

Look at `parsers/coinbase.py` for a well-documented example.

## Adding a new blockchain adapter

1. Create `src/kryptoskatt/chains/my_chain.py`
2. Subclass `BlockchainAdapter` from `chains/base.py`
3. Implement `supported_chains() -> list[str]` and `fetch_transactions(address, chain) -> list[TransactionCreate]`
4. Register in `chains/registry.py`
5. Add tests (see `tests/test_chains_*.py`)

## Code style

- **Formatting**: ruff (line length 100)
- **Types**: type hints on all public functions
- **Decimals**: always use `Decimal`, never `float` for monetary values
- **Timestamps**: always UTC (`datetime` with `tzinfo=timezone.utc`)
- **Docstrings**: for public classes and non-trivial functions

## Tax law accuracy

KryptoSkatt implements Swedish tax law. If you believe the implementation diverges from Skatteverket's guidance, please open an issue with a reference to the relevant rule or decision (beslut/ställningstagande). Changes to core tax logic require explicit justification.

## Reporting bugs

Use [GitHub Issues](../../issues). Include:
- KryptoSkatt version (`kryptoskatt --version`)
- Python version and OS
- Steps to reproduce
- Expected vs. actual behaviour
- Anonymised transaction data if relevant (never share real wallet addresses or API keys)

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
