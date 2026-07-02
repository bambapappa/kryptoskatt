# Förbättringsförslag — genomgång 2026-07

En generell genomgång av kodbas, säkerhet, användbarhet och funktioner.
Punkter markerade ✅ åtgärdades i v0.5.0; övriga är förslag i prioritetsordning.

## Säkerhet

| Prio | Förslag | Status |
|---|---|---|
| Hög | Hasha sessionstokens i databasen (SHA-256) så att en DB-läcka inte ger kapade sessioner | ✅ v0.5.0 |
| Hög | Rate limiting på inloggning och kontoskapande (brute force av konto-ID) | ✅ v0.5.0 |
| Hög | Kräv inloggning på blacklist-endpoints (`/year/{year}/blacklist-coin`) — var helt oautentiserade | ✅ v0.5.0 |
| Hög | Unika temp-filer vid rapportnedladdning i stället för förutsägbara `/tmp/k4_{year}.csv` | ✅ v0.5.0 |
| Medel | CSP-, HSTS- och Permissions-Policy-headers | ✅ v0.5.0 |
| Medel | Produktions-Dockerimage utan gcc och dev-beroenden; HEALTHCHECK; `no-new-privileges` | ✅ v0.5.0 |
| Medel | CI: minsta möjliga workflow-rättigheter + `pip-audit`-skanning | ✅ v0.5.0 |
| Medel | Gör coin-blacklisten per konto (migration 013 + filtrering i alla queries) | ✅ v0.5.0 |
| Medel | CSRF-skydd: Origin/Referer-validering på alla state-ändrande requests (utöver SameSite=Lax) | ✅ v0.5.0 |
| Medel | Kryptera API-nycklar för anpassade kedjor (Fernet + `SECRET_KEY` i .env) | ✅ v0.5.0 |
| Låg | In-memory-limitern är nu korrekt i Docker: entrypoint kör 1 worker (WEB_CONCURRENCY). Distribuerad limiter (Redis) behövs först vid horisontell skalning. | ✅ delvis v0.5.0 |
| Låg | Settings-UI visar sessions-id i stället för token-prefix | ✅ v0.5.0 |
| Låg | Trusted proxy: uvicorn kör med `--proxy-headers --forwarded-allow-ips` (FORWARDED_ALLOW_IPS, default 127.0.0.1) | ✅ v0.5.0 |
| Låg | CodeQL, Dependabot och CODEOWNERS i GitHub-repot; branch protection dokumenterad i SECURITY.md (måste aktiveras i repo-inställningarna) | ✅ v0.5.0 |

## Teknik / kodkvalitet

- ~~Dela upp `web/app.py`~~ — ✅ v0.5.0: uppdelad i `web/routes/*` per domän med delade dependencies i `web/deps.py`.
- ~~Enhetlig DB-dependency~~ — ✅ v0.5.0: alla 15 kopior är nu alias för `kryptoskatt.db.get_db`.
- ~~Byt till psycopg 3~~ — ✅ v0.5.0: `psycopg[binary]` med URL-normalisering i `db.py`; gcc/libpq-dev behövs inte längre i Docker-bygget.
- **Async på riktigt eller inte alls.** Appen kör sync SQLAlchemy i FastAPI-endpoints (blockerar event-loopen under långa anrop, t.ex. fetch-all). Antingen async-sessioner (`sqlalchemy[asyncio]` finns redan som extra) eller kör tunga jobb i bakgrund.
- ~~Bakgrundsjobb för fetch/beräkning~~ — ✅ v0.5.0: `fetch-all` och `calculate` körs nu som bakgrundsjobb med statuspollning i UI:t. (Kvarstår: enkel-adress-fetch/refetch körs fortfarande i requesten; distribuerad kö behövs vid flera workers.)
- ~~Migrationslås~~ — ✅ v0.5.0: `pg_advisory_lock` i alembic env.py serialiserar migrationer mellan repliker.
- ~~Loggning~~ — ✅ v0.5.0: `LOG_LEVEL` appliceras på root-loggern och uvicorn i `serve_cmd`.
- **Typkontroll i CI:** lägg till `mypy` eller `pyright` — kodbasen har redan bra type hints.
- **Postgres 17/18:** compose ligger kvar på `postgres:16-alpine` för att inte bryta befintliga volymer; planera uppgradering med `pg_dump`/`pg_upgrade`.
- ~~Versionssträng på ett ställe~~ — ✅ v0.5.0: `pyproject.toml` läser versionen dynamiskt från `kryptoskatt.__version__`.

## Användbarhet

- ~~Progressindikator för långkörande åtgärder~~ — ✅ v0.5.0 för fetch-all och beräkning (jobbstatus pollas på åtgärdssidan). Kvarstår för CSV-import och enkel-adress-fetch.
- ~~Bekräftelsedialog innan destruktiva åtgärder~~ — fanns redan för refetch (confirm-dialog) och kontoradering (textbekräftelse).
- **Felmeddelanden i query-strängen** (`?result=error:...`) försvinner vid refresh och kan bli långa/fula. Flash-meddelanden via session eller cookie i stället.
- ~~Mobilanpassning av tabeller~~ — fanns redan (`.table-container` med horisontell scroll används på alla tabelltunga sidor).
- ~~Sökfält på transaktionssidan~~ — ✅ v0.5.0: fritextsök på tx-hash, adresser och coin.
- ~~QR-kod för konto-ID~~ — ✅ v0.5.0: visas som inline-SVG på kontoskapande-sidan.
- **Svenska/engelska språkval.** UI:t är svenskt, README/CONTRIBUTING engelskt/blandat; en i18n-struktur (även enkel) gör projektet mer tillgängligt.
- **Onboarding: CSV-import som steg.** Onboardingen hanterar bara adresser; många användare börjar med börs-CSV:er.

## Funktioner

- **Fler år-till-år-överföringar:** spara GAV-utgående balans per år och visa diff mot föregående års deklaration.
- **SRU-fil-export** för K4 (Skatteverkets filformat för e-inlämning) — i dag genereras CSV/HTML-underlag; SRU skulle möjliggöra direktuppladdning.
- **Fler börser:** Bitstamp, Safello, BTCX (svenska aktörer), OKX, Gate.io.
- **WalletConnect/xpub-stöd för Bitcoin** — i dag måste varje BTC-adress läggas in manuellt; xpub-derivering skulle hämta alla.
- **Staking/lending-klassificering:** separera staking-rewards (kapital vs tjänst beroende på setup) med egen eventtyp och T2-kategori.
- **NFT-stöd:** Ledger-parsern filtrerar bort NFT:er; K4-mässigt är NFT-avyttringar också skattepliktiga.
- **Priskällor:** fallback-kedja CoinGecko → CoinAPI → manuell är delvis på plats; lägg till Kraken/Binance-OHLC som gratis källa.
- **Notifieringar:** e-post/webhook när fetch-all hittar nya transaktioner (kräver dock att anonymitetsprincipen ses över).
- **Read-only delningslänk** till revisor/skatterådgivare (tidsbegränsad token med enbart läsrättigheter).
- **API-nycklar per konto:** i dag delas instansens Etherscan/Helius-nycklar av alla konton; låt konton lägga in egna nycklar (krypterat, se säkerhet).
