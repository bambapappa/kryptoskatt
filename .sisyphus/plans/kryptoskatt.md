# KryptoSkatt — Personligt kryptoskatteberäkningssystem

## TL;DR

> **Quick Summary**: Bygga ett CLI-drivet Python-system som importerar kryptotransaktioner från börs-exporter (Coinbase, Crypto.com, MEXC) och on-chain via blockchain-API:er (15+ adresser, 10+ kedjor), beräknar vinst/förlust per tillgång enligt Skatteverkets GAV-metod, och genererar K4-rapporter per valfritt kalenderår. Enkel webbrapport för att granska resultat.
>
> **Deliverables**:
> - CLI-verktyg (`kryptoskatt`) med kommandon: import, fetch, calculate, report, serve
> - CSV-parsers för Coinbase, Crypto.com, MEXC
> - On-chain transaction fetchers via Etherscan v2, Solscan v2, + generiska chain adapters
> - Adressbok (wallet registry) med kedja + ägare-flagga
> - GAV-beräkningsmotor med full audit trail
> - Prisdata-hämtning via CoinGecko + Riksbanken USD/SEK fallback
> - K4-rapport per kalenderår (CSV + JSON) + fullständig transaktionslista + GAV-historik
> - Enkel FastAPI-webbrapport för att browsa resultat
> - PostgreSQL-lagring med 10-års retention
> - Docker Compose för lokal deploy
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES — 4 waves
> **Critical Path**: Skeleton → DB schema → Parsers + Fetchers → GAV engine → Reports → Web UI

---

## Context

### Original Request
Användaren vill bygga ett personligt system för att deklarera kryptovalutor enligt svenska Skatteverkets regler. Systemet ska ta emot CSV-exporter från börser, hämta on-chain-transaktioner via API:er baserat på wallet-adresser, beräkna vinst/förlust per tillgång med GAV-metoden, och generera K4-underlag per kalenderår. Kritiskt: användaren har *glömt* deklarera 2024 och behöver kunna generera historiska rapporter för självrättelse.

### Interview Summary
**Key Discussions**:
- **Arkitektur**: CLI + enkel webbrapport (inte full SPA). Single-user, ingen auth.
- **Tech stack**: Python, FastAPI, SQLAlchemy, Typer (CLI), PostgreSQL, Docker Compose lokalt.
- **Plattformar**: Börser (Coinbase, Crypto.com, MEXC) + non-custodial wallets (Ledger, Phantom, Trust, VeWallet).
- **Kedjor**: Solana, Ethereum, Ripple, Polygon, Kadena, Tron, VeChain, BNB, PEAQ, Aleo + fler.
- **DePIN rewards**: Geodnet (GEOD), Onocoy, Beamable — dagliga staking/mining-belöningar.
- **Datavolym**: 500–2000 transaktioner totalt, 15+ wallet-adresser.
- **Okänd anskaffning**: 0 SEK som default (Skatteverkets regel).
- **Teststrategi**: TDD för beräkningsmoduler.
- **Rapporter**: K4-summary + full transaktionslista + GAV-historik per coin + flaggade problem.
- **Historiska rapporter**: Måste kunna generera K4 för valfritt år (självrättelse-scenario).

**Research Findings**:
- Skatteverket: GAV-metoden obligatorisk, krypto-till-krypto swap = skattepliktig, transfers ej skattepliktiga, fees inkluderas i omkostnad/avdrag, 70%-förlustavdrag, staking beskattas vid mottagande.
- Etherscan v2: En API-nyckel för 60+ EVM-kedjor (ETH, Polygon, BNB, m.fl.). Free tier 5 calls/sec.
- Solscan v2: Solana-specifikt, kräver API-key.
- CoinGecko: Historiskt pris per datum i SEK. Free tier 5–15 calls/min. Datumbaserat (00:00 UTC).
- MEXC-exporter är TSV med svenska headers (ej standard CSV).

### Metis Review
**Identified Gaps** (addressed):
- **Deduplication risk**: Samma transaktion kan finnas i CSV-export OCH on-chain → dedup-logik med tx_hash som nyckel.
- **CoinGecko rate limits**: 500–2000 unika (coin, datum)-par vid 5–15 calls/min → caching + batching obligatoriskt.
- **DePIN-tokens saknar prisdata**: GEOD/Onocoy/Beamable kanske inte finns på CoinGecko → flagga som "pris saknas" + manuell inmatning.
- **PEAQ är Substrate-kedja**: Inte EVM — kan behöva Subscan API istället för Etherscan.
- **API-nycklar i systemdesign.md**: MÅSTE .env + .gitignore från commit 0.
- **systemdesign.md är referens, inte spec**: Det överenskomna scopet från intervjun gäller.
- **Historiska rapporter**: GAV kumulativ från start, rapporter klipps per kalenderår.

---

## Work Objectives

### Core Objective
Bygga ett CLI-drivet system som samlar in ALL kryptotransaktionsdata (börs-exporter + on-chain), beräknar skatteunderlag med GAV-metoden, och genererar K4-rapporter per valfritt kalenderår — med fokus på korrekthet, spårbarhet och 10-års datalagring.

### Concrete Deliverables
- `kryptoskatt` CLI-verktyg med: `import`, `fetch`, `wallet add/list`, `calculate`, `report`, `serve`
- Parsers: Coinbase CSV, Crypto.com CSV, MEXC TSV (insättning/uttag/handel)
- Chain adapters: Etherscan v2 (ETH + EVM), Solscan v2 (Solana), + generiskt interface
- Adressbok-hantering (wallet registry)
- GAV-beräkningsmotor med disposal-spårning
- Prisdata-service med CoinGecko + cache
- K4-rapport (CSV + JSON) + transaktionslista + GAV-historik
- FastAPI webbrapport
- Docker Compose (PostgreSQL + app)
- Full testsvit (TDD för beräkningar)

### Definition of Done
- [ ] `kryptoskatt import --file coinbase.csv --platform coinbase` → transaktioner i DB
- [ ] `kryptoskatt fetch --all` → hämtar on-chain-transaktioner för alla registrerade wallets
- [ ] `kryptoskatt calculate --year 2024` → GAV-beräkning med K4-summary output
- [ ] `kryptoskatt report --year 2024 --format csv` → K4-fil redo för Skatteverket
- [ ] `kryptoskatt serve` → webbrapport på localhost:8000
- [ ] Alla tests gröna: `pytest --tb=short`
- [ ] Docker Compose: `docker compose up` → fullt fungerande system

### Must Have
- GAV-beräkning som är korrekt enligt Skatteverkets genomsnittsmetod
- Deduplication: samma transaktion från CSV + on-chain räknas bara en gång (tx_hash-baserad)
- Transfer-matchning: egna wallet→wallet flaggas som ej skattepliktiga
- Historisk rapport: K4 för valfritt kalenderår (inte bara innevarande)
- Kumulativ GAV: beräkningen börjar från allra första köpet, oavsett rapportår
- Prisdata i SEK vid transaktionstillfället
- Staking/DePIN rewards beskattas vid mottagande (marknadsvärde i SEK)
- Okänd anskaffning = 0 SEK med tydlig flaggning
- Alla belopp som Decimal (aldrig float) 
- All tid i UTC
- .env för alla API-nycklar och hemligheter — aldrig i kod eller git

### Must NOT Have (Guardrails)
- INGEN auth/login — single-user, lokalt
- INGEN Redis/Celery/queue — synkron CLI-körning
- INGEN full SPA med React/Vue — bara enkel FastAPI + Jinja2 templates
- INGEN realtids-synk via börs-API-nycklar
- INGEN SRU-generator (framtida scope)
- INGEN float-aritmetik för belopp (Decimal only)
- INGA API-nycklar hårdkodade i kod
- INGA "smart" tolkningar av gråzoner (gas fees som avdrag etc.) — konservativ approach
- INGEN over-engineering: inga abstrakta factory patterns, inga generiska plugin-system utöver parser/chain-interface
- INGEN AI-slop: inga överflödiga kommentarer, inga generiska variabelnamn (data/result/item)

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: NO (nytt projekt)
- **Automated tests**: TDD (tests first) för beräkningsmoduler, tests-after för parsers/fetchers
- **Framework**: pytest
- **TDD-moduler**: GAV-engine, disposal-beräkning, transfer-matchning, priskonvertering
- **Tests-after**: CSV-parsers, chain adapters, CLI-kommandon, webb-rapport

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Beräkningslogik**: pytest — kör testsvit, verifiera output
- **CLI-kommandon**: Bash — kör CLI, verifiera stdout/stderr/exit code
- **Parsers**: pytest — kör med fixture-filer, jämför output
- **Webb-rapport**: Playwright — navigera, verifiera data i HTML
- **Docker**: Bash — `docker compose up`, healthcheck, curl endpoints

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — start immediately, all independent):
├── Task 1: Project skeleton + Docker Compose + .env setup [quick]
├── Task 2: Database schema + SQLAlchemy models + Alembic migrations [unspecified-high]
├── Task 3: UnifiedTransaction schema + Decimal types + enums [quick]
├── Task 4: Pytest infrastructure + TDD fixtures [quick]
├── Task 5: Wallet registry (address book) model + CLI commands [quick]

Wave 2 (Data ingestion — after Wave 1, MAX PARALLEL):
├── Task 6: Coinbase CSV parser (depends: 2, 3) [unspecified-high]
├── Task 7: Crypto.com CSV parser (depends: 2, 3) [unspecified-high]
├── Task 8: MEXC TSV parser — insättning/uttag/handel (depends: 2, 3) [unspecified-high]
├── Task 9: Etherscan v2 chain adapter — ETH + EVM chains (depends: 2, 3, 5) [unspecified-high]
├── Task 10: Solscan v2 chain adapter — Solana (depends: 2, 3, 5) [unspecified-high]
├── Task 11: Generic chain adapter interface + registry (depends: 3) [quick]
├── Task 12: CoinGecko price service + caching (depends: 2) [unspecified-high]
├── Task 13: CLI import + fetch commands (depends: 2, 5) [unspecified-high]

Wave 3 (Calculation + reports — after Wave 2):
├── Task 14: Deduplication engine — tx_hash based (depends: 6-10) [deep]
├── Task 15: Transfer matching — own wallet detection (depends: 5, 6-10) [deep]
├── Task 16: GAV calculation engine — TDD (depends: 3, 12, 14, 15) [ultrabrain]
├── Task 17: K4 report generator — per year, per asset (depends: 16) [unspecified-high]
├── Task 18: CLI calculate + report commands (depends: 16, 17) [quick]

Wave 4 (UI + polish — after Wave 3):
├── Task 19: FastAPI web report + Jinja2 templates (depends: 16, 17) [visual-engineering]
├── Task 20: CLI serve command + Docker integration (depends: 19) [quick]
├── Task 21: GAV history tracking + visualization data (depends: 16, 19) [unspecified-high]
├── Task 22: Flagged issues report — missing prices, unknown cost basis, unmatched transfers (depends: 14, 15, 16) [unspecified-high]

Wave FINAL (Verification — after ALL tasks):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA — full pipeline test (unspecified-high)
├── Task F4: Scope fidelity check (deep)

Critical Path: Task 1 → Task 2 → Task 6-10 → Task 14 → Task 16 → Task 17 → Task 19 → F1-F4
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 8 (Wave 2)
```

### Dependency Matrix

| Task | Depends On | Blocks | Wave |
|------|-----------|--------|------|
| 1 | — | 2-5, all | 1 |
| 2 | 1 | 6-10, 12, 13 | 1 |
| 3 | 1 | 6-11, 16 | 1 |
| 4 | 1 | all tests | 1 |
| 5 | 1 | 9, 10, 13, 15 | 1 |
| 6 | 2, 3 | 14, 15 | 2 |
| 7 | 2, 3 | 14, 15 | 2 |
| 8 | 2, 3 | 14, 15 | 2 |
| 9 | 2, 3, 5 | 14, 15 | 2 |
| 10 | 2, 3, 5 | 14, 15 | 2 |
| 11 | 3 | 9, 10 | 2 |
| 12 | 2 | 16 | 2 |
| 13 | 2, 5 | — | 2 |
| 14 | 6-10 | 16 | 3 |
| 15 | 5, 6-10 | 16 | 3 |
| 16 | 3, 12, 14, 15 | 17, 19, 21, 22 | 3 |
| 17 | 16 | 18, 19 | 3 |
| 18 | 16, 17 | — | 3 |
| 19 | 16, 17 | 20, 21 | 4 |
| 20 | 19 | — | 4 |
| 21 | 16, 19 | — | 4 |
| 22 | 14, 15, 16 | — | 4 |
| F1-F4 | ALL | — | FINAL |

### Agent Dispatch Summary

- **Wave 1**: 5 tasks — T1→`quick`, T2→`unspecified-high`, T3→`quick`, T4→`quick`, T5→`quick`
- **Wave 2**: 8 tasks — T6-T8→`unspecified-high`, T9-T10→`unspecified-high`, T11→`quick`, T12→`unspecified-high`, T13→`unspecified-high`
- **Wave 3**: 5 tasks — T14-T15→`deep`, T16→`ultrabrain`, T17→`unspecified-high`, T18→`quick`
- **Wave 4**: 4 tasks — T19→`visual-engineering`, T20→`quick`, T21-T22→`unspecified-high`
- **FINAL**: 4 tasks — F1→`oracle`, F2-F3→`unspecified-high`, F4→`deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.

### Wave 1 — Foundation (start immediately, all independent)

