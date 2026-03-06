
## Task 16: GAV Calculation Engine

### Key Implementation Details

1. **GAV Algorithm (Genomsnittsmetoden)**: Maintains per-coin state with `total_units` and `total_cost_sek`. GAV = total_cost_sek / total_units.

2. **Event Processing Order**:
   - Chronological by timestamp
   - At same timestamp: acquisitions (BUY, SWAP_IN, REWARD) BEFORE disposals (SELL, SWAP_OUT)

3. **Transfer Handling**: Linked transfers via TransferLink are non-taxable - cost basis moves with the coins.

4. **Fee Handling**: Fees in same coin as transaction add to cost basis. Fees in SEK also add to cost basis.

5. **Decimal Arithmetic**: ALL arithmetic uses Decimal - never float.

6. **Year Filtering**: `calculate(year=2024)` only returns disposals from that year but processes ALL historical events for correct GAV calculation.

### Test Patterns Used

- In-memory SQLite with `Base.metadata.create_all(engine)`
- Helper functions `_create_tx()` and `_create_transfer_link()` for test data
- 15 comprehensive test cases covering all acceptance criteria

### Verification

- All 15 GAV tests pass
- Full test suite: 174 passed, 1 known failure (test_import_config)


# KryptoSkatt Learnings

## Task 1: Project Skeleton Creation

### Issues Encountered

1. **pyproject.toml corruption**: The edit tool caused duplication of TOML sections. Had to rewrite the entire file to fix "Cannot overwrite a value" TOML parsing error.

2. **Docker build failures**: 
   - First failure: Missing README.md referenced in pyproject.toml
   - Second failure: src directory not copied to builder stage
   - Third failure: pyproject.toml had duplicate entries causing TOML parsing error

3. **Docker compose issues**:
   - Initial CMD was `kryptoskatt --help` which exits immediately
   - Fixed by adding `command: sleep infinity` to keep container running

4. **Edit tool behavior**: Using edit on empty files fails. Must use write after removing the file, or use prepend on files with content.

### Key Decisions

1. **Multi-stage Dockerfile**: Used builder stage for dependencies, runtime stage for app
2. **Non-root user**: Created appuser with uid 1000 in runtime stage
3. **Python 3.12**: Pinned to slim-bookworm variant
4. **pydantic-settings**: Used BaseSettings with env_file=".env"
5. **PostgreSQL 16**: Used official postgres:16 image with healthcheck

### Verification Results

- Docker build: SUCCESS
- Docker compose up: SUCCESS (both db and app healthy)
- Config import test: SUCCESS (prints DATABASE_URL)
- CLI test: SUCCESS (shows help with all commands)
- Secret verification: SUCCESS (no API keys found in committed files)

### Project Structure Created

```
/home/pappa/codeprojects/crypto/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .env (gitignored)
├── .gitignore
├── src/kryptoskatt/
│   ├── __init__.py
│   ├── config.py
│   ├── cli/__init__.py (Typer app with 6 command stubs)
│   ├── models/__init__.py
│   ├── parsers/__init__.py
│   ├── chains/__init__.py
│   ├── engine/__init__.py
│   ├── services/__init__.py
│   ├── reports/__init__.py
│   └── web/__init__.py
└── tests/
    ├── __init__.py
    └── conftest.py
```

### Dependencies Installed

Runtime:
- fastapi, uvicorn[standard], sqlalchemy[asyncio], alembic, typer[all]
- httpx, python-dotenv, pydantic, pydantic-settings, psycopg2-binary, jinja2

Dev:
- pytest, pytest-asyncio, ruff, pytest-cov

## Task 2: Enums and Schemas

### Key Decisions

1. **StrEnum for enums**: Used `StrEnum` (Python 3.11+) for automatic string serialization - no `.value` calls needed
2. **Decimal for amounts**: All monetary values use `Decimal` from decimal module, never float
3. **Negative amounts allowed**: TransactionCreate accepts negative base_amount (valid for SELL, TRANSFER_OUT, SWAP_OUT, FEE)
4. **Pydantic v2**: Used `ConfigDict(from_attributes=True)` for SQLAlchemy compatibility

### Verification Results

