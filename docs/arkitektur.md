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
│  Accounts · Sessions · PriceCache · TransferLinks      │
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
1. Lokal databas (`PriceCache`) — från manuell CSV-import eller tidigare hämtning
2. CoinGecko API (historiska dagspriser)
3. Riksbanken API — för USD→SEK-konvertering

### Steg 4 — Transfermatchning

`TransferMatcher` kopplar samman `TRANSFER_OUT` med `TRANSFER_IN` via `TransferLink`.

**Matchningsmetoder (i prioritetsordning):**
1. `TX_HASH` — identisk tx-hash (inter-kedja ej möjligt, men intra-kedja)
2. `AMOUNT_TIME` — samma mynt, belopp inom 0,01 % och tidsfönster ≤24h
3. `MANUAL` — användaren kopplar manuellt via UI/API

En olänkad `TRANSFER_OUT` behandlas som skattepliktig avyttring vid GAV-beräkning.

### Steg 5 — GAV-beräkning

`GavEngine` implementerar genomsnittsmetoden (GAV = genomsnittligt anskaffningsvärde).

**Algoritm per mynt:**
```
För varje transaktion i kronologisk ordning:

BUY / SWAP_IN / TRANSFER_IN / REWARD:
    ny_total_kostnad = (gammalt_saldo × gammalt_GAV) + (nytt_belopp × pris_sek)
    ny_total_enheter = gammalt_saldo + nytt_belopp
    nytt_GAV = ny_total_kostnad / ny_total_enheter

SELL / SWAP_OUT / olänkad TRANSFER_OUT:
    kostnadsbas = sålda_enheter × nuvarande_GAV
    vinst_förlust = intäkt_sek − kostnadsbas
    → skapar Disposal-rad
    ny_total_enheter = gammalt_saldo − sålda_enheter
    (om ny_total_enheter == 0: GAV nollställs)
```

**Sortерingsregel vid identiska tidsstämplar:** Förvärv (BUY/SWAP_IN/REWARD) sorteras före avyttringar (SELL/SWAP_OUT) för att undvika negativa saldon.

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
    └── (N) CustomChainConfig
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
- `running_balance`: saldo efter händelsen
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
- Identifieras av ett slumpmässigt genererat `account_id` på formatet `ord-ord-ord-NNNN`
- Inga personuppgifter — ingen e-post, inget lösenord, inget namn
- Sessions är 30 dagar, förnyas vid användning

**Isolation:**
- Varje databasmodell har en `user_id`-kolumn (FK → accounts.id)
- Queries utan `user_id`-filter blockeras av auth middleware
- Tester verifierar att konto A aldrig kan se konto B:s data

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

**Solana-fallback:**
```
Helius API → miss → Solscan API
```

---

## Cachning & prestanda

**PriceCache** (databas):
- Historiska dagspriser lagras i DB efter första hämtning
- Lookup O(1) med index på (coin, date)

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
docker-compose up -d
    │
    ├── postgres:16-alpine (DB)
    │
    └── app (multi-stage Dockerfile)
            │
            ├── alembic upgrade head    (vid uppstart)
            │
            └── uvicorn --workers 2     (8000/tcp)
```

**Dockerfile-mönster:**
- Multi-stage build (builder → production)
- Non-root-användare (`appuser`)
- Healthcheck via `/api/v1/health`
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
├── test_integration.py           # Full pipeline-test
├── test_smoke.py                 # Grundläggande rök-test
└── fixtures/                     # Exempelfiler för parsertester
```

Alla tester kör mot SQLite in-memory (`:memory:`). Asynkrona tester med `asyncio_mode = "auto"`.
