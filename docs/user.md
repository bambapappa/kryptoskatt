# KryptoSkatt - User Guide

## Introduction

KryptoSkatt is a tool for calculating capital gains and losses for cryptocurrency transactions according to Swedish tax rules (average cost method / GAV).

## Getting Started

### 1. Installation

```bash
pip install -e .
```

### 2. Configuration

Create a `.env` file with database connection:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/kryptoskatt
```

### 3. Start Database

```bash
docker-compose up -d
alembic upgrade head
```

## Importing Transactions

### From Exchanges

Export your transactions from each exchange as CSV and import:

```bash
kryptoskatt import --file path/to/file.csv --platform coinbase
```

**Supported platforms:**
- `coinbase` - Coinbase export
- `crypto_com` - Crypto.com export
- `mexc` - MEXC export

Platform is auto-detected if not specified.

### From Wallets (Blockchain)

Add a wallet:

```bash
kryptoskatt wallet add --address 0xABC123... --chain ethereum --label "My ETH Wallet"
```

Fetch transactions:

```bash
# For a specific address
kryptoskatt fetch --address 0xABC123... --chain ethereum

# For all registered wallets
kryptoskatt fetch --all
```

## Calculating Taxes

### Calculate for a Year

```bash
kryptoskatt calculate 2024
```

This analyzes all transactions for the year and calculates:
- Number of disposals (sales)
- GAV (average acquisition cost) per currency
- Capital gains and losses

### Generate Report

```bash
# CSV format
kryptoskatt report 2024 --format csv

# JSON format
kryptoskatt report 2024 --format json --output-dir ./reports

# Include full transaction list
kryptoskatt report 2024 --full
```

## Web Interface

Start the web server:

```bash
kryptoskatt serve
```

Open `http://localhost:8000` in your browser.

### Dashboard

Select a tax year to view summary.

### Year Page (K4 Summary)

Shows:
- Total proceeds
- Total cost basis
- Total capital gain/loss
- Summary per currency

### Transactions

Review all imported transactions with filtering.

### GAV History

See how average acquisition cost has changed over time for each currency.

### Issues

View flagged problems in transaction data that need review.

## FAQ

### What is GAV?

GAV (Genomsnittligt AnskaffningsVärde - Average Acquisition Cost) is the method used in Sweden to calculate the cost basis for cryptocurrency. When you sell cryptocurrency, the average acquisition cost of all similar assets you owned is used.

### types are supported?

 What transaction- **Buy** - Purchase of cryptocurrency
- **Sell** - Sale of cryptocurrency
- **Transfer** - Transfer between wallets/exchanges
- **Convert/Swap** - Exchange between cryptocurrencies
- **Reward** - Mining/staking rewards
- **Fee** - Transaction fees

### How are Swaps/Converts handled?

When exchanging (e.g., ETH → SOL), two transactions are created:
- A "sell" of ETH
- A "buy" of SOL

This ensures correct GAV calculation.

### What if there are incorrect transactions?

Use the web interface to:
1. View transactions for a year
2. Identify incorrect entries
3. Contact support for correction

## Troubleshooting

### "No transactions found"

Verify:
1. You have imported transactions: `kryptoskatt import --file ...`
2. The year is correct (transactions exist for that year)

### Database Errors

Ensure:
1. PostgreSQL is running: `docker-compose ps`
2. DATABASE_URL is correct in .env

### Blockchain API Errors

Verify:
1. ETHERSCAN_API_KEY is set in .env (for Ethereum)
2. SOLSCAN_API_KEY is set in .env (for Solana)

## Support

For bug reports or questions, create an issue on GitHub.