- Enum imports: SUCCESS (Chain.SOLANA, Platform.COINBASE, EventType.REWARD)
- TransactionCreate with Decimal: SUCCESS
- K4Report imports: SUCCESS
- Negative amounts accepted: SUCCESS

### Files Created

- `src/kryptoskatt/enums.py` - Chain, Platform, EventType, MatchMethod, PriceSource
- `src/kryptoskatt/schemas.py` - TransactionCreate, TransactionRead, WalletCreate, WalletRead, K4SummaryRow, K4Report, GavSnapshot

#VQ|## Task 3: Alembic Docker Setup Fix
#SV|
#KH|### Issues Encountered
#HQ|
#PR|1. **Missing alembic files in Docker**: Initially only `src/` and `pyproject.toml` were copied to container, so `alembic.ini` and `alembic/` directory were missing
#QK|
#QK|2. **First edit mistake**: Accidentally removed `COPY src/ ./src/` from builder stage when adding alembic COPY commands, causing pip install to fail with "src does not exist"
#PN|
#KH|### Solution Applied
#HQ|
#PR|1. **Builder stage**: Added after pyproject.toml and src/:
#XZ|   ```dockerfile
#XZ|   COPY alembic.ini ./
#XZ|   COPY alembic/ ./alembic/
#XZ|   ```
#PK|
#PR|2. **Runtime stage**: Added after src/ and pyproject.toml:
#XZ|   ```dockerfile
#XZ|   COPY --chown=appuser:appgroup alembic.ini /home/appuser/
#XZ|   COPY --chown=appuser:appgroup alembic/ /home/appuser/alembic/
#XZ|   ```
#BQ|
#KH|### Verification Results
#HQ|
#PR|- `docker compose exec app alembic upgrade head`: SUCCESS
#XZ|- `docker compose exec app alembic downgrade base`: SUCCESS
#XZ|- `docker compose exec app alembic upgrade head` (idempotent): SUCCESS
#XZ|- Model import test: SUCCESS (prints 'transactions')


## Task 4: MEXC TSV Parser Implementation

### Key Decisions

1. **TSV parsing**: MEXC exports use TAB-separated values, not comma-separated. Must use `csv.reader(f, delimiter='\t')`.

2. **Swedish column headers**: MEXC uses Swedish column names (Insättningsbelopp, Uttagsadress, Handelsavgift, etc.). Parser must detect file type from headers.

3. **Auto-detection**: File type detected from headers:
   - Deposit: has `Insättningsbelopp` column
   - Withdrawal: has `Uttagsadress` column
   - Trade: has `Kvantitet` column

4. **Network to Chain mapping**: MEXC networks mapped to Chain enum:
   - `Ethereum(ERC20)` → Chain.ETHEREUM
   - `Solana(SOL)` → Chain.SOLANA
   - `Polygon(MATIC)` → Chain.POLYGON
   - `BNB Smart Chain(BEP20)` → Chain.BNB
   - `KDA` → Chain.KADENA
   - `PEAQ` → Chain.PEAQ

5. **TxID suffix stripping**: Some MEXC TxIDs have `:NNN` suffix (e.g., `...Kumo:010`). Stripped for cross-platform matching, but original preserved in raw_payload.

6. **Withdrawal amounts**: Use `Avräkningsbelopp` (settlement amount, after fee) as base_amount, not `Begärt belopp` (requested). Amounts are negative for TRANSFER_OUT.

7. **Decimal for all amounts**: Never use float - always use Decimal for monetary values.

8. **Error handling**: Parser collects errors and continues, never throws on malformed rows.

### Files Created

- `src/kryptoskatt/parsers/mexc.py` - MexcParser class with parse() method
- `tests/test_mexc_parser.py` - 21 comprehensive tests covering all requirements

### Verification Results

- All 21 tests pass: SUCCESS
- Import verification: SUCCESS
- Parser correctly handles deposits (3 rows → 3 TRANSFER_IN)
- Parser correctly handles withdrawals (7 rows → 7 TRANSFER_OUT)
- Auto-detection works from Swedish headers
- Network→Chain mapping works for ETH, SOL, POL, BNB, KDA, PEAQ
- TxID suffix stripped correctly
- Fee extraction works from Handelsavgift column
- Settlement amount (Avräkningsbelopp) used correctly
- All amounts are Decimal instances
- raw_payload includes original data
- Error handling collects malformed row errors