- [x] 1. Project Skeleton + Docker Compose + Environment Setup

  **What to do**:
  - Initialize Python project with `pyproject.toml` (dependencies: fastapi, uvicorn, sqlalchemy, alembic, typer, httpx, python-dotenv, pytest, ruff)
  - Create Dockerfile (multi-stage, non-root user, pinned Python version)
  - Create `docker-compose.yml` with PostgreSQL 16 + app service + healthchecks
  - Create `.env.example` with all required env vars (DB URL, ETHERSCAN_API_KEY, SOLSCAN_API_KEY, COINGECKO_API_KEY, COINBASE_API_KEY)
  - Create `.env` (gitignored) from example
  - Create `.gitignore` (include .env, __pycache__, .pytest_cache, *.pyc, .sisyphus/evidence/)
  - Create basic package structure: `src/kryptoskatt/` with `__init__.py`, `cli/`, `models/`, `parsers/`, `chains/`, `engine/`, `services/`, `reports/`, `web/`
  - Create `src/kryptoskatt/cli/__init__.py` with Typer app skeleton (empty commands)
  - Create `src/kryptoskatt/config.py` — load .env, expose settings object (pydantic BaseSettings)
  - Verify: `docker compose build` succeeds, `docker compose up -d` starts both services

  **Must NOT do**:
  - Do NOT install React, Vue, or any JS framework
  - Do NOT add Redis or Celery
  - Do NOT hardcode any API keys in source
  - Do NOT create auth/login functionality

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Boilerplate scaffolding, well-understood patterns
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `playwright`: No browser testing needed for scaffolding

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5)
  - **Blocks**: Tasks 2, 3, 4, 5, and all subsequent tasks
  - **Blocked By**: None (start immediately)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:29-42` — Original architecture description (reference, but our agreed scope overrides)
  - **External References**:
    - Typer docs: https://typer.tiangolo.com/ — CLI framework
    - Pydantic Settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/ — env var loading
    - Docker multi-stage: https://docs.docker.com/build/building/multi-stage/
  - **WHY Each Reference Matters**:
    - systemdesign.md has the original data flow concept — use as mental model but simplify for CLI
    - Typer for CLI structure instead of Flask/FastAPI for API-first

  **Acceptance Criteria**:
  - [ ] `docker compose build` → exits 0, no errors
  - [ ] `docker compose up -d` → both services healthy within 30s
  - [ ] `docker compose exec app python -c "from kryptoskatt.config import settings; print(settings.database_url)"` → prints DB URL
  - [ ] `.env.example` exists with all keys documented
  - [ ] `.gitignore` contains `.env` entry
  - [ ] No API keys appear in any committed file (`grep -r 'eyJ\|TVYHK\|BEGIN EC' src/` → 0 matches)

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Docker services start and connect
    Tool: Bash
    Preconditions: Docker installed, .env created from .env.example
    Steps:
      1. Run `docker compose build --progress=plain` — expect exit code 0
      2. Run `docker compose up -d` — expect exit code 0
      3. Run `docker compose ps` — expect 2 services with status 'healthy' or 'running'
      4. Run `docker compose exec app python -c "import kryptoskatt; print('OK')"` — expect 'OK'
    Expected Result: Both services running, Python package importable
    Failure Indicators: Build errors, services in 'restarting' state, import errors
    Evidence: .sisyphus/evidence/task-1-docker-services.txt

  Scenario: No secrets in codebase
    Tool: Bash
    Preconditions: Project files created
    Steps:
      1. Run `grep -r 'eyJhbGci\|TVYHKHJ\|BEGIN EC PRIVATE' src/ .env.example docker-compose.yml Dockerfile` — expect 0 matches
      2. Run `cat .gitignore | grep '.env'` — expect match
    Expected Result: Zero secrets in committed files, .env gitignored
    Failure Indicators: Any grep match on secrets patterns
    Evidence: .sisyphus/evidence/task-1-no-secrets.txt
  ```

  **Commit**: YES
  - Message: `chore: project skeleton with Docker Compose and pytest setup`
  - Files: `pyproject.toml, Dockerfile, docker-compose.yml, .env.example, .gitignore, src/kryptoskatt/**`
  - Pre-commit: `docker compose build`

---

- [x] 2. Database Schema + SQLAlchemy Models + Alembic Migrations

  **What to do**:
  - Design and implement SQLAlchemy models for all core entities:
    - `Wallet`: id, address, chain (enum), label, is_mine (bool), created_at
    - `ImportBatch`: id, platform (enum), filename, imported_at, row_count, error_count
    - `Transaction`: id, import_batch_id (nullable), wallet_id (nullable), source_platform, timestamp_utc, event_type (enum: BUY, SELL, SWAP_IN, SWAP_OUT, TRANSFER_IN, TRANSFER_OUT, REWARD, FEE), base_coin, base_amount (Numeric/Decimal), quote_coin, quote_amount, fee_coin, fee_amount, tx_hash, from_address, to_address, price_sek (Numeric — populated later), is_duplicate (bool, default false), raw_payload (JSONB)
    - `TransferLink`: id, tx_out_id (FK), tx_in_id (FK), match_method (enum: TX_HASH, AMOUNT_TIME, MANUAL), confidence
    - `PriceCache`: id, coin_id, date (DATE), price_sek (Numeric), source (enum: COINGECKO, MANUAL, EXCHANGE_REPORTED)
    - `Disposal`: id, tax_year, coin, sell_timestamp, sell_amount, proceeds_sek, cost_basis_sek, gain_loss_sek, gav_at_disposal
    - `GavLedger`: id, coin, timestamp, event_type, amount_change, total_amount, total_cost_sek, gav_per_unit_sek (snapshot of GAV after event)
  - All Numeric fields use `Numeric(precision=28, scale=18)` — NEVER Float
  - Set up Alembic with initial migration
  - Create `src/kryptoskatt/models/__init__.py` exporting all models
  - Create enum types: `Chain`, `Platform`, `EventType`, `MatchMethod`, `PriceSource`
  - Create index on Transaction(tx_hash) for dedup, Transaction(timestamp_utc) for sorting, PriceCache(coin_id, date) for lookups

  **Must NOT do**:
  - Do NOT use Float for any monetary/amount column
  - Do NOT add User/Session/Auth tables
  - Do NOT add ORM relationships beyond FK constraints (keep simple)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Complex schema design with financial precision requirements
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (after Task 1)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 6-10, 12, 13
  - **Blocked By**: Task 1 (needs project structure)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:56-81` — UnifiedTransaction schema concept (adapt to our simpler model)
    - `systemdesign.md:47-54` — Original entity list (our models are simpler)
  - **External References**:
    - SQLAlchemy Numeric type: https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Numeric
    - Alembic tutorial: https://alembic.sqlalchemy.org/en/latest/tutorial.html
  - **WHY Each Reference Matters**:
    - systemdesign.md schema is the starting point but we simplify (no Session/User, add GavLedger)
    - Numeric(28,18) gives 10 integer digits + 18 decimal — handles crypto amounts perfectly

  **Acceptance Criteria**:
  - [ ] All models importable: `from kryptoskatt.models import Transaction, Wallet, Disposal`
  - [ ] `alembic upgrade head` → creates all tables in PostgreSQL
  - [ ] `alembic downgrade base` → drops all tables cleanly
  - [ ] No Float types anywhere: `grep -r 'Float' src/kryptoskatt/models/` → 0 matches
  - [ ] Transaction.base_amount is Numeric(28,18)

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Migrations run clean on fresh database
    Tool: Bash
    Preconditions: Docker Compose running with PostgreSQL
    Steps:
      1. Run `docker compose exec app alembic upgrade head` — expect exit code 0
      2. Run `docker compose exec app python -c "from kryptoskatt.models import Transaction; print(Transaction.__tablename__)"` — expect 'transactions'
      3. Run `docker compose exec app alembic downgrade base` — expect exit code 0
      4. Run `docker compose exec app alembic upgrade head` — verify idempotent
    Expected Result: Clean up/down migration cycle
    Failure Indicators: SQL errors, missing tables, migration conflicts
    Evidence: .sisyphus/evidence/task-2-migrations.txt

  Scenario: No Float types in models
    Tool: Bash
    Steps:
      1. Run `grep -rn 'Float\|FLOAT\|float_' src/kryptoskatt/models/` — expect 0 matches
      2. Run `grep -rn 'Numeric' src/kryptoskatt/models/` — expect multiple matches
    Expected Result: All amount fields are Numeric, zero Float usage
    Evidence: .sisyphus/evidence/task-2-no-float.txt
  ```

  **Commit**: YES (groups with Task 3)
  - Message: `feat(db): database schema, SQLAlchemy models, and transaction types`
  - Files: `src/kryptoskatt/models/**, alembic/**, src/kryptoskatt/enums.py`
  - Pre-commit: `alembic upgrade head`

---

