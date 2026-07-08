# KryptoSkatt

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/Bambapappa/kryptoskatt/actions/workflows/ci.yml/badge.svg)](https://github.com/Bambapappa/kryptoskatt/actions/workflows/ci.yml)

**Svensk kryptoskattekalkylator** — beräknar kapitalvinster och -förluster enligt genomsnittsmetoden (GAV) och genererar underlag för K4- och T2-blanketterna.

> **Ansvarsfriskrivning:** KryptoSkatt är ett hjälpverktyg. Det ersätter inte professionell skatterådgivning. Kontrollera alltid dina uppgifter mot Skatteverkets aktuella regler innan du lämnar in din deklaration.

---

## Funktioner

| Område | Vad som stöds |
|---|---|
| **Importer** | Coinbase, Coinbase Advanced Trade, Crypto.com, MEXC, Binance, KuCoin, Kraken, Bybit, Bitstamp, OKX, Gate.io, Ledger Live, manuell swap-CSV |
| **On-chain-hämtning** | Ethereum, Polygon, BNB Smart Chain, Base, Arbitrum (Etherscan), Solana (Helius/Solscan), Bitcoin (Blockstream), TRON, VeChain, Peaq/Substrate, XRP, Kadena, anpassade Blockscout-kedjor |
| **Beräkning** | GAV (genomsnittsmetoden) per mynt, avduplicering, transfermatchning, prisberikning (CoinGecko → Binance/Kraken OHLC → CoinAPI, växlas till SEK via Riksbanken) |
| **Rapporter** | K4-underlag (CSV/JSON/HTML), **SRU-export för Skatteverket** (avsnitt D), T2-inkomstrapport, **år-till-år GAV-överföring**, revisionsunderlag, GAV-historik, nettopositoner, **skrivskyddad delningslänk till revisor**, datakvalitetsflaggor |
| **Gränssnitt** | Webb-UI (FastAPI + Jinja2, svenska/engelska) · REST API (`/api/v1/`) · CLI |
| **Säkerhet** | Anonyma konton (inga personuppgifter), HttpOnly-sessionscookies, hashade sessionstokens, rate limiting på inloggning, multi-tenant-isolation |

---

## Snabbstart med Docker

```bash
# 1. Klona och kopiera miljöfil
git clone <repo>
cd crypto
cp .env.example .env
# Fyll i DATABASE_URL och API-nycklar i .env

# 2. Starta
docker-compose up -d

# 3. Öppna i webbläsaren
open http://localhost:8000
```

Migrationer körs automatiskt vid uppstart.

---

## Installation för utveckling

**Krav:** Python 3.12+, PostgreSQL 14+ (Docker-imagen kör Python 3.13 och composen Postgres 18)

> **Uppgradering till Postgres 18:** en ny major-version startar inte på en gammal datakatalog. Vill du inte migrera databasen nu — sätt `POSTGRES_IMAGE=postgres:16-alpine` (din nuvarande major) i `.env` så rörs inte volymen; app-migrationerna fungerar ändå. Vill du faktiskt gå till 18: ta en dump först (`docker compose exec db pg_dump -U kryptoskatt kryptoskatt > backup.sql`), ta bort `pgdata`-volymen, starta på 18 och återställ.

```bash
# Skapa virtuell miljö och installera
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Miljöfil
cp .env.example .env
# Redigera .env med databasanslutning

# Kör migrationer
alembic upgrade head

# Starta webb
kryptoskatt serve --host 0.0.0.0 --port 8000
```

---

## Miljövariabler

Alla inställningar sätts via `.env` eller miljövariabler (se `.env.example` för komplett lista):

```env
# Obligatorisk
DATABASE_URL=postgresql://user:pass@localhost:5432/kryptoskatt

# API-nycklar för on-chain-hämtning
ETHERSCAN_API_KEY=      # ETH, Polygon, BNB, Base, Arbitrum
HELIUS_API_KEY=         # Solana (rekommenderas)
SOLSCAN_API_KEY=        # Solana (reserv)
COINGECKO_API_KEY=      # Historiska priser

# Säkerhet
COOKIE_SECURE=true      # false vid lokal HTTP-utveckling
CORS_ORIGINS=["https://yourdomain.com"]

# Övrigt
LOG_LEVEL=INFO
DEBUG_MODE=false
PRICE_HISTORY_DIR=PriceHistory
```

---

## Kommandon (CLI)

```bash
kryptoskatt --help

# Importera CSV-fil
kryptoskatt import --file export.csv
kryptoskatt import --file export.csv --platform coinbase

# Hämta on-chain-transaktioner
kryptoskatt fetch --all                    # Alla registrerade plånböcker
kryptoskatt fetch --address 0x... --chain ETHEREUM

# Beräkna skatt för ett år
kryptoskatt calculate 2024

# Generera rapporter
kryptoskatt report 2024                    # K4 till stdout
kryptoskatt report 2024 --format csv --output-dir ./rapporter
# SRU-filer för Skatteverkets e-inlämning (INFO.SRU + BLANKETTER.SRU)
kryptoskatt report 2024 --format sru --personnummer ÅÅÅÅMMDDNNNN --namn "För Efternamn"
# År-till-år GAV-överföring (ingående/utgående balans per mynt)
kryptoskatt report 2024 --format carryover

# Starta webbserver
kryptoskatt serve --host 0.0.0.0 --port 8000

# Kontrollera datakvalitet
kryptoskatt issues 2024

# Hantera plånböcker
kryptoskatt wallet add --address 0x... --chain ETHEREUM --label "Metamask"
kryptoskatt wallet list
kryptoskatt wallet remove --address 0x...
kryptoskatt wallet add-xpub zpub6r...        # härled alla Bitcoin-adresser från xpub/ypub/zpub
```

---

## REST API

Bas-URL: `http://localhost:8000/api/v1`

Autentisering via sessionscookie (`kryptoskatt_session`).

```bash
# Hälsokontroll (ingen auth)
curl http://localhost:8000/api/v1/health

# Skapa konto
curl -X POST http://localhost:8000/api/v1/auth/account

# Logga in (sparar cookie)
curl -X POST http://localhost:8000/api/v1/auth/session \
  -H "Content-Type: application/json" \
  -d '{"account_id": "ord-ord-ord-NNNN"}' \
  -c cookies.txt
```

Komplett API-referens: [`docs/api.md`](docs/api.md)

---

## Dataflöde

```
CSV/TSV / Blockchain-API
         │
    [Parsers / Chain Adapters]
         │
    [Transaction DB]
         │
    ┌────┼────┐
[Dedup] [Match] [Priser]
         │
    [GAV-motor]
         │
   [Disposals + GAV Ledger]
         │
    [K4] [T2] [Audit]
```

Se [`docs/arkitektur.md`](docs/arkitektur.md) för fullständig beskrivning.

---

## Tester

```bash
pytest                           # Alla 600+ tester
pytest tests/test_gav.py         # Enskild fil
pytest --cov=kryptoskatt         # Med täckning
ruff check src/                  # Lint
mypy                             # Typkontroll (kärnan)
```

---

## Docker

```bash
docker-compose up -d
docker-compose exec app kryptoskatt calculate 2024

# Importera fil i container
docker cp export.csv kryptoskatt-app:/tmp/
docker-compose exec app kryptoskatt import --file /tmp/export.csv
```

---

## Plattformar

### Börser (CSV-import)

| Plattform | Platform-ID | Kommentar |
|---|---|---|
| Bitstamp | `bitstamp` | Transaktionsexport (v1 och v2) |
| Coinbase | `coinbase` | Standardexport |
| Coinbase Advanced Trade | `coinbase_advanced` | Fill statements |
| Crypto.com | `crypto_com` | |
| MEXC | `mexc` | Inkl. handelsavgifter |
| Binance | `binance` | Handelshistorik |
| KuCoin | `kucoin` | |
| Gate.io | `gateio` | Kontoutdrag ("my bill") |
| Kraken | `kraken` | Ledger-export |
| Bybit | `bybit` | |
| Ledger Live | `ledger` | NFT-filtrering |
| OKX | `okx` | Handels- och funding-utdrag |
| Manuell swap | `manual_swap` | Eget CSV-format |
| NFT-liggare | `nft` | Eget CSV-format för NFT-köp/-försäljning (se nedan) |

#### NFT-liggare (`nft`)

NFT:er kan inte prissättas automatiskt, så köp- och säljbelopp anges i SEK.
Varje NFT blir en unik tillgång (`NFT:<samling>#<token-id>`) som går genom
genomsnittsmetoden och hamnar på K4 (avsnitt D) precis som annan krypto.

```csv
date,action,collection,token_id,chain,amount_sek,fee_sek,tx_hash,notes
2024-03-01,BUY,Bored Apes,1234,ETHEREUM,50000,500,0xabc,mint
2024-09-15,SELL,Bored Apes,1234,ETHEREUM,120000,1000,0xdef,
```

`action` är `BUY`/`MINT`, `SELL`, `TRANSFER_IN` eller `TRANSFER_OUT`.
`amount_sek` är NFT:ns totala pris; `fee_sek` läggs till omkostnaden vid köp
och dras från försäljningspriset vid sälj.

### On-chain (automatisk hämtning)

| Kedja | API-nyckel behövs |
|---|---|
| Ethereum / Polygon / BNB / Base / Arbitrum | `ETHERSCAN_API_KEY` |
| Solana | `HELIUS_API_KEY` |
| Bitcoin | — (Blockstream) |
| TRON | `TRONSCAN_API_KEY` |
| VeChain | `VECHAINSTATS_API_KEY` |
| Peaq / Substrate | `SUBSCAN_API_KEY` |
| XRP | — (XRPL.org) |
| Kadena | — (Chainweb) |
| Anpassad kedja | Konfigureras via inställningar |

---

## Bidra

Bidrag välkomnas! Se [`CONTRIBUTING.md`](CONTRIBUTING.md) för hur du sätter upp dev-miljön, lägger till parsers/kedjor och skapar pull requests.

Säkerhetsproblem rapporteras privat via [GitHub Security Advisories](../../security/advisories/new) — se [`SECURITY.md`](SECURITY.md).

---

## Licens

[Apache 2.0](LICENSE) — fri att använda, modifiera och distribuera, med uttryckligt patentskydd. Se även [`NOTICE`](NOTICE).