## Task 5: Crypto.com CSV Parser Implementation

### Key Decisions

1. **CSV parsing**: Used Python's built-in `csv.DictReader` module (not pandas) for parsing Crypto.com CSV exports

2. **Transaction kind mapping**:
   - `crypto_wallet_swap_credited` → SWAP_IN
   - `crypto_wallet_swap_debited` → SWAP_OUT
   - `crypto_withdrawal` → TRANSFER_OUT (with tx_hash)
   - `crypto_exchange` → TWO records: SWAP_OUT + SWAP_IN
   - `crypto_deposit` → TRANSFER_IN

3. **crypto_exchange handling**: For rows like "USDC > KDA":
   - SWAP_OUT: base_coin=USDC, base_amount=negative, quote_coin=KDA, quote_amount=positive
   - SWAP_IN: base_coin=KDA, base_amount=positive, quote_coin=USDC, quote_amount=positive (abs of sold amount)

4. **quote_amount for SWAP_IN**: Must be POSITIVE (absolute value of what was sold), not the negative original amount

5. **Decimal for all amounts**: Never use float - always use Decimal for monetary values

6. **Error handling**: Parser collects errors and continues, never throws on malformed rows

7. **ParseResult dataclass**: Returns both transactions and errors list

### Files Created

- `src/kryptoskatt/parsers/crypto_com.py` - CryptoComParser class with parse() method
- `tests/test_crypto_com_parser.py` - 12 comprehensive tests

### Verification Results

- Parser returns exactly 10 transactions from fixture (7 CSV rows → 10 transactions due to crypto_exchange doubling)
- crypto_exchange rows produce 6 transactions (3 pairs)
- crypto_wallet_swap_credited/debited map correctly to SWAP_IN/SWAP_OUT
- crypto_withdrawal has correct tx_hash populated
- All amounts are Decimal instances (never float)
- price_sek populated from Native Amount column
- raw_payload contains original CSV row data
- Error handling works for malformed rows

### Issues Encountered

1. **Docker container filesystem read-only**: After container restart, the mounted volume became read-only. Could not use `docker cp` to sync files. Solution: Ran tests locally with Python3 instead.

2. **Edit tool duplication**: Multiple edits on same file caused duplicate code blocks. Solution: Rewrote entire files to fix.

3. **Test filtering**: Initially filtered exchange transactions by event_type only, but crypto_wallet_swap also produces SWAP_IN/SWAP_OUT. Solution: Filter by checking raw_payload['Transaction Kind'] == 'crypto_exchange'


## Task 6: Coinbase CSV Parser Implementation

### Key Decisions

1. **CSV format**: Coinbase CSV exports have 2 metadata lines at start:
   - Line 1: "Transactions" (metadata)
   - Line 2: "User,..." (metadata)
   - Line 3: Headers (ID, Timestamp, Transaction Type, ...)
   - Lines 4+: Data rows

2. **Metadata skip detection**: Auto-detect if first line is "Transactions" to skip metadata, otherwise use file as-is. This allows testing with non-standard CSVs.

3. **Transaction type mapping**:
   - Buy → BUY
   - Send → TRANSFER_OUT
   - Receive → TRANSFER_IN
   - Convert → TWO records: SWAP_OUT + SWAP_IN
   - Sell → SELL
   - Reward → REWARD

4. **Convert (Swap) parsing**: Notes field format "Converted X FROM_COIN to Y TO_COIN" parsed with regex to extract both coins and amounts.

5. **Address extraction**: 
   - Send: Extract from "Sent X to ADDRESS (to ...)"
   - Receive: Extract from "(from ADDRESS1 to ADDRESS2)"
   - Handle truncated addresses with "..." (e.g., "5LWTG...eDgHg")

6. **Swedish krona prefix**: Price columns have "kr" prefix (e.g., "kr2.201200722") - strip before parsing to Decimal.

7. **Negative amounts**: Quantity Transacted can be negative (e.g., "-91.799939" for Send), fees can be negative (e.g., "-kr2.048").

8. **Decimal for all amounts**: Never use float - always use Decimal for monetary values.

9. **Error handling**: Parser collects errors and continues, never throws on malformed rows.

10. **ParseResult dataclass**: Returns both transactions and errors list.

### Files Created

