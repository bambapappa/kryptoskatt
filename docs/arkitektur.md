# KryptoSkatt — Arkitektur

## Systemöversikt

KryptoSkatt är en flerskiktsapplikation för svensk kryptoskatteberäkning. Arkitekturen är uppdelad i tydliga ansvarsdomäner som kan anropas via CLI, webb-UI eller REST API.

```
┌─────────────────────────────────────────────────────────┐
│  Gränssnitt                                              │
│  CLI (Typer)  ·  Webb-UI (FastAPI+Jinja2)  ·  REST API  │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│  Servicelagret                                           │
│  AuthService · WalletService · PriceService             │
│  AddressValidator · RateLimiter · RiksbankService       │
└───────────────────────┬─────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌───────────┐   ┌───────────────┐   ┌──────────────────┐
│  Parsers  │   │ Chain Adapters│   │  Engine          │
│ (CSV/TSV) │   │ (on-chain API)│   │  Dedup · Match   │
└─────┬─────┘   └──────┬────────┘   │  GAV · Prices    │
      │                │            └────────┬─────────┘
      └────────────────┘                     │
                        │                    │
┌───────────────────────▼────────────────────▼───────────┐
│  Databas (PostgreSQL via SQLAlchemy)                    │
│  Transactions · Wallets · Disposals · GavLedger        │
│  Accounts · Sessions · PriceCache (delad) · ManualPrice │
│  (per konto) · TransferLinks · ShareLinks · ApiKeys     │
└─────────────────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│  Rapporter                                               │
│  K4 · T2 · Audit · GavHistory · NetPosition · Issues   │
└─────────────────────────────────────────────────────────┘
```

---

## Dataflöde

### Steg 1 — Import

Transaktioner kan komma in på två sätt:

**CSV/TSV-import** (manuell börsexport):
```
Fil → Parser.parse(path) → list[TransactionCreate] → Transaction-rader i DB
```

Parsers normaliserar till gemensamma fält: `timestamp_utc` (UTC), `base_coin`, `base_amount` (Decimal), `event_type` (EventType-enum).

**On-chain-hämtning** (automatisk):
```
WalletService.get_my_addresses()
    → ChainRegistry.get_adapter(chain)
    → ChainAdapter.fetch_transactions(address, chain)
    → list[TransactionCreate]
    → save_fetched_transactions() → DB
```

Varje adapter implementerar `base.BlockchainAdapter` med metoderna `supported_chains()` och `fetch_transactions()`.

### Steg 2 — Avduplicering

`DeduplicationEngine` markerar dubbletter med `Transaction.is_duplicate = True`.

**Strategi:**
1. Exakt `tx_hash`-matchning (hög konfidens)
2. Heuristisk matchning: samma `base_coin`, `base_amount`, `event_type` och `timestamp_utc` inom ±60 sekunder

Dubbletter ingår fortfarande i DB men exkluderas från beräkning och rapporter.

### Steg 3 — Prisberikning

`PriceEnrichmentEngine` hämtar saknade SEK-priser för alla transaktioner utan `price_sek`.

**Fallback-ordning:**
1. `ManualPrice`: kontots egna priser (tabellen `manual_prices`, migration 017). Syns aldrig för andra konton.
2. Swap-implicit pris (samma `tx_hash`, andra benets värde).
3. `PriceCache`: delad cache med publika priser (CoinGecko, operatörens `PriceHistory`-import). Användare kan inte skriva hit direkt.
4. CoinGecko API → Binance/Kraken publika OHLC → CoinAPI (om nyckel finns).
5. Riksbanken API för USD→SEK.

Saknas pris efter detta blir `price_sek` NULL. Händelsen räknas då med 0 kr och flaggas.

### Steg 4 — Transfermatchning

`TransferMatcher` kopplar samman `TRANSFER_OUT` med `TRANSFER_IN` via `TransferLink`.

**Matchningsmetoder (i prioritetsordning):**
1. `TX_HASH` — identisk tx-hash (inter-kedja ej möjligt, men intra-kedja)
2. `AMOUNT_TIME` — samma mynt, belopp inom 0,01 % och tidsfönster ≤24h
3. `MANUAL` — användaren kopplar manuellt via UI/API

En olänkad `TRANSFER_OUT` behandlas som avyttring till marknadspris vid GAV-beräkning. En `TransferLink` med `tx_in_id = NULL` ("Till egen plånbok") betyder att mottagaren är egen men inte spåras. Enheterna ligger då kvar i poolen.

### Steg 5 — GAV-beräkning

`GavEngine` implementerar genomsnittsmetoden (GAV = genomsnittligt anskaffningsvärde).

Poolen är gemensam per mynt över **alla** plånböcker och börser (IL 48 kap. 7 §).