- [x] 3. UnifiedTransaction Schema + Decimal Types + Enums

  **What to do**:
  - Create `src/kryptoskatt/schemas.py` with Pydantic models for data transfer:
    - `TransactionCreate` — input schema for creating transactions (from parsers)
    - `TransactionRead` — output schema
    - `WalletCreate`, `WalletRead`
    - `K4SummaryRow` — coin, proceeds_sek, cost_basis_sek, gain_loss_sek
    - `K4Report` — tax_year, rows: list[K4SummaryRow], total_gains, total_losses
    - `GavSnapshot` — coin, timestamp, gav_per_unit, total_units, total_cost
  - All amount fields as `Decimal` with custom validators (no negative amounts for base_amount)
  - Create `src/kryptoskatt/enums.py` — Chain, Platform, EventType enums (shared between models and schemas)
  - Ensure enums cover all known chains: SOLANA, ETHEREUM, POLYGON, BNB, KADENA, TRON, VECHAIN, PEAQ, ALEO, RIPPLE, UNKNOWN
  - Ensure Platform enum covers: COINBASE, CRYPTO_COM, MEXC, ON_CHAIN, MANUAL
  - Ensure EventType covers: BUY, SELL, SWAP_IN, SWAP_OUT, TRANSFER_IN, TRANSFER_OUT, REWARD, FEE, UNKNOWN

  **Must NOT do**:
  - Do NOT use float anywhere in schemas
  - Do NOT add auth-related schemas

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Straightforward Pydantic models and Python enums
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (after Task 1)
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5)
  - **Blocks**: Tasks 6-11, 16
  - **Blocked By**: Task 1

  **References**:
  - **Pattern References**:
    - `systemdesign.md:59-81` — Original UnifiedTransaction JSON schema
  - **External References**:
    - Pydantic Decimal handling: https://docs.pydantic.dev/latest/concepts/types/#decimal
  - **WHY Each Reference Matters**:
    - systemdesign.md defines the original field set — adapt to our simplified model (no session_id, add price_sek)

  **Acceptance Criteria**:
  - [ ] `from kryptoskatt.schemas import TransactionCreate, K4Report` → no errors
  - [ ] `TransactionCreate(base_amount=Decimal('0.001'), ...)` → validates correctly
  - [ ] `TransactionCreate(base_amount=-1)` → raises ValidationError
  - [ ] All enums defined: `Chain.SOLANA`, `Platform.COINBASE`, `EventType.REWARD`

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Pydantic schemas validate Decimal amounts
    Tool: Bash
    Steps:
      1. Run `python -c "from decimal import Decimal; from kryptoskatt.schemas import TransactionCreate; t = TransactionCreate(source_platform='coinbase', timestamp_utc='2024-01-01T00:00:00Z', event_type='BUY', base_coin='ETH', base_amount=Decimal('0.5')); print(t.base_amount)"` — expect Decimal('0.5')
      2. Run similar with negative amount — expect ValidationError
    Expected Result: Decimal validation works, negative amounts rejected
    Evidence: .sisyphus/evidence/task-3-schemas.txt
  ```

  **Commit**: YES (groups with Task 2)
  - Message: `feat(db): database schema, SQLAlchemy models, and transaction types`
  - Files: `src/kryptoskatt/schemas.py, src/kryptoskatt/enums.py`

---

- [x] 4. Pytest Infrastructure + TDD Fixtures

  **What to do**:
  - Create `tests/conftest.py` with:
    - PostgreSQL test database fixture (use test DB URL from .env or SQLite for fast local tests)
    - SQLAlchemy session fixture (transaction-rollback pattern for test isolation)
    - Sample transaction fixtures: `sample_buy_eth`, `sample_sell_eth`, `sample_swap_btc_to_eth`, `sample_transfer_in`, `sample_reward_geod`
    - Sample wallet fixtures: `sample_eth_wallet`, `sample_sol_wallet`
  - Create `tests/fixtures/` directory with sample CSV files:
    - `coinbase_sample.csv` — 5 rows based on format from systemdesign.md lines 260-272
    - `crypto_com_sample.csv` — 5 rows based on format from systemdesign.md lines 275-283
    - `mexc_deposit_sample.tsv` — 3 rows based on format from systemdesign.md lines 287-301
    - `mexc_withdrawal_sample.tsv` — 3 rows based on format from systemdesign.md lines 293-301
  - Create `tests/test_smoke.py` — basic import tests to verify test infrastructure
  - Configure pytest in `pyproject.toml` with: testpaths, asyncio_mode, markers
  - Ensure `pytest` runs green from zero

  **Must NOT do**:
  - Do NOT write implementation tests yet — just infrastructure and fixtures
  - Do NOT use real API keys in test fixtures

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Test scaffolding, fixture creation, straightforward
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (after Task 1)
  - **Parallel Group**: Wave 1
  - **Blocks**: All test-dependent tasks (6-22)
  - **Blocked By**: Task 1

  **References**:
  - **Pattern References**:
    - `systemdesign.md:260-301` — Exact CSV/TSV formats for fixture files (CRITICAL — copy headers + sample rows)
  - **External References**:
    - Pytest fixtures: https://docs.pytest.org/en/stable/how-to/fixtures.html
  - **WHY Each Reference Matters**:
    - systemdesign.md has REAL sample data from user's actual exports — use these exact formats for fixtures

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_smoke.py` → PASS
  - [ ] Fixture files exist in `tests/fixtures/`
  - [ ] conftest.py provides `db_session`, `sample_buy_eth` fixtures

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Test infrastructure works
    Tool: Bash
    Steps:
      1. Run `pytest tests/test_smoke.py -v` — expect all pass
      2. Run `ls tests/fixtures/` — expect coinbase_sample.csv, crypto_com_sample.csv, mexc_deposit_sample.tsv, mexc_withdrawal_sample.tsv
    Expected Result: Pytest green, fixtures present
    Evidence: .sisyphus/evidence/task-4-test-infra.txt
  ```

  **Commit**: YES (groups with Task 5)
  - Message: `feat(wallet): wallet registry and test infrastructure`
  - Files: `tests/**`

---

- [x] 5. Wallet Registry (Address Book) + CLI Commands

  **What to do**:
  - Create `src/kryptoskatt/services/wallet.py` — WalletService:
    - `add_wallet(address, chain, label, is_mine)` → saves to DB
    - `list_wallets(chain=None, mine_only=False)` → returns wallets
    - `remove_wallet(address)` → soft delete or hard delete
    - `get_my_addresses()` → returns set of (address, chain) tuples for transfer matching
  - Create CLI commands in `src/kryptoskatt/cli/wallet.py`:
    - `kryptoskatt wallet add --address 0x... --chain ethereum --label "Main ETH" --mine`
    - `kryptoskatt wallet list [--chain solana] [--mine-only]`
    - `kryptoskatt wallet remove --address 0x...`
  - Validate address format per chain (basic validation — not full checksum, just format sanity)
  - Chain enum validation: reject unknown chains with helpful error

  **Must NOT do**:
  - Do NOT implement wallet balance lookup
  - Do NOT implement transaction fetching (that's Task 9/10)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple CRUD operations + CLI wiring
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (after Task 1)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 9, 10, 13, 15
  - **Blocked By**: Task 1

  **References**:
  - **Pattern References**:
    - `systemdesign.md:307-348` — Trust Wallet data shows address format (partial: `FceP6wv...9GfMDsp`)
    - `systemdesign.md:287-301` — MEXC shows withdrawal addresses (full: `0x85fB22b3C15C7C2c93F26E83F446950D9408ba67`)
  - **External References**:
    - Typer docs: https://typer.tiangolo.com/tutorial/commands/
  - **WHY Each Reference Matters**:
    - Address examples from systemdesign.md show what real addresses look like per chain

  **Acceptance Criteria**:
  - [ ] `kryptoskatt wallet add --address 0xtest --chain ethereum --label test --mine` → wallet saved to DB
  - [ ] `kryptoskatt wallet list` → shows added wallet
  - [ ] `kryptoskatt wallet list --mine-only` → filters correctly

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Wallet CRUD via CLI
    Tool: Bash
    Steps:
      1. Run `kryptoskatt wallet add --address 0xABC123 --chain ethereum --label "Test ETH" --mine` — expect success message
      2. Run `kryptoskatt wallet list` — expect table with 0xABC123, ethereum, Test ETH, mine=True
      3. Run `kryptoskatt wallet list --chain solana` — expect empty (no solana wallets)
      4. Run `kryptoskatt wallet remove --address 0xABC123` — expect success
      5. Run `kryptoskatt wallet list` — expect empty
    Expected Result: Full CRUD cycle works
    Failure Indicators: DB errors, wrong chain filtering, wallet not found on remove
    Evidence: .sisyphus/evidence/task-5-wallet-crud.txt

  Scenario: Invalid chain rejected
    Tool: Bash
    Steps:
      1. Run `kryptoskatt wallet add --address 0xABC --chain invalidchain --label test` — expect error
    Expected Result: Clear error message about invalid chain, exit code != 0
    Evidence: .sisyphus/evidence/task-5-invalid-chain.txt
  ```

  **Commit**: YES (groups with Task 4)
  - Message: `feat(wallet): wallet registry and test infrastructure`
  - Files: `src/kryptoskatt/services/wallet.py, src/kryptoskatt/cli/wallet.py`

---

### Wave 2 — Data Ingestion (after Wave 1, MAX PARALLEL)

- [x] 6. Coinbase CSV Parser

  **What to do**:
  - Create `src/kryptoskatt/parsers/coinbase.py` — `CoinbaseParser` class
  - Implement `parse(file_path: Path) -> list[TransactionCreate]`
  - Handle Coinbase CSV format: skip metadata rows (User, ID line), find header row (`ID,Timestamp,Transaction Type,...`)
  - Map Transaction Types to EventType enum:
    - `Buy` → BUY
    - `Send` → TRANSFER_OUT (check Notes for "Sent X to...")
    - `Receive` → TRANSFER_IN (check Notes for "Received X from...")
    - `Convert` → two records: SWAP_OUT (negative amount) + SWAP_IN (positive, from Notes: "Converted X to Y")
    - `Sell` → SELL
    - `Reward` → REWARD
  - Parse amounts as Decimal (not float). Handle Swedish-style `kr` prefix and comma formats in Price/Subtotal/Total columns.
  - Extract from_address/to_address from Notes field (regex: `to (\w+\.\.\.\w+)` or `from (\w+\.\.\.\w+)`)
  - Extract tx_hash if present (Coinbase CSV may not include it — set null)
  - Store raw row as `raw_payload` JSON
  - Handle Convert (swap) edge case: Notes contains "Converted 7.53325 XRP to 91.799939 ALEO" — parse BOTH coins
  - Detect and report error rows (malformed dates, unparseable amounts) without failing the entire file
  - Write tests: parse fixture file (`tests/fixtures/coinbase_sample.csv`), verify all event types map correctly

  **Must NOT do**:
  - Do NOT use float for any amount parsing — Decimal only
  - Do NOT call any external APIs (no price lookups during parsing)
  - Do NOT skip/ignore any row silently — errors must be collected and reported

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Complex CSV parsing with edge cases (metadata rows, embedded SEK prices, Convert→SWAP split)
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 8, 9, 10, 11, 12, 13)
  - **Blocks**: Tasks 14, 15
  - **Blocked By**: Tasks 2, 3 (needs Transaction model + schemas)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:260-272` — EXACT Coinbase CSV format with real data. Headers: `ID,Timestamp,Transaction Type,Asset,Quantity Transacted,Price Currency,Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),Fees and/or Spread,Notes`
    - `tests/fixtures/coinbase_sample.csv` — Test fixture to parse (created in Task 4)
  - **API/Type References**:
    - `src/kryptoskatt/schemas.py:TransactionCreate` — Output schema for each parsed row
    - `src/kryptoskatt/enums.py:EventType` — Enum values to map to
  - **External References**:
    - Python csv module: https://docs.python.org/3/library/csv.html
  - **WHY Each Reference Matters**:
    - systemdesign.md lines 260-272 have the REAL format from user's actual Coinbase export — note the metadata lines before headers, the `kr` prefix on prices, the Notes field with address fragments
    - TransactionCreate schema is the target output — every parsed row must produce a valid instance
    - The Convert type produces TWO transactions (SWAP_OUT + SWAP_IN) — see line 263 "Converted 7.53325 XRP to 91.799939 ALEO"

  **Acceptance Criteria**:
  - [ ] `from kryptoskatt.parsers.coinbase import CoinbaseParser` → no errors
  - [ ] `CoinbaseParser().parse('tests/fixtures/coinbase_sample.csv')` → returns list of TransactionCreate
  - [ ] Convert rows produce 2 transactions (SWAP_OUT + SWAP_IN)
  - [ ] All amounts are Decimal instances
  - [ ] `pytest tests/test_coinbase_parser.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Parse Coinbase CSV with all event types
    Tool: Bash
    Preconditions: Task 2,3 complete, fixture file exists
    Steps:
      1. Run `python -c "from kryptoskatt.parsers.coinbase import CoinbaseParser; txs = CoinbaseParser().parse('tests/fixtures/coinbase_sample.csv'); print(len(txs)); [print(f'{t.event_type} {t.base_coin} {t.base_amount}') for t in txs]"` — expect transactions list
      2. Verify Convert rows produce 2 records: grep output for SWAP_OUT and SWAP_IN
      3. Run `python -c "from decimal import Decimal; from kryptoskatt.parsers.coinbase import CoinbaseParser; txs = CoinbaseParser().parse('tests/fixtures/coinbase_sample.csv'); assert all(isinstance(t.base_amount, Decimal) for t in txs); print('OK')"` — expect 'OK'
    Expected Result: All event types mapped, Convert→2 records, Decimal amounts
    Failure Indicators: Float amounts, Convert→1 record, missing events, import errors
    Evidence: .sisyphus/evidence/task-6-coinbase-parser.txt

  Scenario: Error handling for malformed rows
    Tool: Bash
    Steps:
      1. Create a temp CSV with a malformed row (bad date format)
      2. Parse it — expect parser to return valid rows + error report, NOT throw exception
    Expected Result: Partial parse succeeds with error list
    Evidence: .sisyphus/evidence/task-6-coinbase-errors.txt
  ```

  **Commit**: YES (groups with Tasks 7, 8)
  - Message: `feat(parsers): CSV/TSV parsers for Coinbase, Crypto.com, MEXC`
  - Files: `src/kryptoskatt/parsers/coinbase.py, tests/test_coinbase_parser.py`
  - Pre-commit: `pytest tests/test_coinbase_parser.py`

---

- [x] 7. Crypto.com CSV Parser

  **What to do**:
  - Create `src/kryptoskatt/parsers/crypto_com.py` — `CryptoComParser` class
  - Implement `parse(file_path: Path) -> list[TransactionCreate]`
  - Handle Crypto.com CSV format: Headers are `Timestamp (UTC),Transaction Description,Currency,Amount,To Currency,To Amount,Native Currency,Native Amount,Native Amount (in USD),Transaction Kind,Transaction Hash`
  - Map `Transaction Kind` to EventType enum:
    - `crypto_wallet_swap_credited` → SWAP_IN
    - `crypto_wallet_swap_debited` → SWAP_OUT
    - `crypto_withdrawal` → TRANSFER_OUT
    - `crypto_exchange` → handle as SWAP: Currency is sold (SWAP_OUT), To Currency is bought (SWAP_IN)
    - `crypto_deposit` → TRANSFER_IN
    - `crypto_earn_interest_paid` / similar → REWARD
  - For `crypto_exchange` rows: generate TWO TransactionCreate records (SWAP_OUT + SWAP_IN using To Currency/To Amount)
  - Parse `Native Amount` as price_sek when Native Currency is SEK
  - Extract tx_hash from `Transaction Hash` column (may be empty)
  - All amounts as Decimal
  - Store entire row as raw_payload
  - Error handling: collect bad rows, continue parsing
  - Write tests with `tests/fixtures/crypto_com_sample.csv`

  **Must NOT do**:
  - Do NOT use float for amounts
  - Do NOT call external APIs
  - Do NOT silently skip rows — report errors

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Multiple transaction kinds with different field semantics
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 8-13)
  - **Blocks**: Tasks 14, 15
  - **Blocked By**: Tasks 2, 3

  **References**:
  - **Pattern References**:
    - `systemdesign.md:275-283` — EXACT Crypto.com CSV format with real data. Note: `crypto_exchange` rows use Currency/Amount for the sold side and To Currency/To Amount for the bought side
    - `tests/fixtures/crypto_com_sample.csv` — Test fixture (Task 4)
    - `src/kryptoskatt/parsers/coinbase.py` — Follow same class structure/interface as Coinbase parser
  - **API/Type References**:
    - `src/kryptoskatt/schemas.py:TransactionCreate` — Output schema
    - `src/kryptoskatt/enums.py:EventType` — Target enum values
  - **WHY Each Reference Matters**:
    - systemdesign.md lines 275-283 show REAL data — note that `crypto_exchange` has both Currency and To Currency columns
    - The `Balance Conversion` rows (lines 276-277) come in credited/debited PAIRS — same timestamp, opposite amounts
    - Coinbase parser sets the interface pattern — all parsers should follow the same class structure

  **Acceptance Criteria**:
  - [ ] `CryptoComParser().parse('tests/fixtures/crypto_com_sample.csv')` → returns TransactionCreate list
  - [ ] `crypto_exchange` rows produce 2 records (SWAP_OUT + SWAP_IN)
  - [ ] `crypto_withdrawal` maps to TRANSFER_OUT with tx_hash populated
  - [ ] All amounts Decimal
  - [ ] `pytest tests/test_crypto_com_parser.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Parse Crypto.com CSV with exchanges and withdrawals
    Tool: Bash
    Preconditions: Fixture file exists, schemas importable
    Steps:
      1. Run `python -c "from kryptoskatt.parsers.crypto_com import CryptoComParser; txs = CryptoComParser().parse('tests/fixtures/crypto_com_sample.csv'); print(len(txs)); [print(f'{t.event_type} {t.base_coin} {t.base_amount} hash={t.tx_hash}') for t in txs]"` — expect transactions
      2. Verify crypto_exchange rows produce SWAP_OUT + SWAP_IN pairs
      3. Verify crypto_withdrawal has tx_hash from Transaction Hash column
    Expected Result: Correct mapping of all Transaction Kind values, tx_hash populated where available
    Failure Indicators: Missing SWAP_IN from exchanges, null tx_hash on withdrawals
    Evidence: .sisyphus/evidence/task-7-crypto-com-parser.txt

  Scenario: Balance Conversion pairs handled correctly
    Tool: Bash
    Steps:
      1. Parse fixture with Balance Conversion rows (credited + debited at same timestamp)
      2. Verify they produce SWAP_IN + SWAP_OUT with matching timestamps
    Expected Result: Paired conversion records
    Evidence: .sisyphus/evidence/task-7-balance-conversion.txt
  ```

  **Commit**: YES (groups with Tasks 6, 8)
  - Message: `feat(parsers): CSV/TSV parsers for Coinbase, Crypto.com, MEXC`
  - Files: `src/kryptoskatt/parsers/crypto_com.py, tests/test_crypto_com_parser.py`
  - Pre-commit: `pytest tests/test_crypto_com_parser.py`

---

- [x] 8. MEXC TSV Parser — Deposits, Withdrawals, Trades

  **What to do**:
  - Create `src/kryptoskatt/parsers/mexc.py` — `MexcParser` class
  - CRITICAL: MEXC files are TAB-SEPARATED (TSV), NOT CSV. Use `csv.reader(f, delimiter='\t')`
  - CRITICAL: MEXC uses SWEDISH column headers: `UID`, `Status`, `Tid`, `Krypto`, `Nätverk`, `Insättningsbelopp`, `TxID`, `Framsteg`
  - Handle THREE separate file types (user may upload each separately):
    - **Deposit file** (`Insättning`): columns `UID, Status, Tid, Krypto, Nätverk, Insättningsbelopp, TxID, Framsteg` → TRANSFER_IN events
    - **Withdrawal file** (`Uttag`): columns `UID, Status, Tid, Krypto, Nätverk, Begärt belopp, Uttagsadress, memo, TxID, Handelsavgift, Avräkningsbelopp, Uttagsbeskrivningar` → TRANSFER_OUT events
    - **Trade file** (`Övrig`): columns `UID, Tid, Krypto, Typ, Kvantitet, Status, Anmärkning` → BUY/SELL based on Typ column
  - Auto-detect file type from column headers (use `Insättningsbelopp` vs `Uttagsadress` vs `Kvantitet` to distinguish)
  - For withdrawals: extract fee from `Handelsavgift`, actual amount from `Avräkningsbelopp`, destination from `Uttagsadress`
  - For deposits: extract amount from `Insättningsbelopp`, tx_hash from `TxID`
  - Map `Nätverk` to Chain enum: `Ethereum(ERC20)` → ETHEREUM, `Solana(SOL)` → SOLANA, `Polygon(MATIC)` → POLYGON, `BNB Smart Chain(BEP20)` → BNB, `KDA` → KADENA, `PEAQ` → PEAQ
  - Parse `Tid` as datetime (format: `YYYY-MM-DD HH:MM:SS`)
  - All amounts as Decimal
  - For TxID: some have `:010` suffix (e.g., `O02IiV-...Kumo:010`) — strip suffix for hash matching but keep original in raw_payload
  - Write tests with `tests/fixtures/mexc_deposit_sample.tsv` and `tests/fixtures/mexc_withdrawal_sample.tsv`

  **Must NOT do**:
  - Do NOT parse as regular CSV — MUST use tab delimiter
  - Do NOT hardcode column positions — use header names (Swedish)
  - Do NOT use float for amounts

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Non-standard format (TSV + Swedish headers + 3 file types + network mapping)
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 9-13)
  - **Blocks**: Tasks 14, 15
  - **Blocked By**: Tasks 2, 3

  **References**:
  - **Pattern References**:
    - `systemdesign.md:286-301` — EXACT MEXC format with real data. CRITICAL: These are TSV files with Swedish column headers.
    - `systemdesign.md:302-305` — Trade file headers (no sample data yet, just headers)
    - `tests/fixtures/mexc_deposit_sample.tsv` — Deposit fixture (Task 4)
    - `tests/fixtures/mexc_withdrawal_sample.tsv` — Withdrawal fixture (Task 4)
    - `src/kryptoskatt/parsers/coinbase.py` — Follow same interface pattern
  - **API/Type References**:
    - `src/kryptoskatt/schemas.py:TransactionCreate` — Output schema
    - `src/kryptoskatt/enums.py:Chain` — Map Nätverk values to Chain enum
  - **WHY Each Reference Matters**:
    - systemdesign.md lines 287-301 are the ONLY source for MEXC format — note tab-separated, Swedish headers (`Insättningsbelopp`, `Avräkningsbelopp`, `Handelsavgift`)
    - Withdrawal data (lines 293-301) shows the fee structure: `Begärt belopp` minus `Handelsavgift` = `Avräkningsbelopp`
    - TxID `O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM:010` shows the `:NNN` suffix pattern that appears in cross-platform matches

  **Acceptance Criteria**:
  - [ ] `MexcParser().parse('tests/fixtures/mexc_deposit_sample.tsv')` → returns TRANSFER_IN transactions
  - [ ] `MexcParser().parse('tests/fixtures/mexc_withdrawal_sample.tsv')` → returns TRANSFER_OUT with fees
  - [ ] Auto-detects file type from headers
  - [ ] Network `Ethereum(ERC20)` maps to Chain.ETHEREUM
  - [ ] All amounts Decimal
  - [ ] `pytest tests/test_mexc_parser.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Parse MEXC deposit TSV
    Tool: Bash
    Preconditions: Fixture files exist
    Steps:
      1. Run `python -c "from kryptoskatt.parsers.mexc import MexcParser; txs = MexcParser().parse('tests/fixtures/mexc_deposit_sample.tsv'); print(len(txs)); [print(f'{t.event_type} {t.base_coin} {t.base_amount} chain={t.tx_hash}') for t in txs]"` — expect TRANSFER_IN events
      2. Verify ETH deposit has Chain.ETHEREUM, KDA deposit has Chain.KADENA
    Expected Result: Deposits parsed as TRANSFER_IN, correct chain mapping
    Evidence: .sisyphus/evidence/task-8-mexc-deposits.txt

  Scenario: Parse MEXC withdrawal TSV with fees
    Tool: Bash
    Steps:
      1. Parse withdrawal fixture
      2. Verify fee_amount matches Handelsavgift column (e.g., 0.3 POL for Polygon withdrawals)
      3. Verify base_amount uses Avräkningsbelopp (actual amount after fee)
    Expected Result: Fees correctly extracted, amounts use settlement values
    Failure Indicators: Fee=0, wrong amount (using Begärt belopp instead of Avräkningsbelopp)
    Evidence: .sisyphus/evidence/task-8-mexc-withdrawals.txt

  Scenario: Tab-separated parsing (not comma-separated)
    Tool: Bash
    Steps:
      1. Verify fixture file uses actual tabs (not spaces/commas)
      2. Parse and confirm all columns extracted correctly
    Expected Result: All columns populated, no empty fields from wrong delimiter
    Evidence: .sisyphus/evidence/task-8-mexc-tsv-format.txt
  ```

  **Commit**: YES (groups with Tasks 6, 7)
  - Message: `feat(parsers): CSV/TSV parsers for Coinbase, Crypto.com, MEXC`
  - Files: `src/kryptoskatt/parsers/mexc.py, tests/test_mexc_parser.py`
  - Pre-commit: `pytest tests/test_mexc_parser.py`

---

- [ ] 9. Etherscan v2 Chain Adapter — ETH + EVM Chains

  **What to do**:
  - Create `src/kryptoskatt/chains/etherscan.py` — `EtherscanAdapter` class
  - Implement the generic chain interface (from Task 11): `fetch_transactions(address: str, chain: Chain) -> list[TransactionCreate]`
  - Use Etherscan v2 unified API:
    - Normal transactions: `GET https://api.etherscan.io/v2/api?chainid={id}&module=account&action=txlist&address={addr}&startblock=0&endblock=99999999&sort=asc&apikey={key}`
    - ERC-20 token transfers: `GET ...&action=tokentx&...`
    - Internal transactions: `GET ...&action=txlistinternal&...` (for contract interactions)
  - Chain ID mapping (from Chain enum):
    - ETHEREUM → 1, POLYGON → 137, BNB → 56, PEAQ → TBD (check Etherscan v2 docs)
  - For each transaction:
    - Classify as TRANSFER_IN (to_address matches our wallet), TRANSFER_OUT (from_address matches), or REWARD (from zero address)
    - Extract tx_hash, from_address, to_address, value (convert from Wei to ETH using Decimal division by 10**18)
    - Handle ERC-20 separately: different amount decimals per token
  - Implement pagination: Etherscan returns max 10000 results per call, use startblock/endblock for pagination
  - Rate limiting: max 5 calls/sec (free tier). Use asyncio.sleep or simple time.sleep between calls.
  - Use httpx for HTTP calls (async-ready)
  - API key from environment: `ETHERSCAN_API_KEY`
  - Write tests with mocked API responses (httpx mock)

  **Must NOT do**:
  - Do NOT hardcode API key — must come from env/config
  - Do NOT exceed 5 calls/sec (implement rate limiter)
  - Do NOT use requests library — use httpx
  - Do NOT skip ERC-20 token transactions (only normal txs would miss token transfers)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: External API integration with rate limiting, Wei conversion, pagination, multi-chain support
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6-8, 10-13)
  - **Blocks**: Tasks 14, 15
  - **Blocked By**: Tasks 2, 3, 5 (needs models, schemas, wallet registry for address ownership)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:357-362` — Etherscan API key and docs link. Note: v2 supports 60+ chains with single key.
  - **API/Type References**:
    - `src/kryptoskatt/schemas.py:TransactionCreate` — Output schema
    - `src/kryptoskatt/enums.py:Chain` — Chain enum with chain IDs
    - `src/kryptoskatt/services/wallet.py:WalletService.get_my_addresses()` — To determine if from/to address is ours
  - **External References**:
    - Etherscan v2 docs: https://docs.etherscan.io/etherscan-v2
    - Etherscan supported chains: https://docs.etherscan.io/supported-chains
    - httpx docs: https://www.python-httpx.org/
  - **WHY Each Reference Matters**:
    - Etherscan v2 is the SINGLE entry point for ETH, Polygon, BNB, and potentially PEAQ — one adapter handles 4+ chains
    - Wei conversion (10**18) is critical — raw values are integers, must convert to Decimal
    - ERC-20 tokens have variable decimals (USDC=6, most ERC-20=18) — must read `tokenDecimal` field

  **Acceptance Criteria**:
  - [ ] `EtherscanAdapter().fetch_transactions('0xtest', Chain.ETHEREUM)` → returns TransactionCreate list (mocked)
  - [ ] Wei-to-ETH conversion correct: `1000000000000000000 Wei = Decimal('1.0') ETH`
  - [ ] ERC-20 tokens handled with correct decimal places
  - [ ] Rate limiting: max 5 calls/sec
  - [ ] `pytest tests/test_etherscan_adapter.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Fetch and parse mocked Etherscan v2 response
    Tool: Bash
    Preconditions: httpx mock fixture with sample API response
    Steps:
      1. Create mock response matching Etherscan v2 JSON format (status, message, result array)
      2. Run adapter with mocked httpx client
      3. Verify returned transactions have correct event_type (TRANSFER_IN/OUT based on address)
      4. Verify tx_hash, from_address, to_address populated
      5. Verify amount converted from Wei to Decimal correctly
    Expected Result: Mocked API response parsed into TransactionCreate objects
    Failure Indicators: Wrong event type direction, Wei not converted, missing tx_hash
    Evidence: .sisyphus/evidence/task-9-etherscan-mock.txt

  Scenario: Multi-chain support with chain IDs
    Tool: Bash
    Steps:
      1. Verify EtherscanAdapter handles Chain.ETHEREUM (chainid=1), Chain.POLYGON (chainid=137), Chain.BNB (chainid=56)
      2. Assert API URL includes correct chainid parameter for each chain
    Expected Result: Correct chainid per chain in API requests
    Evidence: .sisyphus/evidence/task-9-etherscan-chains.txt
  ```

  **Commit**: YES (groups with Tasks 10, 11)
  - Message: `feat(chain): blockchain adapters for Etherscan v2 and Solscan v2`
  - Files: `src/kryptoskatt/chains/etherscan.py, tests/test_etherscan_adapter.py`
  - Pre-commit: `pytest tests/test_etherscan_adapter.py`

---

- [ ] 10. Solscan v2 Chain Adapter — Solana

  **What to do**:
  - Create `src/kryptoskatt/chains/solscan.py` — `SolscanAdapter` class
  - Implement chain interface: `fetch_transactions(address: str, chain: Chain) -> list[TransactionCreate]`
  - Use Solscan v2 API:
    - Account transactions: `GET https://pro-api.solscan.io/v2.0/account/transactions?address={addr}&limit=40`
    - Token transfers: `GET https://pro-api.solscan.io/v2.0/account/token/txs?address={addr}`
    - API key via header: `token: {SOLSCAN_API_KEY}`
  - For each transaction:
    - SOL transfers: classify TRANSFER_IN/OUT based on address ownership
    - SPL token transfers (GEOD, USDC, etc.): use token transfer endpoint
    - Staking/DePIN rewards: `TRANSFER_IN` from program address → classify as REWARD
    - For GEOD rewards specifically: daily TRANSFER_IN from `FceP6wv...9GfMDsp` → REWARD
  - Convert SOL amounts from lamports (1 SOL = 10**9 lamports) using Decimal
  - SPL token decimals vary (GEOD, USDC etc.) — fetch from token metadata or hardcode known tokens
  - Pagination: Solscan v2 uses cursor-based pagination
  - Rate limiting: respect API limits
  - API key from environment: `SOLSCAN_API_KEY`
  - Write tests with mocked API responses

  **Must NOT do**:
  - Do NOT hardcode API key
  - Do NOT use float for lamport conversion
  - Do NOT skip SPL token transfers (most DePIN rewards are SPL tokens)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Solana-specific API with lamport conversion, SPL tokens, DePIN reward detection
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6-9, 11-13)
  - **Blocks**: Tasks 14, 15
  - **Blocked By**: Tasks 2, 3, 5

  **References**:
  - **Pattern References**:
    - `systemdesign.md:351-355` — Solscan API key and endpoint reference
    - `systemdesign.md:307-348` — Trust Wallet data shows GEOD reward pattern: daily receives from `FceP6wv...9GfMDsp` with amounts like `+12 GEOD`
    - `src/kryptoskatt/chains/etherscan.py` — Follow same adapter interface pattern
  - **API/Type References**:
    - `src/kryptoskatt/schemas.py:TransactionCreate` — Output schema
    - `src/kryptoskatt/services/wallet.py:WalletService.get_my_addresses()` — Address ownership check
  - **External References**:
    - Solscan v2 API docs: https://pro-api.solscan.io/pro-api-docs/v2.0
  - **WHY Each Reference Matters**:
    - systemdesign.md lines 307-348 show the REAL GEOD reward pattern from Trust Wallet — these are the actual on-chain transactions Solscan will return
    - The reward source address `FceP6wv...9GfMDsp` is a DePIN distribution address — transfers from it should be classified as REWARD
    - Etherscan adapter (Task 9) sets the interface pattern — Solscan adapter must implement the same interface

  **Acceptance Criteria**:
  - [ ] `SolscanAdapter().fetch_transactions('CAGfWW...', Chain.SOLANA)` → returns TransactionCreate list (mocked)
  - [ ] Lamport-to-SOL conversion correct: `1000000000 = Decimal('1.0')`
  - [ ] SPL token transfers detected and parsed
  - [ ] GEOD rewards classified as REWARD (not TRANSFER_IN)
  - [ ] `pytest tests/test_solscan_adapter.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Parse mocked Solscan v2 SOL transfer response
    Tool: Bash
    Preconditions: Mock fixture with sample Solscan API JSON
    Steps:
      1. Create mock Solscan v2 response with SOL transfer + SPL token transfer
      2. Run adapter with mocked httpx client
      3. Verify SOL amount converted from lamports to Decimal correctly
      4. Verify SPL token transfer (e.g., GEOD) parsed with correct token symbol and amount
    Expected Result: Both SOL and SPL transfers parsed correctly
    Evidence: .sisyphus/evidence/task-10-solscan-mock.txt

  Scenario: GEOD rewards classified as REWARD
    Tool: Bash
    Steps:
      1. Mock a transfer_in from known DePIN distribution address
      2. Verify event_type is REWARD, not TRANSFER_IN
    Expected Result: DePIN rewards correctly classified
    Evidence: .sisyphus/evidence/task-10-geod-rewards.txt
  ```

  **Commit**: YES (groups with Tasks 9, 11)
  - Message: `feat(chain): blockchain adapters for Etherscan v2 and Solscan v2`
  - Files: `src/kryptoskatt/chains/solscan.py, tests/test_solscan_adapter.py`
  - Pre-commit: `pytest tests/test_solscan_adapter.py`

---

- [x] 11. Generic Chain Adapter Interface + Registry

  **What to do**:
  - Create `src/kryptoskatt/chains/base.py` — `ChainAdapter` abstract base class (ABC/Protocol):
    - `fetch_transactions(address: str, chain: Chain) -> list[TransactionCreate]` (abstract)
    - `supported_chains() -> list[Chain]` (abstract)
    - `rate_limit_delay() -> float` (default 0.2 sec)
  - Create `src/kryptoskatt/chains/registry.py` — `ChainRegistry`:
    - `register(adapter: ChainAdapter)` — registers adapter for its supported chains
    - `get_adapter(chain: Chain) -> ChainAdapter | None`
    - `supported_chains() -> list[Chain]`
    - `fetch_all(wallets: list[Wallet]) -> list[TransactionCreate]` — iterates all wallets, dispatches to correct adapter
  - Pre-register Etherscan adapter for: ETHEREUM, POLYGON, BNB
  - Pre-register Solscan adapter for: SOLANA
  - For unsupported chains (KADENA, TRON, VECHAIN, RIPPLE, ALEO): log warning "No adapter for chain X, skipping address Y"
  - Create `src/kryptoskatt/chains/__init__.py` — export registry with default adapters
  - Write tests: registry dispatches correctly, unsupported chains logged

  **Must NOT do**:
  - Do NOT create adapters for unsupported chains — just log and skip
  - Do NOT build a plugin system — simple dict registry is enough
  - Do NOT over-abstract — Protocol/ABC + dict, nothing more

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple interface definition + dict-based registry, straightforward
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6-10, 12-13)
  - **Blocks**: Tasks 9, 10 (they implement the interface)
  - **Blocked By**: Task 3 (needs Chain enum)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:186-208` — Original parser-plugin concept (adapt to chain adapter pattern, simpler)
  - **API/Type References**:
    - `src/kryptoskatt/enums.py:Chain` — Enum for all supported chains
    - `src/kryptoskatt/schemas.py:TransactionCreate` — Return type from fetch
  - **WHY Each Reference Matters**:
    - systemdesign.md parser interface concept shows `can_parse()` + `parse()` — adapt to `supported_chains()` + `fetch_transactions()`
    - Chain enum is the dispatch key — each adapter declares which chains it handles

  **Acceptance Criteria**:
  - [ ] `ChainAdapter` is abstract — cannot instantiate directly
  - [ ] `ChainRegistry().get_adapter(Chain.ETHEREUM)` → returns EtherscanAdapter
  - [ ] `ChainRegistry().get_adapter(Chain.KADENA)` → returns None + logs warning
  - [ ] `pytest tests/test_chain_registry.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Registry dispatches to correct adapter
    Tool: Bash
    Steps:
      1. Run `python -c "from kryptoskatt.chains import get_registry; r = get_registry(); print(r.get_adapter(Chain.ETHEREUM).__class__.__name__)"` — expect 'EtherscanAdapter'
      2. Run `python -c "from kryptoskatt.chains import get_registry; r = get_registry(); print(r.get_adapter(Chain.SOLANA).__class__.__name__)"` — expect 'SolscanAdapter'
      3. Run `python -c "from kryptoskatt.chains import get_registry; r = get_registry(); print(r.get_adapter(Chain.KADENA))"` — expect 'None'
    Expected Result: Correct adapter per chain, None for unsupported
    Evidence: .sisyphus/evidence/task-11-chain-registry.txt

  Scenario: Unsupported chains logged as warnings
    Tool: Bash
    Steps:
      1. Run registry.fetch_all with a KADENA wallet, capture log output
      2. Verify warning message contains chain name and address
    Expected Result: Warning logged, no exception raised
    Evidence: .sisyphus/evidence/task-11-unsupported-chain.txt
  ```

  **Commit**: YES (groups with Tasks 9, 10)
  - Message: `feat(chain): blockchain adapters for Etherscan v2 and Solscan v2`
  - Files: `src/kryptoskatt/chains/base.py, src/kryptoskatt/chains/registry.py, src/kryptoskatt/chains/__init__.py, tests/test_chain_registry.py`
  - Pre-commit: `pytest tests/test_chain_registry.py`

---

- [ ] 12. CoinGecko Price Service + Caching

  **What to do**:
  - Create `src/kryptoskatt/services/price.py` — `PriceService` class
  - Implement `get_price_sek(coin_id: str, date: date) -> Decimal | None`:
    - First check PriceCache table (DB) — if cached, return immediately
    - If not cached: call CoinGecko API `GET /coins/{id}/history?date={DD-MM-YYYY}&localization=false`
    - Extract `market_data.current_price.sek` from response
    - If SEK not available: get USD price + fetch Riksbanken USD/SEK rate for that date as fallback
    - Save to PriceCache table with source (COINGECKO or MANUAL)
    - Return Decimal price
  - Implement `get_prices_batch(requests: list[tuple[str, date]]) -> dict[tuple[str, date], Decimal | None]`:
    - Batch multiple price lookups
    - Check cache first for ALL requests, only API-call for cache misses
    - Rate limit: max 5 calls/min for free tier (configurable)
    - Sleep between calls to respect rate limit
  - Create coin ID mapping: common coins to CoinGecko IDs:
    - SOL → `solana`, ETH → `ethereum`, XRP → `ripple`, BTC → `bitcoin`, BNB → `binancecoin`
    - VET → `vechain`, KDA → `kadena`, TRX → `tron`, POL → `matic-network`
    - HNT → `helium`, PEAQ → `peaq-2` (verify), ALEO → `aleo`
    - GEOD → may not exist on CoinGecko — return None, flag as "price not found"
  - Handle API errors gracefully: 429 (rate limit) → exponential backoff, 404 → None + log
  - CoinGecko date format is `DD-MM-YYYY` (NOT ISO format!)
  - All prices as Decimal
  - Write tests with mocked API responses

  **Must NOT do**:
  - Do NOT hardcode API key (CoinGecko free tier may not need one, but support COINGECKO_API_KEY env var)
  - Do NOT make uncached API calls for the same (coin, date) twice
  - Do NOT use float for prices
  - Do NOT fail the entire batch if one coin price is unavailable — return None for that coin

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: External API with rate limiting, caching layer, fallback strategy, batch optimization
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6-11, 13)
  - **Blocks**: Task 16 (GAV engine needs prices)
  - **Blocked By**: Task 2 (needs PriceCache model)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:350` — API reference note about price lookups
  - **API/Type References**:
    - `src/kryptoskatt/models:PriceCache` — DB cache model (coin_id, date, price_sek, source)
    - `src/kryptoskatt/enums.py:PriceSource` — COINGECKO, MANUAL, EXCHANGE_REPORTED
  - **External References**:
    - CoinGecko API: https://docs.coingecko.com/reference/coins-id-history — Historical price endpoint
    - Riksbanken API: https://www.riksbank.se/sv/statistik/rantor-och-valutakurser/ — USD/SEK fallback
  - **WHY Each Reference Matters**:
    - CoinGecko is date-based (00:00 UTC) — sufficient accuracy for tax reporting
    - PriceCache DB model ensures we never call the API twice for the same (coin, date) pair
    - Riksbanken provides official SEK exchange rates — useful as USD→SEK conversion fallback
    - GEOD and other DePIN tokens may NOT be on CoinGecko — must handle None gracefully and flag for manual input

  **Acceptance Criteria**:
  - [ ] `PriceService().get_price_sek('ethereum', date(2024, 6, 15))` → returns Decimal (mocked)
  - [ ] Second call for same (coin, date) → returns from cache (no API call)
  - [ ] Unknown coin → returns None (not exception)
  - [ ] Rate limit respected: `time.sleep` between API calls
  - [ ] `pytest tests/test_price_service.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Price lookup with caching
    Tool: Bash
    Preconditions: DB running, PriceCache table exists, mocked CoinGecko response
    Steps:
      1. First call: `get_price_sek('ethereum', date(2024, 6, 15))` — expect API call + DB insert
      2. Second call: same args — expect cache hit (verify no HTTP call made)
      3. Verify returned price is Decimal type
    Expected Result: Cache hit on second call, Decimal prices
    Evidence: .sisyphus/evidence/task-12-price-cache.txt

  Scenario: Unknown coin returns None
    Tool: Bash
    Steps:
      1. Call `get_price_sek('totally-fake-coin', date(2024, 1, 1))` with mocked 404 response
      2. Verify returns None, does not raise exception
      3. Verify warning is logged
    Expected Result: Graceful None return, no crash
    Evidence: .sisyphus/evidence/task-12-unknown-coin.txt

  Scenario: Batch price lookup optimizes API calls
    Tool: Bash
    Steps:
      1. Pre-populate cache with 2 of 4 requested (coin, date) pairs
      2. Call get_prices_batch with all 4
      3. Verify only 2 API calls made (for cache misses)
    Expected Result: Cache utilized, minimal API calls
    Evidence: .sisyphus/evidence/task-12-batch-optimization.txt
  ```

  **Commit**: YES
  - Message: `feat(price): CoinGecko price service with caching`
  - Files: `src/kryptoskatt/services/price.py, tests/test_price_service.py`
  - Pre-commit: `pytest tests/test_price_service.py`

---

- [ ] 13. CLI Import + Fetch Commands

  **What to do**:
  - Create `src/kryptoskatt/cli/import_cmd.py` — `kryptoskatt import` command:
    - `kryptoskatt import --file <path> --platform <coinbase|crypto_com|mexc>`
    - Auto-detect platform if `--platform` not given (inspect headers)
    - Select correct parser based on platform
    - Create ImportBatch record in DB (filename, platform, timestamp)
    - Parse file → create Transaction records in DB
    - Report: "Imported N transactions, M errors" with error details
    - Support `--dry-run` flag: parse and show preview without saving to DB
  - Create `src/kryptoskatt/cli/fetch_cmd.py` — `kryptoskatt fetch` command:
    - `kryptoskatt fetch --address <addr> --chain <chain>` — fetch single address
    - `kryptoskatt fetch --all` — fetch all registered wallets (from wallet registry)
    - Use ChainRegistry to dispatch to correct adapter
    - Create ImportBatch for on-chain fetches (platform=ON_CHAIN)
    - Save fetched transactions to DB
    - Report: "Fetched N transactions from chain X for address Y"
    - Handle unsupported chains: skip with warning
  - Wire both commands into main Typer app
  - Write integration tests (with mocked DB + mocked API for fetch)

  **Must NOT do**:
  - Do NOT implement calculate/report logic here — just import and store
  - Do NOT call price APIs during import — prices are resolved at calculate time
  - Do NOT skip error reporting — user needs to know about failed rows

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: CLI wiring with parser dispatch, DB operations, error reporting
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6-12)
  - **Blocks**: None directly (but import must work before Wave 3 makes sense)
  - **Blocked By**: Tasks 2, 5 (needs DB models + wallet registry)

  **References**:
  - **Pattern References**:
    - `src/kryptoskatt/cli/wallet.py` — Follow same CLI structure/patterns (Typer commands)
    - `src/kryptoskatt/parsers/coinbase.py` — Parser interface to dispatch to
    - `src/kryptoskatt/chains/registry.py` — ChainRegistry for fetch dispatch
  - **API/Type References**:
    - `src/kryptoskatt/models:ImportBatch` — Create batch record per import/fetch
    - `src/kryptoskatt/models:Transaction` — Store parsed transactions
  - **WHY Each Reference Matters**:
    - wallet.py CLI pattern ensures consistent command structure across the CLI
    - Both parsers and chain adapters have the same output type (TransactionCreate) — DB storage logic is shared

  **Acceptance Criteria**:
  - [ ] `kryptoskatt import --file tests/fixtures/coinbase_sample.csv --platform coinbase` → transactions in DB
  - [ ] `kryptoskatt import --dry-run --file tests/fixtures/coinbase_sample.csv --platform coinbase` → shows preview, no DB writes
  - [ ] `kryptoskatt fetch --all` → fetches for all registered wallets (mocked API)
  - [ ] `pytest tests/test_cli_import.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Import Coinbase CSV via CLI
    Tool: Bash
    Preconditions: DB running, parsers working, sample CSV exists
    Steps:
      1. Run `kryptoskatt import --file tests/fixtures/coinbase_sample.csv --platform coinbase` — expect success message with count
      2. Run `python -c "from kryptoskatt.models import Transaction; from kryptoskatt.config import get_session; s=get_session(); print(s.query(Transaction).count())"` — expect N > 0
    Expected Result: Transactions stored in database
    Failure Indicators: Zero transactions in DB, parser errors, CLI crash
    Evidence: .sisyphus/evidence/task-13-import-cli.txt

  Scenario: Dry run shows preview without DB writes
    Tool: Bash
    Steps:
      1. Run `kryptoskatt import --dry-run --file tests/fixtures/coinbase_sample.csv --platform coinbase`
      2. Verify output shows transaction preview
      3. Query DB — expect no new transactions from this run
    Expected Result: Preview displayed, zero DB side effects
    Evidence: .sisyphus/evidence/task-13-dry-run.txt

  Scenario: Fetch with unsupported chain skips gracefully
    Tool: Bash
    Steps:
      1. Register a wallet with Chain.KADENA (unsupported)
      2. Run `kryptoskatt fetch --all`
      3. Verify warning about unsupported chain in output, no crash
    Expected Result: Warning logged, other wallets still fetched
    Evidence: .sisyphus/evidence/task-13-unsupported-fetch.txt
  ```

  **Commit**: YES
  - Message: `feat(cli): import and fetch CLI commands`
  - Files: `src/kryptoskatt/cli/import_cmd.py, src/kryptoskatt/cli/fetch_cmd.py, tests/test_cli_import.py`
  - Pre-commit: `pytest tests/test_cli_import.py`

---

### Wave 3 — Calculation + Reports (after Wave 2)

- [ ] 14. Deduplication Engine — tx_hash Based

  **What to do**:
  - Create `src/kryptoskatt/engine/dedup.py` — `DeduplicationEngine` class
  - Core logic: find transactions that appear in BOTH CSV imports AND on-chain fetches
  - Primary dedup key: `tx_hash` — if two Transaction records share the same non-null tx_hash, they are duplicates
  - Secondary dedup heuristic (when tx_hash is null): match on (coin, amount, timestamp within 5 min window)
  - When duplicate found:
    - Mark the CSV-imported version as `is_duplicate = True` (prefer on-chain version as canonical)
    - Preserve raw_payload on both for audit trail
    - Log: "Duplicate found: tx_hash={hash}, keeping on-chain version"
  - Implement `deduplicate_all(session=None) -> DeduplicationReport`:
    - `DeduplicationReport`: total_checked, exact_matches (tx_hash), heuristic_matches, kept_count, removed_count
  - Handle edge cases:
    - MEXC TxID with `:NNN` suffix (e.g., `O02IiV-...:010`) — strip suffix before matching
    - Same tx_hash but different event_type (e.g., CSV says BUY, on-chain says TRANSFER_IN) — keep on-chain classification
  - Write TDD tests: create known duplicate pairs, verify dedup marks correct one

  **Must NOT do**:
  - Do NOT delete duplicate records — only mark with `is_duplicate = True`
  - Do NOT deduplicate transfers between own wallets (that's Task 15)
  - Do NOT modify amounts during dedup

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex matching logic with edge cases (TxID suffixes, heuristic matching, audit trail)
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 15)
  - **Blocks**: Task 16 (GAV engine needs clean data)
  - **Blocked By**: Tasks 6-10 (needs imported + fetched transactions)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:174-182` — Transfer matching heuristic concept (adapt for dedup: tx_hash match, then time+amount window)
    - `systemdesign.md:290-291` — MEXC TxID with `:010` suffix: `O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM:010`
    - `systemdesign.md:278-279` — Same KDA withdrawal appears in Crypto.com AND MEXC deposits — this is a cross-platform dedup case
  - **API/Type References**:
    - `src/kryptoskatt/models:Transaction` — `is_duplicate` field, `tx_hash` field
  - **WHY Each Reference Matters**:
    - The MEXC TxID suffix is a REAL example from user's data — line 290 shows `O02IiV-...KuM:010` which must match the base hash without `:010`
    - Lines 278-279 show a KDA withdrawal from Crypto.com that appears as a deposit in MEXC — same tx_hash, must be deduped

  **Acceptance Criteria**:
  - [ ] Two transactions with same tx_hash → one marked `is_duplicate = True`
  - [ ] MEXC TxID with `:NNN` suffix matches base hash
  - [ ] Heuristic match: (coin, amount, timestamp ±5min) when tx_hash is null
  - [ ] Report shows exact_matches vs heuristic_matches count
  - [ ] `pytest tests/test_dedup.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Exact tx_hash dedup
    Tool: Bash
    Preconditions: DB with two Transaction records sharing tx_hash '0xABC123'
    Steps:
      1. Insert CSV-sourced tx (source_platform='coinbase', tx_hash='0xABC123')
      2. Insert on-chain tx (source_platform='on_chain', tx_hash='0xABC123')
      3. Run `DeduplicationEngine().deduplicate_all()`
      4. Query DB: verify CSV version has is_duplicate=True, on-chain version has is_duplicate=False
    Expected Result: CSV version marked as duplicate, on-chain kept as canonical
    Evidence: .sisyphus/evidence/task-14-exact-dedup.txt

  Scenario: MEXC TxID suffix stripping
    Tool: Bash
    Steps:
      1. Insert tx with tx_hash='O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM:010'
      2. Insert tx with tx_hash='O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM'
      3. Run dedup — expect match
    Expected Result: Suffix stripped, records matched as duplicates
    Evidence: .sisyphus/evidence/task-14-mexc-suffix.txt
  ```

  **Commit**: YES (groups with Task 15)
  - Message: `feat(engine): deduplication and transfer matching`
  - Files: `src/kryptoskatt/engine/dedup.py, tests/test_dedup.py`
  - Pre-commit: `pytest tests/test_dedup.py`

---

- [ ] 15. Transfer Matching — Own Wallet Detection

  **What to do**:
  - Create `src/kryptoskatt/engine/transfers.py` — `TransferMatcher` class
  - Core logic: identify TRANSFER_OUT + TRANSFER_IN pairs that represent transfers between user's OWN wallets (non-taxable)
  - Step 1: Get all user's addresses from WalletService.get_my_addresses()
  - Step 2: For each TRANSFER_OUT:
    - If `to_address` matches one of user's addresses → likely own-wallet transfer
    - Find matching TRANSFER_IN with same (coin, ±amount, timestamp within 30 min, from_address matches sending wallet)
    - Create TransferLink record: tx_out_id, tx_in_id, match_method (TX_HASH or AMOUNT_TIME), confidence
  - Match methods (priority order):
    1. TX_HASH: same tx_hash on both sides (highest confidence)
    2. AMOUNT_TIME: same coin, matching amounts (±fee tolerance), timestamp within 30min
    3. Unmatched: TRANSFER_OUT to unknown address → leave as-is (could be external withdrawal)
  - Handle fee differences: withdrawal of 1.0 ETH may arrive as 0.999 ETH — allow small delta
  - Important: matched transfers should NOT be taxed (they are just moves between own wallets)
  - Generate `TransferMatchReport`: total_checked, matched, unmatched, ambiguous
  - Write TDD tests

  **Must NOT do**:
  - Do NOT modify the underlying transactions — only create TransferLink records
  - Do NOT auto-match ambiguous cases — flag them for review
  - Do NOT delete any records

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex matching logic with fee tolerance, multiple match strategies, confidence scoring
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 14)
  - **Blocks**: Task 16 (GAV engine needs to know which transfers are non-taxable)
  - **Blocked By**: Tasks 5, 6-10 (needs wallet registry + imported transactions)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:174-182` — Transfer matching heuristic: `tx_hash match` > `(coin, amount, timestamp within X min)` > `needs_review`
    - `systemdesign.md:270-272` — Coinbase Send to `5LWTG...eDgHg` which is user's Solana wallet — real example of own-wallet transfer
    - `systemdesign.md:294-299` — MEXC withdrawals to user's addresses (Polygon `0x85fB22b3...`, Solana `CAGfWWX...`)
  - **API/Type References**:
    - `src/kryptoskatt/models:TransferLink` — Link record between matched out/in transactions
    - `src/kryptoskatt/services/wallet.py:WalletService.get_my_addresses()` — Set of (address, chain) for ownership check
  - **WHY Each Reference Matters**:
    - systemdesign.md line 270 shows a real Send from Coinbase to user's Solana address — this must be matched as own-wallet transfer
    - MEXC withdrawal addresses (lines 294-299) are the user's wallet addresses — these transfers are non-taxable
    - TransferLink model records the match with confidence level — ambiguous matches are flagged

  **Acceptance Criteria**:
  - [ ] TRANSFER_OUT to own wallet + matching TRANSFER_IN → TransferLink created
  - [ ] TX_HASH match has higher confidence than AMOUNT_TIME match
  - [ ] TRANSFER_OUT to unknown address → no TransferLink (left as potential sale/withdrawal)
  - [ ] Fee tolerance: 1.0 ETH out + 0.999 ETH in → still matches
  - [ ] `pytest tests/test_transfers.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Own-wallet transfer matched by tx_hash
    Tool: Bash
    Preconditions: DB with TRANSFER_OUT (tx_hash=0xABC, to_address=user_wallet) and TRANSFER_IN (tx_hash=0xABC)
    Steps:
      1. Register both addresses as user's wallets
      2. Run TransferMatcher().match_all()
      3. Query TransferLink table — expect 1 record with match_method=TX_HASH
    Expected Result: Transfer linked with high confidence
    Evidence: .sisyphus/evidence/task-15-txhash-match.txt

  Scenario: Transfer to external address not matched
    Tool: Bash
    Steps:
      1. Insert TRANSFER_OUT to address NOT in wallet registry
      2. Run matcher
      3. Verify no TransferLink created for this transaction
    Expected Result: External transfers left unmatched (potential taxable event)
    Evidence: .sisyphus/evidence/task-15-external-transfer.txt
  ```

  **Commit**: YES (groups with Task 14)
  - Message: `feat(engine): deduplication and transfer matching`
  - Files: `src/kryptoskatt/engine/transfers.py, tests/test_transfers.py`
  - Pre-commit: `pytest tests/test_transfers.py`

---

- [ ] 16. GAV Calculation Engine — TDD (Core Tax Logic)

  **What to do**:
  - Create `src/kryptoskatt/engine/gav.py` — `GavEngine` class
  - **TDD WORKFLOW**: Write failing tests FIRST, then implement to pass
  - Core algorithm — Genomsnittsmetoden (GAV / Average Cost Method):
    - Maintain per-coin state: `total_units: Decimal`, `total_cost_sek: Decimal`
    - GAV per unit = `total_cost_sek / total_units` (recalculated after each acquisition)
  - Event processing (chronological order, ALL events from all time):
    - **BUY / SWAP_IN / REWARD**: Acquisition
      - `total_units += amount`
      - `total_cost_sek += (amount * price_sek) + fee_sek`
      - For REWARD: cost_basis = market value at receipt (price_sek * amount)
      - Recalculate GAV: `gav = total_cost_sek / total_units`
    - **SELL / SWAP_OUT**: Disposal (taxable event)
      - `proceeds_sek = amount * price_sek - fee_sek`
      - `cost_basis_sek = amount * current_gav`
      - `gain_loss_sek = proceeds_sek - cost_basis_sek`
      - `total_units -= amount`
      - `total_cost_sek -= cost_basis_sek`
      - Create `Disposal` record with all values
    - **TRANSFER_IN / TRANSFER_OUT**: Non-taxable (if matched as own-wallet transfer via TransferLink)
      - Skip for GAV calculation (units and cost don't change)
      - BUT: transfer fees ARE deductible — add fee_sek to cost basis if fee paid in base_coin
    - **FEE (standalone)**: Deductible
      - May reduce total_cost_sek or create tiny disposal
  - Create GavLedger entries for EVERY event: snapshot of GAV state after processing
  - Implement `calculate(year: int | None = None) -> CalculationResult`:
    - Process ALL events from the beginning (for correct cumulative GAV)
    - If year specified: only create Disposal records for events within that year
    - Return: `CalculationResult(disposals, gav_snapshots, warnings)`
  - Handle edge cases:
    - Unknown cost basis (no price_sek): use 0 SEK, flag as warning
    - Selling more than owned: flag as warning, proceed with available GAV
    - Zero units after full sell: reset GAV to 0
    - Multiple events at same timestamp: process acquisitions before disposals
  - **All arithmetic MUST use Decimal** — NEVER float
  - Write comprehensive TDD test suite:
    - Simple buy + sell
    - Multiple buys at different prices + sell (GAV averaging)
    - Swap (SWAP_OUT + SWAP_IN = two events)
    - Reward followed by sell
    - Transfer (no tax impact)
    - Unknown cost basis (0 SEK)
    - Full sell + rebuy (GAV reset)
    - Multi-year: events in 2023 + 2024, report only 2024 disposals

  **Must NOT do**:
  - Do NOT use float — Decimal ONLY for all arithmetic
  - Do NOT implement FIFO/LIFO — GAV (genomsnittsmetoden) ONLY as required by Skatteverket
  - Do NOT skip events from prior years — GAV is cumulative from first ever acquisition
  - Do NOT apply the 70% loss deduction — that's Skatteverket's job when processing K4
  - Do NOT round intermediate values — only round final K4 output to öre (2 decimal places)

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain`
    - Reason: Core tax calculation logic requiring mathematical precision, extensive TDD, edge case handling
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on multiple Wave 2 + Wave 3 outputs
  - **Parallel Group**: Sequential within Wave 3
  - **Blocks**: Tasks 17, 19, 21, 22
  - **Blocked By**: Tasks 3 (schemas), 12 (price service), 14 (dedup), 15 (transfer matching)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:165-171` — Original calculate algorithm concept: sort chronologically, build GAV-ledger, create Disposals
  - **API/Type References**:
    - `src/kryptoskatt/models:Disposal` — Output: tax_year, coin, sell_timestamp, proceeds, cost_basis, gain_loss, gav_at_disposal
    - `src/kryptoskatt/models:GavLedger` — Audit trail: coin, timestamp, event_type, amount_change, total_amount, total_cost, gav_per_unit
    - `src/kryptoskatt/models:TransferLink` — Check if TRANSFER is matched (non-taxable)
    - `src/kryptoskatt/services/price.py:PriceService` — Get price_sek for each event
  - **External References**:
    - Skatteverket GAV guide: https://www.skatteverket.se/privat/skatter/vardepapper/andratillgangar/kryptovalutor.4.15532c7b1442f256bae11b60.html
  - **WHY Each Reference Matters**:
    - systemdesign.md algorithm concept is the starting point but simplified — we process ALL events chronologically, not per-session
    - Disposal model must capture GAV-at-disposal for audit trail (Skatteverket may ask)
    - GavLedger provides complete history of how GAV evolved — required for 10-year retention
    - TransferLink determines which transfers are non-taxable — unmatched TRANSFER_OUT could be a gift/payment (taxable)
    - Skatteverket page confirms: genomsnittsmetoden is mandatory, fees in cost basis, all disposals reported

  **Acceptance Criteria**:
  - [ ] TDD: tests written BEFORE implementation (verify test file committed first or simultaneously)
  - [ ] Simple buy+sell: Buy 1 ETH @ 20000 SEK, Sell 0.5 ETH @ 25000 → gain = 12500 - 10000 = 2500 SEK
  - [ ] GAV averaging: Buy 1 ETH @ 20000, Buy 1 ETH @ 30000, GAV = 25000. Sell 1 → cost_basis = 25000
  - [ ] Swap: SWAP_OUT 1 BTC + SWAP_IN 10 ETH → disposal of BTC + acquisition of ETH
  - [ ] Reward: Receive 100 GEOD @ 5 SEK/GEOD → cost_basis = 500 SEK, total_units += 100
  - [ ] Transfer: own-wallet transfer → no disposal, no GAV change
  - [ ] Unknown price: 0 SEK cost basis, warning flag
  - [ ] Multi-year: 2023 events affect GAV, 2024 disposals reported
  - [ ] All arithmetic uses Decimal (verified by test)
  - [ ] `pytest tests/test_gav.py -v` → ALL PASS (10+ test cases)

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: GAV calculation with real-world scenario
    Tool: Bash
    Preconditions: DB with test transactions (mix of BUY, SELL, SWAP, REWARD)
    Steps:
      1. Create test data: 3 ETH buys at different prices, 1 sell, 1 reward
      2. Run `GavEngine().calculate(year=2024)`
      3. Verify disposal has correct proceeds, cost_basis (using GAV), gain_loss
      4. Verify GavLedger has entries for each event showing GAV progression
      5. Manually calculate expected values and compare
    Expected Result: GAV matches manual calculation, disposals correct
    Failure Indicators: Float rounding errors, wrong GAV formula, missing events
    Evidence: .sisyphus/evidence/task-16-gav-calculation.txt

  Scenario: Multi-year GAV continuity
    Tool: Bash
    Steps:
      1. Insert Buy ETH in 2023 @ 15000 SEK
      2. Insert Buy ETH in 2024 @ 25000 SEK
      3. Insert Sell ETH in 2024
      4. Calculate for year=2024
      5. Verify cost_basis uses GAV that includes 2023 buy (not just 2024)
    Expected Result: GAV is cumulative, includes all historical acquisitions
    Evidence: .sisyphus/evidence/task-16-multi-year-gav.txt

  Scenario: Zero cost basis with warning
    Tool: Bash
    Steps:
      1. Insert Sell GEOD (no prior Buy, no price available)
      2. Calculate — expect disposal with cost_basis=0 and warning
    Expected Result: 0 SEK cost basis, flagged in warnings
    Evidence: .sisyphus/evidence/task-16-zero-cost-basis.txt
  ```

  **Commit**: YES
  - Message: `feat(engine): GAV calculation engine with TDD test suite`
  - Files: `src/kryptoskatt/engine/gav.py, tests/test_gav.py`
  - Pre-commit: `pytest tests/test_gav.py -v`

---

- [ ] 17. K4 Report Generator — Per Year, Per Asset

  **What to do**:
  - Create `src/kryptoskatt/reports/k4.py` — `K4ReportGenerator` class
  - Implement `generate(year: int) -> K4Report`:
    - Query all Disposal records for the given tax year
    - Group by coin
    - Per coin: sum proceeds_sek, sum cost_basis_sek, calculate gain_loss_sek
    - Create K4SummaryRow per coin
    - Calculate totals: total_gains (sum of positive gain_loss), total_losses (sum of negative gain_loss)
    - Return K4Report with year, rows, total_gains, total_losses
  - Implement `export_csv(report: K4Report, output_path: Path)`:
    - Format: `Tillgång,Försäljningspris SEK,Omkostnadsbelopp SEK,Vinst/Förlust SEK`
    - One row per coin
    - Total row at bottom
    - Swedish column headers (Skatteverket format)
  - Implement `export_json(report: K4Report, output_path: Path)`:
    - Structured JSON with same data
  - Implement `generate_full_transaction_list(year: int, output_path: Path)`:
    - Every disposal with details: timestamp, coin, amount, proceeds, cost_basis, gain_loss, GAV at disposal
    - Sorted chronologically
    - This is the "underlag" Skatteverket may request
  - Round final SEK values to 2 decimal places (kr och öre) for report output only
  - Write tests: verify K4 output matches expected values from known disposals

  **Must NOT do**:
  - Do NOT apply 70% loss deduction — Skatteverket calculates this
  - Do NOT generate SRU format (out of scope)
  - Do NOT round intermediate values — only round in final output

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Report generation with Swedish formatting, multiple output formats, tax-specific requirements
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (after Task 16)
  - **Blocks**: Tasks 18, 19
  - **Blocked By**: Task 16 (needs Disposal records from GAV engine)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:141-147` — Original export endpoints concept: k4-summary.json, k4-summary.csv, disposals.csv, unmatched-transfers.csv
    - `systemdesign.md:54` — K4Summary entity: per coin proceeds, cost_basis, gain_loss
  - **API/Type References**:
    - `src/kryptoskatt/schemas.py:K4Report, K4SummaryRow` — Output data structures
    - `src/kryptoskatt/models:Disposal` — Input data: all disposals for the year
  - **External References**:
    - Skatteverket K4 blankett avsnitt D: https://www.skatteverket.se/privat/deklaration/bilagor/k4.4.233f91f71260075abe8800020817.html
  - **WHY Each Reference Matters**:
    - K4 avsnitt D requires: per tillgång (asset), försäljningspris and omkostnadsbelopp
    - CSV export is the deliverable the user will use to fill in K4
    - Full transaction list is the "underlag" required for 10-year retention

  **Acceptance Criteria**:
  - [ ] `K4ReportGenerator().generate(year=2024)` → K4Report with rows per coin
  - [ ] CSV export has Swedish headers: `Tillgång,Försäljningspris SEK,Omkostnadsbelopp SEK,Vinst/Förlust SEK`
  - [ ] Values rounded to 2 decimal places in output
  - [ ] Full transaction list includes all disposals chronologically
  - [ ] `pytest tests/test_k4_report.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Generate K4 CSV for 2024
    Tool: Bash
    Preconditions: Disposals in DB for 2024 (from GAV engine)
    Steps:
      1. Run `K4ReportGenerator().generate(2024)` then `export_csv(report, 'k4_2024.csv')`
      2. Read k4_2024.csv — verify Swedish headers
      3. Verify per-coin rows with correct sums
      4. Verify total row at bottom
    Expected Result: Valid K4 CSV with Swedish formatting
    Evidence: .sisyphus/evidence/task-17-k4-csv.txt

  Scenario: K4 for year with no disposals
    Tool: Bash
    Steps:
      1. Generate K4 for year with zero disposals
      2. Verify empty report (headers but no data rows, totals = 0)
    Expected Result: Empty but valid report
    Evidence: .sisyphus/evidence/task-17-empty-year.txt
  ```

  **Commit**: YES (groups with Task 18)
  - Message: `feat(report): K4 report generation and CLI commands`
  - Files: `src/kryptoskatt/reports/k4.py, tests/test_k4_report.py`
  - Pre-commit: `pytest tests/test_k4_report.py`

---

- [ ] 18. CLI Calculate + Report Commands

  **What to do**:
  - Create `src/kryptoskatt/cli/calculate_cmd.py` — `kryptoskatt calculate` command:
    - `kryptoskatt calculate --year 2024`
    - Runs: dedup → transfer matching → price resolution → GAV calculation
    - Output: summary to stdout (total disposals, gains, losses per coin)
    - Stores Disposal + GavLedger records in DB
  - Create `src/kryptoskatt/cli/report_cmd.py` — `kryptoskatt report` command:
    - `kryptoskatt report --year 2024 --format csv` → writes `k4_2024.csv`
    - `kryptoskatt report --year 2024 --format json` → writes `k4_2024.json`
    - `kryptoskatt report --year 2024 --full` → writes full transaction list
    - Default output directory: `./reports/` (create if not exists)
  - Wire both commands into main Typer app
  - `calculate` should show progress: "Processing 500 transactions...", "Resolving prices...", "Creating disposals..."
  - Error handling: if price service fails for some coins, continue and show warnings

  **Must NOT do**:
  - Do NOT re-implement calculation logic — delegate to GavEngine
  - Do NOT re-implement report logic — delegate to K4ReportGenerator
  - Do NOT skip the dedup/transfer matching steps

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: CLI wiring that delegates to existing engines/services
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (after Tasks 16, 17)
  - **Blocks**: None directly
  - **Blocked By**: Tasks 16, 17

  **References**:
  - **Pattern References**:
    - `src/kryptoskatt/cli/wallet.py` — CLI structure pattern
    - `src/kryptoskatt/cli/import_cmd.py` — Progress output pattern
  - **API/Type References**:
    - `src/kryptoskatt/engine/gav.py:GavEngine` — Calculate logic
    - `src/kryptoskatt/engine/dedup.py:DeduplicationEngine` — Dedup step
    - `src/kryptoskatt/engine/transfers.py:TransferMatcher` — Transfer matching step
    - `src/kryptoskatt/reports/k4.py:K4ReportGenerator` — Report generation
  - **WHY Each Reference Matters**:
    - Each CLI command is a thin wrapper that orchestrates the engine components in correct order

  **Acceptance Criteria**:
  - [ ] `kryptoskatt calculate --year 2024` → shows summary, creates Disposal records
  - [ ] `kryptoskatt report --year 2024 --format csv` → creates `reports/k4_2024.csv`
  - [ ] `kryptoskatt report --year 2024 --full` → creates full transaction list file
  - [ ] `pytest tests/test_cli_calculate.py` → PASS

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: End-to-end calculate + report
    Tool: Bash
    Preconditions: DB with imported transactions, wallets registered
    Steps:
      1. Run `kryptoskatt calculate --year 2024` — expect summary output with gains/losses
      2. Run `kryptoskatt report --year 2024 --format csv` — expect file created
      3. Run `cat reports/k4_2024.csv` — verify headers and data present
    Expected Result: Full pipeline: calculate → report generation
    Failure Indicators: Missing Disposal records, empty CSV, calculation errors
    Evidence: .sisyphus/evidence/task-18-e2e-calculate.txt

  Scenario: Calculate shows progress and warnings
    Tool: Bash
    Steps:
      1. Insert transactions including one with unknown coin (no CoinGecko price)
      2. Run `kryptoskatt calculate --year 2024`
      3. Verify progress messages in stdout
      4. Verify warning about missing price in output
    Expected Result: Progress shown, warnings for missing prices, no crash
    Evidence: .sisyphus/evidence/task-18-calculate-warnings.txt
  ```

  **Commit**: YES (groups with Task 17)
  - Message: `feat(report): K4 report generation and CLI commands`
  - Files: `src/kryptoskatt/cli/calculate_cmd.py, src/kryptoskatt/cli/report_cmd.py, tests/test_cli_calculate.py`
  - Pre-commit: `pytest tests/test_cli_calculate.py`

---

### Wave 4 — UI + Polish (after Wave 3)

- [ ] 19. FastAPI Web Report + Jinja2 Templates

  **What to do**:
  - Create `src/kryptoskatt/web/app.py` — FastAPI app with Jinja2Responses:
    - `GET /` → dashboard: list available tax years (years that have Disposal records)
    - `GET /year/{year}` → K4 summary for that year: per-coin table with proceeds, cost_basis, gain_loss
    - `GET /year/{year}/transactions` → full transaction list for that year (paginated)
    - `GET /year/{year}/gav` → GAV history chart data (per-coin GAV over time)
    - `GET /year/{year}/issues` → flagged issues: missing prices, unmatched transfers, unknown cost basis
    - `GET /year/{year}/download/csv` → download K4 CSV file
    - `GET /year/{year}/download/json` → download K4 JSON file
  - Create Jinja2 templates in `src/kryptoskatt/web/templates/`:
    - `base.html` — layout with minimal CSS (use Pico CSS or Simple.css CDN for clean styling)
    - `dashboard.html` — year selector
    - `year_summary.html` — K4 table + totals + download buttons
    - `transactions.html` — sortable transaction table
    - `gav_history.html` — GAV per coin table (no JS charts needed, just a table)
    - `issues.html` — flagged problems list
  - No JavaScript frameworks — just HTML + minimal CSS
  - Read from DB directly (SQLAlchemy queries)
  - Serve static files for CSS

  **Must NOT do**:
  - Do NOT use React, Vue, Svelte, or any JS SPA framework
  - Do NOT add authentication/login
  - Do NOT build an API-first backend (Jinja2 templates render directly)
  - Do NOT add JavaScript charts — tables are sufficient

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: Web UI with templates, CSS styling, user-facing presentation
  - **Skills**: [`playwright`]
    - `playwright`: For QA scenario browser testing of the web UI

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (after Tasks 16, 17)
  - **Blocks**: Tasks 20, 21
  - **Blocked By**: Tasks 16, 17 (needs GAV calculations + K4 reports)

  **References**:
  - **Pattern References**:
    - `systemdesign.md:214-228` — Original frontend page list (adapt to Jinja2 templates: dashboard, review, results, export)
  - **API/Type References**:
    - `src/kryptoskatt/schemas.py:K4Report, K4SummaryRow` — Data structures for templates
    - `src/kryptoskatt/reports/k4.py:K4ReportGenerator` — Generate report data for templates
    - `src/kryptoskatt/models:Disposal, GavLedger, Transaction` — Query for data
  - **External References**:
    - FastAPI Jinja2: https://fastapi.tiangolo.com/advanced/templates/
    - Pico CSS: https://picocss.com/ — Classless CSS framework for clean default styling
  - **WHY Each Reference Matters**:
    - systemdesign.md page list provides the mental model for navigation (adapted from SPA to server-rendered)
    - Pico CSS provides clean styling without JS dependencies — perfect for simple server-rendered app

  **Acceptance Criteria**:
  - [ ] `uvicorn kryptoskatt.web.app:app` starts on port 8000
  - [ ] `GET /` → HTML with year links
  - [ ] `GET /year/2024` → HTML with K4 summary table
  - [ ] `GET /year/2024/download/csv` → downloads k4_2024.csv
  - [ ] No JavaScript frameworks in dependencies

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Web UI shows K4 summary
    Tool: Playwright (playwright skill)
    Preconditions: Server running on localhost:8000, Disposal records in DB for 2024
    Steps:
      1. Navigate to http://localhost:8000/
      2. Assert page contains heading with "KryptoSkatt"
      3. Assert link to year 2024 exists
      4. Click year 2024 link
      5. Assert page contains table with columns: Tillgång, Försäljningspris, Omkostnadsbelopp, Vinst/Förlust
      6. Assert at least one data row in table
      7. Take screenshot
    Expected Result: K4 summary table rendered with correct Swedish headers
    Failure Indicators: 404, empty table, missing columns, server error
    Evidence: .sisyphus/evidence/task-19-web-k4-summary.png

  Scenario: CSV download works from web UI
    Tool: Playwright (playwright skill)
    Steps:
      1. Navigate to http://localhost:8000/year/2024
      2. Click download CSV button/link
      3. Verify response is CSV with correct headers
    Expected Result: CSV file downloaded with correct content
    Evidence: .sisyphus/evidence/task-19-csv-download.txt
  ```

  **Commit**: YES (groups with Task 20)
  - Message: `feat(web): FastAPI web report with Jinja2 templates`
  - Files: `src/kryptoskatt/web/**, src/kryptoskatt/web/templates/**`
  - Pre-commit: `python -c "from kryptoskatt.web.app import app; print('OK')"`

---

- [ ] 20. CLI Serve Command + Docker Integration

  **What to do**:
  - Create `src/kryptoskatt/cli/serve_cmd.py` — `kryptoskatt serve` command:
    - `kryptoskatt serve [--host 0.0.0.0] [--port 8000]`
    - Starts uvicorn with the FastAPI app
    - Prints: "Web report available at http://localhost:8000"
  - Update `docker-compose.yml`:
    - Add port mapping: `8000:8000` for app service
    - Set default CMD to run the web server (or healthcheck on /)
  - Update Dockerfile CMD to run web server via gunicorn/uvicorn with workers:
    - `CMD ["uvicorn", "kryptoskatt.web.app:app", "--host", "0.0.0.0", "--port", "8000"]`
  - Add healthcheck endpoint: `GET /health` → returns 200 OK
  - Wire serve command into main Typer app

  **Must NOT do**:
  - Do NOT use Flask development server — use uvicorn
  - Do NOT add HTTPS/SSL (localhost only)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple CLI command + Docker config update
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (after Task 19)
  - **Blocks**: None
  - **Blocked By**: Task 19

  **References**:
  - **Pattern References**:
    - `src/kryptoskatt/cli/wallet.py` — CLI command pattern
    - `docker-compose.yml` — Existing Docker Compose config to update
  - **WHY Each Reference Matters**:
    - Docker Compose needs port mapping for the web UI to be accessible

  **Acceptance Criteria**:
  - [ ] `kryptoskatt serve` starts web server on port 8000
  - [ ] `curl http://localhost:8000/health` → 200 OK
  - [ ] `docker compose up` → web UI accessible on port 8000

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Serve command starts web server
    Tool: Bash
    Steps:
      1. Run `kryptoskatt serve --port 8001 &` in background
      2. Wait 3 seconds
      3. Run `curl -s http://localhost:8001/health` — expect 200
      4. Kill background process
    Expected Result: Server starts and responds to health check
    Evidence: .sisyphus/evidence/task-20-serve-health.txt

  Scenario: Docker Compose exposes web UI
    Tool: Bash
    Steps:
      1. Run `docker compose up -d`
      2. Wait for healthy status
      3. Run `curl -s http://localhost:8000/health` — expect 200
    Expected Result: Docker container serves web UI
    Evidence: .sisyphus/evidence/task-20-docker-web.txt
  ```

  **Commit**: YES (groups with Task 19)
  - Message: `feat(web): FastAPI web report with Jinja2 templates`
  - Files: `src/kryptoskatt/cli/serve_cmd.py, docker-compose.yml, Dockerfile`
  - Pre-commit: `curl -s http://localhost:8000/health`

---

- [ ] 21. GAV History Tracking + Visualization Data

  **What to do**:
  - Create `src/kryptoskatt/reports/gav_history.py` — `GavHistoryReport` class
  - Implement `generate(coin: str | None = None, year: int | None = None) -> list[GavSnapshot]`:
    - Query GavLedger entries
    - If coin specified: filter to that coin
    - If year specified: show only events within that year (but GAV values reflect cumulative history)
    - Return list of snapshots: timestamp, event_type, amount_change, total_units, total_cost, gav_per_unit
  - Add web template `gav_history.html`:
    - Table showing GAV progression per coin over time
    - Columns: Datum, Händelse, Ändring, Totalt antal, Total kostnad SEK, GAV/enhet SEK
    - Filter by coin (dropdown or URL parameter)
  - Add route `GET /year/{year}/gav/{coin}` for per-coin GAV history
  - This provides the audit trail required for Skatteverket

  **Must NOT do**:
  - Do NOT add JavaScript charts — tables only
  - Do NOT recalculate GAV — read from GavLedger (already calculated in Task 16)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Report generation + web template with data formatting
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Task 22)
  - **Blocks**: None
  - **Blocked By**: Tasks 16, 19 (needs GavLedger data + web app)

  **References**:
  - **API/Type References**:
    - `src/kryptoskatt/models:GavLedger` — GAV snapshot data source
    - `src/kryptoskatt/schemas.py:GavSnapshot` — Output schema
    - `src/kryptoskatt/web/app.py` — Add route to existing FastAPI app
  - **WHY Each Reference Matters**:
    - GavLedger is the pre-computed audit trail — this report just presents it
    - Web app already handles year-based routing — follow same pattern

  **Acceptance Criteria**:
  - [ ] `GavHistoryReport().generate(coin='ETH', year=2024)` → list of GavSnapshot
  - [ ] `GET /year/2024/gav/ETH` → HTML table with GAV history
  - [ ] Table shows Swedish headers: Datum, Händelse, Ändring, Totalt antal, GAV/enhet SEK

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: GAV history table shows progression
    Tool: Playwright (playwright skill)
    Preconditions: GavLedger entries for ETH in DB, web server running
    Steps:
      1. Navigate to http://localhost:8000/year/2024/gav/ETH
      2. Assert table exists with GAV progression rows
      3. Verify first row shows initial buy, subsequent rows show updated GAV
      4. Screenshot
    Expected Result: GAV history visible in table format
    Evidence: .sisyphus/evidence/task-21-gav-history.png
  ```

  **Commit**: YES (groups with Task 22)
  - Message: `feat(report): GAV history tracking and flagged issues report`
  - Files: `src/kryptoskatt/reports/gav_history.py, src/kryptoskatt/web/templates/gav_history.html`
  - Pre-commit: `pytest tests/test_gav_history.py`

---

- [ ] 22. Flagged Issues Report — Missing Prices, Unknown Cost Basis, Unmatched Transfers

  **What to do**:
  - Create `src/kryptoskatt/reports/issues.py` — `FlaggedIssuesReport` class
  - Collect and report all data quality issues:
    - **Missing prices**: Transactions where price_sek is None (CoinGecko didn't have price)
    - **Unknown cost basis**: Disposals where cost_basis = 0 SEK (no prior acquisition found)
    - **Unmatched transfers**: TRANSFER_OUT without a TransferLink (could be external withdrawal — potentially taxable)
    - **Heuristic dedup matches**: Deduplications done by heuristic (not tx_hash) — may need manual review
    - **Sell > hold warning**: Cases where sell amount exceeded known holdings
  - Implement `generate(year: int | None = None) -> FlaggedIssuesReport`:
    - Categorize issues by severity: ERROR (missing price on disposal), WARNING (unmatched transfer), INFO (heuristic dedup)
    - Include affected transaction details (timestamp, coin, amount, issue description)
  - Add web template `issues.html`:
    - Issues grouped by category
    - Color-coded severity
    - Actionable text: "This transaction has no market price. Add manual price via DB or re-run with updated CoinGecko mapping."
  - Add route `GET /year/{year}/issues` to web app
  - Add CLI command `kryptoskatt issues --year 2024` for terminal output

  **Must NOT do**:
  - Do NOT auto-fix issues — just report them
  - Do NOT suppress any issue category — show all

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Multiple issue categories, DB queries across tables, web template + CLI output
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Task 21)
  - **Blocks**: None
  - **Blocked By**: Tasks 14, 15, 16 (needs dedup, transfer matching, and GAV results)

  **References**:
  - **API/Type References**:
    - `src/kryptoskatt/models:Transaction` — Query for missing prices
    - `src/kryptoskatt/models:Disposal` — Query for zero cost basis
    - `src/kryptoskatt/models:TransferLink` — Find unmatched transfers
    - `src/kryptoskatt/engine/dedup.py` — Heuristic match records
  - **WHY Each Reference Matters**:
    - Each issue category maps to a specific model/table query
    - The user needs this report to know what manual fixes are required before final K4 submission

  **Acceptance Criteria**:
  - [ ] `FlaggedIssuesReport().generate(year=2024)` → report with categorized issues
  - [ ] Missing prices listed with transaction details
  - [ ] Unmatched transfers listed
  - [ ] `GET /year/2024/issues` → HTML with color-coded issue list
  - [ ] `kryptoskatt issues --year 2024` → terminal output with issue summary

  **QA Scenarios (MANDATORY):**
  ```
  Scenario: Issues report shows missing prices
    Tool: Bash
    Preconditions: DB with transaction where price_sek is NULL (e.g., GEOD with no CoinGecko data)
    Steps:
      1. Run `kryptoskatt issues --year 2024`
      2. Verify output lists the missing-price transaction with coin, date, amount
      3. Verify severity is ERROR
    Expected Result: Missing price flagged as ERROR with actionable description
    Evidence: .sisyphus/evidence/task-22-missing-prices.txt

  Scenario: Issues web page shows categorized issues
    Tool: Playwright (playwright skill)
    Preconditions: Issues exist in DB, web server running
    Steps:
      1. Navigate to http://localhost:8000/year/2024/issues
      2. Assert issue categories are displayed (ERROR, WARNING, INFO)
      3. Assert at least one issue listed with details
      4. Screenshot
    Expected Result: Categorized, color-coded issue list
    Evidence: .sisyphus/evidence/task-22-issues-web.png
  ```

  **Commit**: YES (groups with Task 21)
  - Message: `feat(report): GAV history tracking and flagged issues report`
  - Files: `src/kryptoskatt/reports/issues.py, src/kryptoskatt/web/templates/issues.html, src/kryptoskatt/cli/issues_cmd.py, tests/test_issues_report.py`
  - Pre-commit: `pytest tests/test_issues_report.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Rejection → fix → re-run.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m py_compile` on all modules + `ruff check .` + `pytest --tb=short`. Review all changed files for: `# type: ignore`, bare except, print() in prod code, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp). Verify all amounts use Decimal, not float.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill for web UI)
  Start from clean state (`docker compose down -v && docker compose up -d`). Import sample Coinbase CSV. Add a wallet address. Fetch on-chain. Run calculate for 2024. Generate K4 report. Open web UI. Verify K4 numbers match manual calculation. Test edge cases: unknown cost basis coin, duplicate tx_hash, own-wallet transfer. Save evidence to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes. Verify no auth system, no Redis, no SPA framework, no float arithmetic.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| After Tasks | Commit Message | Key Files |
|------------|---------------|-----------|
| 1 | `chore: project skeleton with Docker Compose and pytest setup` | pyproject.toml, Dockerfile, docker-compose.yml, .env.example |
| 2, 3 | `feat(db): database schema, SQLAlchemy models, and transaction types` | models/, alembic/, schemas/ |
| 4, 5 | `feat(wallet): wallet registry and test infrastructure` | tests/, cli/wallet.py |
| 6, 7, 8 | `feat(parsers): CSV/TSV parsers for Coinbase, Crypto.com, MEXC` | parsers/ |
| 9, 10, 11 | `feat(chain): blockchain adapters for Etherscan v2 and Solscan v2` | chains/ |
| 12 | `feat(price): CoinGecko price service with caching` | services/price.py |
| 13 | `feat(cli): import and fetch CLI commands` | cli/ |
| 14, 15 | `feat(engine): deduplication and transfer matching` | engine/ |
| 16 | `feat(engine): GAV calculation engine with TDD test suite` | engine/gav.py, tests/test_gav.py |
| 17, 18 | `feat(report): K4 report generation and CLI commands` | reports/, cli/ |
| 19, 20 | `feat(web): FastAPI web report with Jinja2 templates` | web/ |
| 21, 22 | `feat(report): GAV history tracking and flagged issues report` | reports/, web/ |

---

## Success Criteria

### Verification Commands
```bash
# All tests pass
pytest --tb=short                    # Expected: all green

# Docker builds and runs
docker compose build                 # Expected: success
docker compose up -d                 # Expected: services healthy

# CLI works end-to-end
kryptoskatt import --file tests/fixtures/coinbase_sample.csv --platform coinbase
kryptoskatt wallet add --address 0x123... --chain ethereum --mine
kryptoskatt calculate --year 2024
kryptoskatt report --year 2024 --format csv   # Expected: k4_2024.csv with per-asset summary

# Web report serves
kryptoskatt serve                    # Expected: http://localhost:8000 shows results
```

### Final Checklist
- [ ] All "Must Have" present — GAV correct, dedup works, transfers matched, historical reports, Decimal everywhere
- [ ] All "Must NOT Have" absent — no auth, no Redis, no SPA, no float, no hardcoded keys
- [ ] All tests pass (pytest)
- [ ] Docker Compose runs clean
- [ ] K4 report for 2024 generates correctly with sample data
- [ ] Web UI shows results, GAV history, flagged issues