- `src/kryptoskatt/parsers/coinbase.py` - CoinbaseParser class with parse() method
- `tests/test_coinbase_parser.py` - 18 comprehensive tests

### Verification Results

- All 18 tests pass: SUCCESS
- 11 CSV rows → 15 transactions (4 Convert rows produce 2 each)
- Convert rows produce SWAP_OUT + SWAP_IN pairs
- All amounts are Decimal instances (never float)
- Address extraction works for truncated addresses
- Buy rows have correct price_sek and fee
- Send/Receive transactions have correct to_address/from_address
- Error handling collects malformed row errors
- raw_payload contains original CSV row

### Issues Encountered

1. **Edit tool duplication**: Multiple edits on same file caused duplicate code blocks. Solution: Rewrote entire sections to fix.

2. **Docker volume mounts**: Initially tried to mount ./src and ./tests, but this broke the container's Python venv. Solution: Used docker cp to sync files after editing.

3. **Test file not in container**: Dockerfile doesn't copy tests directory. Solution: Used docker cp to copy tests and source files to container.

4. **Test assertion syntax**: Multiline assert statement caused NameError. Solution: Split into separate lines.

5. **Validation order**: Added validation that raises ValueError for invalid quantity, but test CSV didn't have Coinbase metadata lines. Solution: Made metadata skipping auto-detect based on first line content.



## Task 12: CoinGecko Price Service + Caching

### What was implemented
- Created `src/kryptoskatt/services/price.py` - PriceService class
- Created `tests/test_price_service.py` - Comprehensive tests (19 tests)

### Key implementation details

1. **CoinGecko API Date Format**: Uses DD-MM-YYYY format (NOT ISO!) - critical for API to work
2. **Cache-first strategy**: Always check PriceCache table before making API calls
3. **Decimal for prices**: Convert float from JSON using `Decimal(str(value))` to avoid floating point errors
4. **Coin ID mapping**: COIN_ID_MAP dict maps symbols (BTC) to CoinGecko IDs (bitcoin)
5. **API key support**: x-cg-demo-api-key header added when coingecko_api_key configured
6. **Error handling**: Returns None on 404, 429, or network errors (graceful degradation)

### Test patterns used

- Mock httpx.Client using context manager pattern:
  ```python
  with patch("kryptoskatt.services.price.httpx.Client") as mock_client_class:
      mock_client = MagicMock()
      mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
      mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
      yield mock_client
  ```

### Known pre-existing test failures (not related to this task)
- `test_import_config` - Expected to raise but didn't
- `test_add_command_import` - CLI module issue with add_typer

### Results
- 19 tests pass for PriceService
- All other tests still pass (103 passed, 2 pre-existing failures)


## Task: Fix fetch_cmd.py duplicates

### What was done