**Algoritm per mynt:**
```
För varje transaktion i kronologisk ordning:

BUY / SWAP_IN / REWARD / olänkad TRANSFER_IN:
    total_kostnad += belopp × pris_sek (+ avgift i SEK eller samma mynt)
    total_enheter += belopp

SELL / SWAP_OUT / olänkad TRANSFER_OUT:
    kostnadsbas = sålda_enheter × GAV
    vinst_förlust = intäkt_sek − avgift_sek − kostnadsbas
    → Disposal-rad
    total_enheter −= sålda_enheter; total_kostnad −= kostnadsbas
    (om total_enheter == 0: total_kostnad = 0)

Länkad TRANSFER_OUT/IN (egen plånbok, IL 44 kap. 3 §: ingen avyttring):
    total_kostnad oförändrad
    total_enheter −= max(skickat − mottaget, 0)   # nätverksavgift i myntet
    # avgiftens anskaffningsvärde stannar på återstående enheter

FEE (fristående): total_kostnad −= avgift_sek (ej under 0)
```

DEX-swappar känns igen i minnet: samma `tx_hash` med TRANSFER_OUT av mynt A och TRANSFER_IN av mynt B klassas om till SWAP_OUT/SWAP_IN.

**Rapportering:** K4 avsnitt D. `K4Report.deductible_losses = 0,70 × total_losses` och `net_taxable = total_gains − deductible_losses`.

**Sorteringsregel vid identiska tidsstämplar:** Förvärv (BUY/SWAP_IN/REWARD) sorteras före avyttringar (SELL/SWAP_OUT) för att undvika negativa saldon.

Alla beräkningar görs med `Decimal` med 18 decimaler — aldrig `float`.

---

## Domänmodell

```
Account (1) ─── (N) UserSession
    │
    ├── (N) Wallet
    │
    ├── (N) ImportBatch ─── (N) Transaction
    │                               │
    │                    ┌──────────┤
    │                    ▼          ▼
    │             TransferLink    price_sek
    │
    ├── (N) Disposal ──── (1) Transaction (säljhändelsen)
    │
    ├── (N) GavLedger
    │
    ├── (N) T2ManualEntry
    │
    ├── (N) CoinBlacklist
    │
    ├── (N) ManualPrice
    │
    ├── (N) AccountApiKey (krypterad)
    │
    ├── (N) ShareLink (hashad token)
    │
    └── (N) CustomChainConfig (krypterad API-nyckel)
```

### Nyckelmodeller

**Transaction** — en atomär händelse:
- `event_type`: `BUY | SELL | SWAP_IN | SWAP_OUT | TRANSFER_IN | TRANSFER_OUT | REWARD | FEE`
- `base_coin`, `base_amount`: primär tillgång
- `quote_coin`, `quote_amount`: motpart (vid köp/sälj)
- `fee_coin`, `fee_amount`: transaktionsavgift
- `price_sek`: SEK-värde per enhet vid tidpunkten
- `is_duplicate`: flaggad av DeduplicationEngine

**Disposal** — en skattepliktig händelse:
- Skapas av GavEngine för varje SELL/SWAP_OUT/olänkad TRANSFER_OUT
- `proceeds_sek`: intäkt
- `cost_basis_sek`: GAV × antal enheter
- `gain_loss_sek`: proceeds − cost_basis

**GavLedger** — bokföring av GAV-tillstånd:
- En rad per händelse som påverkar GAV för ett mynt
- `total_amount` / `total_cost_sek`: saldo och total kostnad efter händelsen
- `gav_per_unit_sek`: genomsnittspris efter händelsen

---

## Autentisering & multi-tenancy

```
Begäran
    │
    ▼
Cookie 'kryptoskatt_session' extraheras
    │
    ▼
UserSession-tabell → account_id → Account.id (= user_id)
    │
    ▼
Alla DB-queries filtrerar på user_id
(Wallet.user_id, Transaction.user_id, Disposal.user_id, ...)
```

**Konton:**
- Identifieras av ett slumpmässigt `account_id` på formatet `ord-ord-ord-ord-NNNN` (1024 ord, ~2^53 kombinationer; äldre konton har 3 ord)
- Ingen e-post, inget lösenord, inget namn
- Sessioner gäller 30 dagar och förnyas vid användning. Bara SHA-256-hash av token lagras.
- Inloggningsförsök begränsas per IP (10/min) och globalt (200 misslyckade/min). Klient-IP tas från `request.client`, som uvicorn bara skriver om för proxys i `FORWARDED_ALLOW_IPS`.
- Nytt konto-ID visas i POST-svaret (`Cache-Control: no-store`) och läggs aldrig i en URL.

**Isolation:**
- Varje tabell med kontodata har en `user_id`- eller `account_id`-kolumn (FK → accounts.id).
- Isoleringen bygger på att varje fråga filtrerar på kontot. Det finns inget automatiskt skydd, så ny kod måste göra samma sak.
- `tests/test_multi_tenant_isolation.py`, `tests/test_account_deletion.py` och `tests/test_web.py` verifierar isolering, fullständig radering och att "hämta om" bara rör det egna kontot.

**Radering och export (GDPR):**
- `services/account_deletion.py` innehåller `OWNED_TABLES`, den enda listan över tabeller med kontodata. Den används av webb och API för radering (art. 17) och export (art. 15/20). Ett test fallerar om en ny tabell med ägarkolumn saknas i listan.
- `purge_inactive_accounts()` raderar konton som inte använts på `INACTIVE_ACCOUNT_MONTHS`.

