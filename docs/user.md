# KryptoSkatt - User Guide (English)

KryptoSkatt calculates capital gains and losses on crypto assets under Swedish tax rules and prepares the figures for form K4 (section D) and T2. It uses the average cost method (*genomsnittsmetoden*, GAV).

> KryptoSkatt is a calculation aid, not tax advice. You are responsible for your own tax return. See the in-app pages **Terms** (`/villkor`), **Privacy policy** (`/integritet`) and **How we calculate** (`/om-berakningen`).

The full, more detailed guide is in Swedish: [`anvandare.md`](anvandare.md). Running your own public instance? See the administrator guide [`drift.md`](drift.md) (Swedish).

## Getting started

```bash
cp .env.example .env      # set SECRET_KEY, OPERATOR_NAME, OPERATOR_CONTACT
docker compose up -d      # migrations run automatically
```

Open `http://localhost:8000`. No API keys are needed to start.

## Your account

- Click **Create anonymous account** after accepting the terms. You never enter a name, e-mail or password.
- Your account ID (`word-word-word-word-NNNN`) is shown **once**, also as a QR code. It is your only key and cannot be recovered.
- Sessions last 30 days after the last use. Accounts unused for 24 months are deleted automatically.

## The flow

The menu follows the steps: **Overview · 1 Wallets · 2 Import · 3 Calculate**, with the rest under **More**.

1. **Wallets**: add your *public* addresses (never private keys or seed phrases). For Bitcoin you can add an xpub/ypub/zpub.
2. **Import**: click *Fetch on-chain*, then upload CSV exports from each exchange you used (Coinbase, Binance, Kraken, KuCoin, Bybit, Bitstamp, OKX, Gate.io, MEXC, Crypto.com, Ledger Live, and more; the format is auto-detected; max 20 MB).
3. **Calculate**: keep the default **All years**.
4. **Review**: open a year to see the K4 summary, the 70 % loss rule, T2 income and flagged issues.
5. **File**: download the SRU files for Skatteverket's file upload, or copy the figures to K4 section D.

## Which chains need an API key?

| Chain | Source | Key |
|---|---|---|
| Bitcoin (incl. xpub) | Blockstream | none |
| Ethereum, Base, Arbitrum, Polygon | Blockscout (Etherscan if a key exists) | none |
| XRP, Kadena | XRPL cluster, Chainweb | none |
| BNB Smart Chain | Etherscan | free `ETHERSCAN_API_KEY` |
| Solana | Helius / Solscan | free `HELIUS_API_KEY` |
| TRON, VeChain, Peaq | Tronscan, VeChainStats, Subscan | free key |

Keys can be set by the operator in `.env` or by you under **More → Settings → API keys**. Your own keys are stored encrypted and apply only to your account.

## How the tax is calculated

- All units of the same asset form **one pool across all your wallets and exchanges**.
- **Selling, swapping and paying** with crypto are disposals. A transfer to someone else is a disposal at market value.
- **Moving between your own wallets** is not a disposal. The cost basis carries over unchanged. Units lost as network fee leave the pool, but their cost stays with the remaining units.
- **Losses** are deductible at 70 %. The year page shows gains, losses, the deductible part and the net figure.
- **Rewards** (staking, mining, airdrops) are income at market value when received, and that value becomes their cost basis.
- **Prices**: your own manual price (private to your account), then the implied swap price, then CoinGecko, Binance and Kraken, converted to SEK at Riksbanken's rate. A missing price counts as 0 SEK and is flagged.

## Privacy and your data

- Only necessary cookies (session, language). No trackers, no third-party scripts or fonts.
- **Export** all your data as JSON: **Settings → Export your data**.
- **Delete** your account and everything linked to it: **Settings → Delete account**.
- When fetching on-chain data, the *server* sends your addresses to the source listed above; your IP address is not sent.

## CLI

```bash
kryptoskatt import --file export.csv            # platform auto-detected
kryptoskatt wallet add --address 0x... --chain ETHEREUM
kryptoskatt fetch --all
kryptoskatt calculate 2024
kryptoskatt report 2024 --format csv
kryptoskatt report 2024 --format sru --personnummer YYYYMMDDNNNN --namn "First Last"
kryptoskatt purge-inactive                      # operator: remove idle accounts
```

## Troubleshooting

- **Nothing on the overview**: follow the step marked as next.
- **On-chain fetch returns nothing**: the result message names any missing key. Check that the address is marked as *mine*.
- **Wrong or missing price**: add a manual price under **More → Prices** and calculate again.
- **Negative balance**: purchases are missing. Import older history until the balance is correct.

Bug reports: GitHub issues. Security issues: see `SECURITY.md`.
