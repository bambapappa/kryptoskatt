# KryptoSkatt

A Swedish crypto tax calculation CLI tool that helps calculate capital gains and losses for cryptocurrency transactions according to Swedish tax regulations.

## Features

- **Transaction Import**: Import transactions from exchange exports (CSV format)
  - Coinbase
  - Crypto.com
  - MEXC
- **Blockchain Fetching**: Fetch transactions directly from blockchain explorers
  - Ethereum (via Etherscan)
  - Solana (via Solscan)
- **Tax Calculation**: Calculate capital gains/losses using the Swedish GAV (genomsnittsmetoden/average cost method)
- **K4 Reports**: Generate Swedish K4 tax report summaries
- **Web Interface**: View reports and transaction data via web UI

## Requirements

- Python 3.12+
- PostgreSQL database
- API keys for blockchain explorers (optional)

## Installation

```bash
# Clone and install
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

## Configuration

Create a `.env` file with the following variables:

```env
# Database
DATABASE_URL=postgresql://kryptoskatt:kryptoskatt@localhost:5432/kryptoskatt

# Optional: Blockchain API keys
ETHERSCAN_API_KEY=your_etherscan_api_key
SOLSCAN_API_KEY=your_solscan_api_key

# Optional: Coinbase API (for read-only access)
COINBASE_API_KEY=your_coinbase_api_key
COINBASE_API_SECRET=your_coinbase_secret
```

## Usage

### CLI Commands

#### Import transactions from exchange export files

```bash
kryptoskatt import --file transactions.csv --platform coinbase
```

Supported platforms: `coinbase`, `crypto_com`, `mexc`

Auto-detection is used if `--platform` is not specified.

#### Fetch transactions from blockchain

```bash
# Fetch for specific address
kryptoskatt fetch --address 0x... --chain ethereum

# Fetch for all registered wallets
kryptoskatt fetch --all
```

#### Manage wallets

```bash
# Add a wallet
kryptoskatt wallet add --address 0x... --chain ethereum --label "My ETH Wallet"

# List wallets
kryptoskatt wallet list

# Remove a wallet
kryptoskatt wallet remove --address 0x...
```

#### Calculate tax for a year

```bash
kryptoskatt calculate 2024
```

#### Generate tax report

```bash
# Generate CSV report
kryptoskatt report 2024 --format csv

# Generate JSON report
kryptoskatt report 2024 --format json --output-dir ./reports

# Include full transaction list
kryptoskatt report 2024 --full
```

#### Check for data issues

```bash
kryptoskatt issues 2024
```

#### Start web server

```bash
kryptoskatt serve --host 0.0.0.0 --port 8000
```

## Docker Deployment

```bash
# Start the application
docker-compose up -d

# Run migrations
docker-compose exec app alembic upgrade head

# Stop
docker-compose down
```

## Project Structure

```
src/kryptoskatt/
├── cli/                  # CLI commands
│   ├── calculate_cmd.py  # Tax calculation
│   ├── fetch_cmd.py      # Blockchain fetching
│   ├── import_cmd.py     # Transaction import
│   ├── issues_cmd.py     # Data issue checking
│   ├── report_cmd.py     # Report generation
│   ├── serve_cmd.py      # Web server
│   └── wallet.py         # Wallet management
├── chains/               # Blockchain adapters
│   ├── base.py           # Base chain interface
│   ├── etherscan.py     # Ethereum explorer
│   └── solscan.py       # Solana explorer
├── engine/               # Core calculation engine
│   ├── gav.py            # GAV (average cost) calculation
│   ├── dedup.py          # Transaction deduplication
│   └── transfers.py      # Transfer matching
├── models/               # Database models
├── parsers/              # Exchange file parsers
│   ├── coinbase.py
│   ├── crypto_com.py
│   └── mexc.py
├── reports/              # Report generators
│   ├── gav_history.py    # GAV history report
│   ├── issues.py         # Issues report
│   └── k4.py             # K4 tax form data
├── services/             # Business services
│   ├── price.py          # Price fetching
│   └── wallet.py         # Wallet service
├── web/                  # Web application
│   └── app.py            # FastAPI app
└── config.py             # Configuration
```

## Database Schema

- **transactions**: Imported transactions from exchanges/wallets
- **wallets**: Tracked wallet addresses
- **disposals**: Calculated disposals (sales)
- **gav_ledger**: Running GAV per coin
- **price_cache**: Cached historical prices
- **transfer_links**: Linked transfers between addresses

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src

# Lint
ruff check src/
```

## License

MIT