1. **Removed duplicate imports**: Lines 14-16 were duplicates of lines 10-13 imports
2. **Removed duplicate code block**: Lines 210-226 in `_fetch_all_wallets()` contained a broken duplicate block that referenced `wallet.chain_enum` (which doesn't exist)

### Issues encountered

1. **Edit tool corruption**: Multiple edit operations on the same file caused corruption (garbage lines, growing file size)
2. **File deleted**: At one point accidentally deleted the file while cleaning garbage lines
3. **Solution**: Used Python directly via bash to make surgical edits to the file

### Verification

- `python3 -c "import ast; ast.parse(open('src/kryptoskatt/cli/fetch_cmd.py').read()); print('OK')"`: SUCCESS
- No duplicate imports found
- No `wallet.chain_enum` references in file



## Task 15: Transfer Matching Engine

### Overview
Created a TransferMatcher class that identifies TRANSFER_OUT + TRANSFER_IN pairs representing non-taxable transfers between user's own wallets.

### Key Details

1. **Files Created**:
   - `src/kryptoskatt/engine/transfers.py` - TransferMatcher class with TransferMatchReport dataclass
   - `tests/test_transfers.py` - 12 comprehensive TDD tests

2. **Implementation**:
   - **Fee tolerance**: 5% (allows matching when fees are deducted)
   - **Time window**: 30 minutes for amount/time matching
   - **TX_HASH matching**: Same tx_hash on both → confidence 0.95
   - **AMOUNT_TIME matching**: Same coin, amount within ±5%, timestamp within 30 min → confidence 0.75
   - **External transfers**: TRANSFER_OUT to unknown address → unmatched (potential taxable)
   - **Ambiguous matches**: Multiple possible matches → counted as ambiguous, no link created

3. **Test Coverage** (12 tests):
   - No transfers: report shows 0s
   - TX_HASH match: same hash → TX_HASH method, confidence 0.95
   - AMOUNT_TIME match: similar amount, timestamp within 30 min → AMOUNT_TIME method, confidence 0.75
   - External transfer: to unknown address → unmatched
   - Fee tolerance: 0.96 out → 0.96 in (within 5%) → matches
   - Fee tolerance exceeded: 1.0 out → 0.5 in (>5%) → no match
   - Time window exceeded: >30 min apart → no match
   - Different coin: ETH out, BTC in → no match
   - Ambiguous: multiple matches → ambiguous (no link)
   - Report counts: verifies total_checked, matched, unmatched, ambiguous
   - Already linked: skipped
   - Negative amounts: abs() used for comparison

### Verification

- All 12 transfer tests pass
- 158/160 total tests pass (2 pre-existing failures unrelated to transfer matching)

### Issues Fixed Along the Way

1. **Corrupted dedup.py**: Found and fixed corrupted dedup.py file that had duplicate code blocks causing indentation errors


## Task 14: Deduplication Engine

### Overview
Created a DeduplicationEngine class that identifies and marks duplicate cryptocurrency transactions from CSV imports vs on-chain fetches.

### Key Details

1. **Files Created**:
   - `src/kryptoskatt/engine/dedup.py` - DeduplicationEngine class with DeduplicationReport dataclass
   - `src/kryptoskatt/engine/__init__.py` - Module exports
   - `tests/test_dedup.py` - 11 comprehensive TDD tests

2. **Implementation**:
   - **Primary dedup**: Two Transaction records with same non-null `tx_hash` → CSV version marked `is_duplicate=True`, on-chain version kept as canonical
   - **MEXC TxID suffix stripping**: Uses regex `r":\d+$"` to strip trailing `:010` suffix from MEXC TxIDs
   - **Secondary heuristic dedup**: When tx_hash is null, match on (coin, amount, timestamp ±5 min)
   - **Priority when choosing which to keep**: ON_CHAIN > COINBASE > CRYPTO_COM > MEXC > MANUAL

3. **Test Coverage** (11 tests):
   - test_no_duplicates: All unique tx_hashes → nothing marked
   - test_exact_tx_hash_dedup: Same tx_hash on CSV + on-chain → CSV marked duplicate
   - test_mexc_suffix_stripping: `hash:010` matches `hash` → CSV marked duplicate
   - test_heuristic_dedup_same_coin_amount_time: null tx_hash, same (coin, amount, timestamp within 5 min) → duplicate
   - test_heuristic_no_match_different_coin: null tx_hash, different coin → no match
   - test_heuristic_no_match_time_too_far: null tx_hash, timestamp >5 min apart → no match
   - test_on_chain_preferred_over_csv: on-chain kept, CSV marked duplicate
   - test_dedup_report_counts: Verify report has correct counts
   - test_already_duplicate_skipped: Transactions with is_duplicate=True are skipped
   - test_multiple_duplicates_same_hash: 3+ tx with same hash, only one kept
   - test_normalize_tx_hash_static: Unit test for normalize_tx_hash method

### Verification

- All 11 dedup tests pass
- 159/160 total tests pass (1 pre-existing failure unrelated to deduplication)
- Tests use in-memory SQLite for speed and isolation

### Issues Fixed Along the Way

1. **Corrupted dedup.py**: Multiple edit operations caused file corruption with duplicate code blocks. Solution: Deleted and rewrote the entire file cleanly.
2. **Edit tool issues**: The edit tool was adding hash prefixes to lines, causing confusion. Rewriting the entire file is cleaner.
3. **Docker cache**: Needed to rebuild Docker with `--no-cache` after corruption issues to ensure clean build.
4. **Test counts**: Initially counted individual duplicates instead of duplicate groups. Fixed to count groups (1 group of 3 transactions = 1 exact match, not 2).
2. **Docker rebuild needed**: Source code changes in src/ required Docker rebuild before tests would reflect changes