**Övrigt skydd:**
- SSRF: användarstyrda explorer-URL:er måste vara publika `https`-adresser (`utils/url_safety.py`), kontrolleras både när de sparas och när de hämtas.
- Hemligheter krypteras med Fernet (nyckel härledd ur `SECRET_KEY`). Utan `SECRET_KEY` vägras lagring.
- Uppladdningar begränsas till 20 MB (`utils/uploads.py`).
- CSP utan externa källor. Inga tredjepartsskript eller typsnitt.

---

## Chain Adapter-system

```python
class BlockchainAdapter(ABC):
    def supported_chains(self) -> list[str]: ...
    def fetch_transactions(self, address: str, chain: str) -> list[TransactionCreate]: ...
```

**ChainRegistry** är ett enkelt `dict[str, BlockchainAdapter]`. Nycklar är kedjans namn i versaler (t.ex. `"ETHEREUM"`).

**Anpassade kedjor** (`CustomChainConfig`):
- Användaren definierar en ny kedja med adapter-typ (`blockscout` eller `etherscan`), Explorer URL och native coin
- `get_registry_for_user(session, account_id)` bygger en per-konto-registry som inkluderar anpassade adapters

**Nyckelfri drift:** `missing_api_key(chain, effective_keys)` avgör om en kedja kan hämtas. ETH/Base/Arbitrum/Polygon använder publika Blockscout-instanser (`KEYLESS_EVM_CONFIG`) när ingen Etherscan-nyckel finns. BNB, Solana, TRON, VeChain och Peaq kräver gratisnycklar. Nycklar löses per konto: kontots egen nyckel före instansens.

**Solana-fallback:**
```
Helius API → miss → Solscan API
```

---

## Cachning & prestanda

**PriceCache** (databas, delad mellan konton):
- Historiska dagspriser från publika källor lagras efter första hämtning
- Lookup med index på (coin, date)
- Manuella priser ligger i `manual_prices` per konto, aldrig här

**GAV-batch-insättningar:**
- GavEngine samlar `_pending_ledger` och `_pending_disposals` under beräkning
- Skriver allt i ett enda `session.add_all()` + `commit()` — eliminerar N+1-problemet

**Transaktionsindex:**
```sql
CREATE INDEX ix_transactions_user_id_timestamp ON transactions (user_id, timestamp_utc);
CREATE INDEX ix_transactions_tx_hash ON transactions (tx_hash);
CREATE INDEX ix_transactions_base_coin ON transactions (base_coin, timestamp_utc);
CREATE INDEX ix_disposals_user_id_tax_year ON disposals (user_id, tax_year);
CREATE INDEX ix_gav_ledger_coin_ts ON gav_ledger (coin, timestamp_utc);
```

---

## Konfiguration

`config.py` exponerar ett `Settings`-objekt via `pydantic-settings`. Alla värden läses från miljövariabler eller `.env`-fil. Singleton importeras direkt: `from kryptoskatt.config import settings`.

Inga hårdkodade värden någonstans — alla externa URL:er, nycklar och flaggor är konfigurerbara.

---

## Deployment

### Produktion (Docker)

```
docker compose up -d
    │
    ├── postgres:18-alpine (DB, POSTGRES_IMAGE kan pinna äldre major)
    │
    └── app (multi-stage Dockerfile, Python 3.13)
            │
            ├── alembic upgrade head          (vid uppstart)
            ├── kryptoskatt purge-inactive    (vid uppstart)
            │
            └── uvicorn --workers ${WEB_CONCURRENCY:-1} --proxy-headers
                        --forwarded-allow-ips ${FORWARDED_ALLOW_IPS} --no-access-log
```

**Dockerfile-mönster:**
- Multi-stage build (builder → production)
- Non-root-användare (`appuser`)
- Healthcheck via `/health`
- PriceHistory monteras som read-only volym

### Lokal utveckling

```bash
pip install -e ".[dev]"
kryptoskatt serve --reload   # auto-reload vid filändring
```

---

## Teststruktur

```
tests/
├── conftest.py                   # make_test_account(), DB-fixtures
├── test_gav.py                   # GAV-beräkningslogik
├── test_transfers.py             # Transfermatchning
├── test_dedup.py                 # Avduplicering
├── test_web.py                   # Webb-UI (HTML-endpoints)
├── test_api_wallets.py           # REST API plånböcker
├── test_api_account.py           # GDPR export/deletion
├── test_multi_tenant_isolation.py# Tenant-isolation
├── test_address_validator.py     # Adressvalidering
├── test_riksbank.py              # SEK-kurshämtning
├── test_rate_limiter*.py         # Rate limiting
├── test_schema_validators.py     # Pydantic-schemas
├── test_account_deletion.py      # GDPR-radering/export, manuella priser per konto
├── test_url_safety.py            # SSRF-skydd
├── test_integration_tax_flow.py  # Full pipeline-test
├── test_smoke.py                 # Grundläggande rök-test
└── fixtures/                     # Exempelfiler för parsertester
```

Alla tester kör mot SQLite in-memory (`:memory:`). Asynkrona tester med `asyncio_mode = "auto"`.
