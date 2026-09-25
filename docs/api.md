# KryptoSkatt — API-referens

Bas-URL: `http://localhost:8000/api/v1`

Alla endpoints utom `/health` och `/info` kräver autentisering via sessionscookie (`kryptoskatt_session`). Se [Autentisering](#autentisering) nedan.

Alla svar är JSON. Tidsstämplar är ISO 8601 UTC. Belopp är strängar med decimalprecision.

---

## Innehåll

- [Autentisering](#autentisering)
- [Hälsa & info](#hälsa--info)
- [Plånböcker](#plånböcker)
- [Transaktioner & disposals](#transaktioner--disposals)
- [Transfereringar](#transfereringar)
- [Import](#import)
- [On-chain-hämtning](#on-chain-hämtning)
- [Beräkning](#beräkning)
- [Rapporter](#rapporter)
- [Priser](#priser)
- [Datakvalitet](#datakvalitet)
- [T2-poster](#t2-poster)
- [Anpassade kedjor](#anpassade-kedjor)
- [Konto (GDPR)](#konto-gdpr)
- [Felkoder](#felkoder)

---

## Autentisering

KryptoSkatt använder anonyma konton utan e-post eller lösenord. Varje konto identifieras av ett unikt `account_id` i formatet `ord-ord-ord-ord-NNNN` (äldre konton: `ord-ord-ord-NNNN`). `account_id` är den enda inloggningsuppgiften. Behandla det som ett lösenord.

### Skapa konto

```http
POST /api/v1/auth/account
```

Skapar ett nytt anonymt konto och sätter sessionscookien. Spara `account_id`: det visas bara här. Den som skapar konton via API:t godkänner därmed [användarvillkoren](/villkor). Begränsat till 10 anrop/min per IP.

**Svar 201:**
```json
{
  "account_id": "maple-river-fox-lamp-4291"
}
```

### Logga in

```http
POST /api/v1/auth/session
Content-Type: application/json

{
  "account_id": "maple-river-fox-lamp-4291"
}
```

Skapar en session (30 dagar, förlängs vid användning) och sätter cookie `kryptoskatt_session` (HttpOnly, SameSite=Lax, Secure över HTTPS).

**Svar 200:**
```json
{"ok": true}
```

**Svar 401:** okänt `account_id`. **Svar 429:** för många försök (10/min per IP, eller den globala gränsen för misslyckade inloggningar).

### Logga ut

```http
DELETE /api/v1/auth/session
```

Avslutar alla sessioner för kontot. Cookie rensas.

**Svar 200:** `{"ok": true}`

### Kontoinformation

```http
GET /api/v1/auth/me
```

**Svar 200:**
```json
{
  "account_id": "maple-river-fox-lamp-4291",
  "created_at": "2025-03-15T10:00:00Z"
}
```

### Lista sessioner

```http
GET /api/v1/auth/sessions
```

**Svar 200:**
```json
{
  "sessions": [
    {
      "id": 1,
      "created_at": "2025-03-15T10:00:00Z",
      "last_used_at": "2025-03-15T12:00:00Z",
      "expires_at": "2025-04-14T10:00:00Z"
    }
  ]
}
```

### Återkalla session

```http
DELETE /api/v1/auth/sessions/{session_id}
DELETE /api/v1/auth/sessions          ← alla sessioner
```

---

## Hälsa & info

Kräver ingen autentisering.

### Hälsokontroll

```http
GET /api/v1/health
```

```json
{"status": "ok", "version": "0.4.0"}
```

### Tjänstinfo

```http
GET /api/v1/info
```

```json
{
  "version": "0.4.0",
  "supported_chains": ["ARBITRUM", "BASE", "BITCOIN", "BNB", "ETHEREUM", "KADENA", "POLYGON", "SOLANA", "TRON", "VECHAIN"],
  "adapter_types": ["blockscout", "etherscan"]
}
```

---

## Plånböcker

### Lista plånböcker

```http
GET /api/v1/wallets
```

**Svar 200:**
```json
{
  "wallets": [
    {
      "id": 1,
      "address": "0xAbCd...1234",
      "chain": "ETHEREUM",
      "label": "Metamask",
      "is_mine": true,
      "category": "own",
      "created_at": "2025-03-10T08:00:00Z"
    }
  ]
}
```

### Lägg till plånbok

```http
POST /api/v1/wallets
Content-Type: application/json

{
  "address": "0xAbCd...1234",
  "chain": "ETHEREUM",
  "label": "Metamask",
  "is_mine": true
}
```

`chain` kan vara valfri icke-tom sträng. Okända kedjor sparas men hoppas över vid hämtning tills adapter konfigurerats.

**Svar 201:** Plånboksobjekt (samma format som i listan)

**Svar 400:** Adressformatet är felaktigt för känd kedja, tom kedja, eller dublettpost.

### Lista ej stödda plånböcker

```http
GET /api/v1/wallets/unsupported
```

Returnerar plånböcker där ingen adapter är konfigurerad (okänd kedja eller saknad API-nyckel).

### Ta bort plånbok

```http
DELETE /api/v1/wallets/{wallet_id}
```

**Svar 200:** `{"ok": true}`

**Svar 404:** Plånboken existerar inte eller tillhör annat konto.

---

## Transaktioner & disposals

### Lista disposals (avyttringar)

```http
GET /api/v1/transactions?year=2024&page=1&page_size=100
```

**Query-parametrar:**

| Parameter | Typ | Beskrivning |
|---|---|---|
| `year` | int | Filtrera på skatteår (valfritt) |
| `page` | int | Sida (standard: 1) |
| `page_size` | int | Poster per sida (max 200, standard: 100) |

**Svar 200:**
```json
{
  "disposals": [
    {
      "id": 42,
      "tax_year": 2024,
      "coin": "ETH",
      "amount_disposed": "0.500000000000000000",
      "proceeds_sek": "15234.50",
      "cost_basis_sek": "12100.00",
      "gain_loss_sek": "3134.50",
      "timestamp_utc": "2024-06-15T14:23:00Z"
    }
  ],
  "total": 87,
  "page": 1,
  "page_size": 100
}
```

### Sätt etikett på transaktion

```http
PATCH /api/v1/transactions/{tx_id}/label
Content-Type: application/json

{"label": "Staking-belöning Q1 2024"}
```

**Svar 200:** `{"ok": true}`

---

## Transfereringar

### Lista transferlänkar

```http
GET /api/v1/transfers?year=2024
```

**Svar 200:**
```json
{
  "links": [
    {
      "id": 5,
      "tx_out_id": 100,
      "tx_in_id": 101,
      "match_method": "TX_HASH",
      "confidence": "1.0000"
    }
  ]
}
```

### Skapa manuell transferlänk

Matchar en TRANSFER_OUT med en TRANSFER_IN manuellt för att undvika felaktig skattepliktig avyttring.

```http
POST /api/v1/transfers/manual
Content-Type: application/json

{
  "tx_out_id": 100,
  "tx_in_id": 101
}
```

**Svar 201:** Länkobjekt

### Ta bort transferlänk

```http
DELETE /api/v1/transfers/{link_id}
```

**Svar 200:** `{"ok": true}`

---

## Import

### Ladda upp CSV/TSV-fil

```http
POST /api/v1/import
Content-Type: multipart/form-data

file=@export.csv
platform=auto    ← valfritt; auto-detekterar om utelämnat
```

**Plattformsvärden:** `auto`, `coinbase`, `coinbase_advanced`, `crypto_com`, `mexc`, `binance`, `kucoin`, `kraken`, `bybit`, `ledger`, `manual_swap`

**Svar 200:**
```json
{
  "ok": true,
  "platform_detected": "coinbase",
  "imported": 143,
  "duplicates": 12,
  "batch_id": 7
}
```

**Svar 400:** Okänt filformat, parsningsfel.

---

## On-chain-hämtning

### Hämta transaktioner

```http
POST /api/v1/fetch
Content-Type: application/json

{
  "wallets": [
    {"address": "0xAbCd...1234", "chain": "ETHEREUM"}
  ]
}
```

Utelämna `wallets` för att hämta alla registrerade plånböcker.

**Svar 200:**
```json
{
  "ok": true,
  "fetched": 67,
  "skipped": 3,
  "errors": []
}
```

---

## Beräkning

Kör hela pipeline: avduplicering → prisberikning → transfermatchning → GAV-beräkning.

```http
POST /api/v1/calculate
Content-Type: application/json

{"year": 2024}
```

**Svar 200:**
```json
{
  "ok": true,
  "year": 2024,
  "disposals_created": 34,
  "gav_entries": 156,
  "transfers_matched": 8,
  "duplicates_flagged": 5
}
```

---

## Rapporter

### K4-rapport (kapitalvinster)

```http
GET /api/v1/reports/k4/{year}
GET /api/v1/reports/k4/{year}/csv    ← CSV-nedladdning
```

**Svar 200 (JSON):**
```json
{
  "year": 2024,
  "total_gains": "45231.00",
  "total_losses": "-12800.00",
  "rows": [
    {
      "coin": "BTC",
      "proceeds_sek": "123450.00",
      "cost_basis_sek": "98200.00",
      "gain_loss_sek": "25250.00"
    }
  ]
}
```

### T2-rapport (staking/mining-inkomster)

```http
GET /api/v1/reports/t2/{year}
```

**Svar 200:**
```json
{
  "year": 2024,
  "total_income_sek": "3400.00",
  "entries": [
    {
      "coin": "ETH",
      "event_type": "REWARD",
      "amount": "0.05",
      "value_sek": "1700.00",
      "date": "2024-02-14"
    }
  ]
}
```

### Nettopositoner

```http
GET /api/v1/reports/net-position/{year}
```

**Svar 200:**
```json
{
  "year": 2024,
  "positions": [
    {
      "coin": "ETH",
      "total_units": "2.500000",
      "gav_per_unit_sek": "30400.00",
      "total_cost_sek": "76000.00"
    }
  ]
}
```

### GAV-historik

```http
GET /api/v1/reports/gav-history?coin=ETH&year=2024
```

Returnerar alla GAV-ledger-poster för ett mynt/år.

### Revisionsunderlag

```http
GET /api/v1/reports/audit/{year}
```

Komplett transaktionsunderlag med källplatform, tx-hash och klassificering.

### Prisberikning (asynkron)

```http
POST /api/v1/reports/enrich-prices/async
Content-Type: application/json
{"year": 2024}
```

**Svar 200:**
```json
{"job_id": "3f2c…", "status": "running"}
```

**Svar 409:** kontot har redan ett jobb igång.

```http
GET /api/v1/reports/enrich-prices/status/{job_id}
```

Jobbet syns bara för kontot som startade det (annars 404).

**Svar 200:**
```json
{"status": "done", "result": {"enriched": 45, "skipped": 2, "total": 47, "swap_implied": 3, "skipped_unknown_coin": 1}}
```
`status` är `running`, `done` eller `error` (då med `error`-fält).

---

## Priser

### Ladda upp manuell prisfil

```http
POST /api/v1/prices/upload-manual
Content-Type: multipart/form-data

file=@manual_prices.csv
```

Priserna är privata för kontot och går före publika priskällor. Kolumnen kan heta `coin` eller `coin_id`.

CSV-format (med rubrikrad):
```csv
coin,date,price_sek
GEOD,2025-07-12,0.054
BONO,2025-10-20,0.001
```

Max 20 MB (annars 413). Ett befintligt pris för samma mynt och datum skrivs över.

**Svar 200:** `{"imported": 2, "errors": []}`

> `POST /api/v1/prices/import-history` är borttagen. Publik prishistorik läses bara in av operatören från serverns `PriceHistory/`-katalog.

---

## Datakvalitet

### Lista flaggade problem

```http
GET /api/v1/issues?year=2024
```

**Svar 200:**
```json
{
  "issues": [
    {
      "type": "UNMATCHED_TRANSFER_OUT",
      "severity": "warning",
      "coin": "ETH",
      "amount": "1.5",
      "timestamp_utc": "2024-03-01T12:00:00Z",
      "message": "TRANSFER_OUT utan matchande TRANSFER_IN — behandlas som skattepliktig avyttring"
    },
    {
      "type": "MISSING_PRICE",
      "severity": "info",
      "coin": "GEOD",
      "message": "Saknar prisdata för GEOD — kan inte beräkna vinst/förlust"
    }
  ]
}
```

**Problemtyper:**

| Typ | Allvarlighet | Beskrivning |
|---|---|---|
| `UNMATCHED_TRANSFER_OUT` | warning | TRANSFER_OUT utan matchande TRANSFER_IN |
| `MISSING_PRICE` | info | Saknat pris — avyttringen är inte beräknad |
| `NEGATIVE_BALANCE` | error | GAV-saldo under noll — troligen saknade köptransaktioner |
| `UNBALANCED_SWAP` | warning | SWAP_OUT utan matchande SWAP_IN (eller vice versa) |

---

## T2-poster

Manuella kostnads- och inkomstposter för T2-blanketten (gruvdrift, DePIN-utrustning, el).

### Lista T2-poster

```http
GET /api/v1/t2-entries?year=2024
```

**Svar 200:**
```json
{
  "entries": [
    {
      "id": 3,
      "year": 2024,
      "entry_date": "2024-01-15",
      "description": "Grafikkort RTX 4090",
      "amount_sek": "-18500.00",
      "vendor": "Webhallen"
    }
  ]
}
```

### Skapa T2-post

```http
POST /api/v1/t2-entries
Content-Type: application/json

{
  "year": 2024,
  "entry_date": "2024-01-15",
  "description": "Grafikkort RTX 4090",
  "amount_sek": -18500.00,
  "vendor": "Webhallen"
}
```

**Svar 201:** Postobjekt

### Ta bort T2-post

```http
DELETE /api/v1/t2-entries/{entry_id}
```

---

## Anpassade kedjor

Konfigurerar blockchain-adapters för kedjor som inte stöds direkt (Blockscout-kompatibla utforskare eller Etherscan-forks).

### Lista anpassade kedjor

```http
GET /api/v1/custom-chains
```

### Skapa anpassad kedja

```http
POST /api/v1/custom-chains
Content-Type: application/json

{
  "chain_name": "MYCHAIN",
  "adapter_type": "blockscout",
  "explorer_url": "https://explorer.mychain.io",
  "native_coin": "MYC",
  "api_key": "valfritt"
}
```

`adapter_type`: `blockscout` eller `etherscan`. `explorer_url` måste vara en publik `https://`-adress (port 443, inga inloggningsuppgifter, får inte peka på privata eller reserverade IP-adresser). Annars svar 422. `api_key` lagras krypterat. Saknar servern `SECRET_KEY` blir svaret 503.

**Svar:** Kedjeobjekt

### Ta bort anpassad kedja

```http
DELETE /api/v1/custom-chains/{chain_id}
```

---

## Konto (GDPR)

### Exportera kontodata

```http
GET /api/v1/account/export
```

Laddar ner alla kontodata som JSON-fil (GDPR art. 15 och 20). En nyckel per tabell med kontodata, med alla kolumner. Sessioner, API-nycklar och tokenhashar ingår inte.

**Svar 200:** JSON-fil med `Content-Disposition: attachment`

```json
{
  "exported_at": "2026-09-24T12:00:00+00:00",
  "account_id": "maple-river-fox-lamp-4291",
  "created_at": "…",
  "transactions": [...],
  "import_batches": [...],
  "wallets": [...],
  "disposals": [...],
  "gav_ledger": [...],
  "t2_manual_entries": [...],
  "t2_manual_income_entries": [...],
  "coin_blacklist": [...],
  "manual_prices": [...],
  "custom_chain_configs": [...],
  "share_links": [...],
  "transfer_links": [...]
}
```

### Radera konto

```http
DELETE /api/v1/account
Content-Type: application/json

{"confirm": "DELETE MY ACCOUNT"}
```

Raderar permanent kontot och all tillhörande data i en transaktion (GDPR art. 17). Samma kod som webbens radering. Kräver exakt bekräftelsesträng.

**Svar 200:** `{"ok": true}`

**Svar 400:** Fel bekräftelsesträng.

---

## Felkoder

| HTTP-kod | Beskrivning |
|---|---|
| `400 Bad Request` | Ogiltig inmatning, valideringsfel |
| `401 Unauthorized` | Saknad eller ogiltig session |
| `403 Forbidden` | Behörighet saknas för resursen |
| `404 Not Found` | Resursen existerar inte (eller tillhör annat konto) |
| `409 Conflict` | Resursen existerar redan (t.ex. dubblett-plånbok) |
| `422 Unprocessable Entity` | Parsningsfel i request body |
| `413 Content Too Large` | Uppladdad fil större än 20 MB |
| `429 Too Many Requests` | Rate limit nådd |
| `503 Service Unavailable` | Servern saknar konfiguration (t.ex. `SECRET_KEY`) |
| `500 Internal Server Error` | Serverfel |

Felsvar:
```json
{
  "detail": "Beskrivning av felet"
}
```

---

## Rate limiting

| Endpoint-grupp | Gräns |
|---|---|
| Allmänt | 60 req/min per konto |
| Fetch (on-chain) | 5 req/min per konto |
| Skapa konto / logga in | 10 req/min per IP |
| Misslyckade inloggningar | 200/min totalt för hela instansen |

Vid rate limit: HTTP 429. Gränserna gäller per process (`WEB_CONCURRENCY=1` rekommenderas).
