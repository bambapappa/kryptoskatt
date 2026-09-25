# KryptoSkatt

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/Bambapappa/kryptoskatt/actions/workflows/ci.yml/badge.svg)](https://github.com/Bambapappa/kryptoskatt/actions/workflows/ci.yml)

**Svensk kryptoskattekalkylator** — beräknar kapitalvinster och -förluster enligt genomsnittsmetoden (GAV) och genererar underlag för K4- och T2-blanketterna.

> **Ansvarsfriskrivning:** KryptoSkatt är ett hjälpverktyg. Det ersätter inte professionell skatterådgivning. Kontrollera alltid dina uppgifter mot Skatteverkets aktuella regler innan du lämnar in din deklaration. Appen har användarvillkor (`/villkor`), integritetspolicy (`/integritet`) och en metodbeskrivning (`/om-berakningen`). Texterna bör granskas av en jurist innan en publik instans lanseras.

---

## Funktioner

| Område | Vad som stöds |
|---|---|
| **Importer** | Coinbase, Coinbase Advanced Trade, Crypto.com, MEXC, Binance, KuCoin, Kraken, Bybit, Bitstamp, OKX, Gate.io, Ledger Live, manuell swap-CSV |
| **On-chain-hämtning** | **Utan nyckel:** Bitcoin inkl. xpub (Blockstream), Ethereum/Base/Arbitrum/Polygon (Blockscout), XRP, Kadena. **Med gratisnyckel:** BNB (Etherscan), Solana (Helius/Solscan), TRON, VeChain, Peaq/Substrate. Anpassade Blockscout-/Etherscan-kedjor |
| **Beräkning** | GAV (genomsnittsmetoden) med gemensam pool över alla plånböcker, kostnadsneutrala flyttar mellan egna plånböcker, 70 %-regeln för förluster (K4 avsnitt D), avduplicering, transfermatchning, prisberikning (eget pris → swap-implicit → CoinGecko → Binance/Kraken → CoinAPI, till SEK via Riksbanken) |
| **Rapporter** | K4-underlag (CSV/JSON/HTML), **SRU-export för Skatteverket** (avsnitt D), T2-inkomstrapport, **år-till-år GAV-överföring**, revisionsunderlag, GAV-historik, nettopositoner, **skrivskyddad delningslänk till revisor**, datakvalitetsflaggor |
| **Gränssnitt** | Webb-UI (FastAPI + Jinja2, svenska/engelska) · REST API (`/api/v1/`) · CLI |
| **Integritet & säkerhet** | Anonyma konton (inget namn, ingen e-post, inget lösenord), bara nödvändiga cookies, inga tredjepartsskript eller externa typsnitt, hashade sessionstokens, krypterade API-nycklar, SSRF-skydd, begränsning av inloggningsförsök per IP och globalt, multi-tenant-isolation, GDPR-export och radering, automatisk radering av inaktiva konton |

---

## Snabbstart med Docker

```bash
# 1. Klona och kopiera miljöfil
git clone https://github.com/bambapappa/kryptoskatt.git
cd kryptoskatt
cp .env.example .env
# Sätt minst POSTGRES_PASSWORD/DATABASE_URL, SECRET_KEY, OPERATOR_NAME, OPERATOR_CONTACT

# 2. Starta
docker compose up -d

# 3. Öppna i webbläsaren
open http://localhost:8000
```

Migrationer och rensning av inaktiva konton körs automatiskt vid uppstart. Inga API-nycklar krävs för att komma igång.

### Innan en publik instans startas

- [ ] `SECRET_KEY` satt (`openssl rand -hex 32`). Utan den kan användare inte spara API-nycklar.
- [ ] `OPERATOR_NAME` och `OPERATOR_CONTACT` satta. De visas i integritetspolicyn, som GDPR art. 13 kräver.
- [ ] Starkt `POSTGRES_PASSWORD`.
- [ ] HTTPS via reverse proxy och `FORWARDED_ALLOW_IPS` satt till proxyns IP.
- [ ] `CORS_ORIGINS` satt till din domän.
- [ ] Villkor och integritetspolicy granskade av jurist.
- [ ] Säkerhetskopior av databasen (de innehåller användardata och omfattas av raderingskraven).

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

# API-nycklar (alla valfria, gratisnivåer räcker; användare kan även ange egna)
ETHERSCAN_API_KEY=      # BNB (+ ETH/Polygon/Base/Arbitrum, annars Blockscout utan nyckel)
HELIUS_API_KEY=         # Solana (rekommenderas)
SOLSCAN_API_KEY=        # Solana (reserv)
COINGECKO_API_KEY=      # Historiska priser (demo-nyckel ger högre gränser)

# Säkerhet
COOKIE_SECURE=true      # false vid lokal HTTP-utveckling
CORS_ORIGINS=["https://yourdomain.com"]
SECRET_KEY=             # krypterar användarnas API-nycklar, krävs för att spara dem
FORWARDED_ALLOW_IPS=127.0.0.1  # reverse proxyns IP

# Juridik & integritet
OPERATOR_NAME=          # personuppgiftsansvarig, visas i /integritet och /villkor
OPERATOR_CONTACT=       # kontakt-e-post
INACTIVE_ACCOUNT_MONTHS=24  # radera konton som inte använts så här länge
ACCESS_LOG=false        # HTTP-åtkomstloggar innehåller IP-adresser och delningstoken

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

# Radera konton som inte använts på INACTIVE_ACCOUNT_MONTHS (körs även vid container-start;
# schemalägg gärna dagligen via cron)
kryptoskatt purge-inactive

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
docker compose up -d
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
| Ethereum / Polygon / Base / Arbitrum | — (Blockscout). Etherscan används om `ETHERSCAN_API_KEY` finns |
| BNB Smart Chain | `ETHERSCAN_API_KEY` (gratis) |
| Solana | `HELIUS_API_KEY` (gratis) eller `SOLSCAN_API_KEY` |
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
