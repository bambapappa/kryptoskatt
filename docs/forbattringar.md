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
| Medel | **CSRF-tokens på formulär-POSTs.** SameSite=Lax skyddar mot det mesta, men äldre webbläsare och subdomän-scenarier täcks inte. FastAPI saknar inbyggt stöd — lägg t.ex. till double-submit-cookie. | Förslag |
| Medel | Kryptera API-nycklar för anpassade kedjor (Fernet + `SECRET_KEY` i .env) | ✅ v0.5.0 |
| Låg | **Distribuerad rate limiter.** Nuvarande är in-memory per process — med `--workers 2` (som i entrypoint) har varje worker sin egen räknare. Redis eller reverse-proxy-limit för produktion. | Förslag |
| Låg | **Ta bort sessionstoken-prefix ur settings-UI.** Visar nu hash-prefix (ofarligt) men kolumnen kan lika gärna visa enbart id/datum. | Förslag |
| Låg | **Trusted proxy-lista.** `X-Forwarded-Proto` litas på från alla klienter (påverkar Secure-flaggan och HSTS). Konfigurera uvicorn `--proxy-headers --forwarded-allow-ips` korrekt. | Förslag |
| Låg | CodeQL, Dependabot och CODEOWNERS i GitHub-repot; branch protection dokumenterad i SECURITY.md (måste aktiveras i repo-inställningarna) | ✅ v0.5.0 |

## Teknik / kodkvalitet

- ~~Dela upp `web/app.py`~~ — ✅ v0.5.0: uppdelad i `web/routes/*` per domän med delade dependencies i `web/deps.py`.
- **Enhetlig DB-dependency.** `get_db`, `_get_db` och `_get_db_session` är tre kopior av samma generator; samla i `kryptoskatt/db.py` och importera.
- **Byt till psycopg 3.** `psycopg2-binary` underhålls men psycopg3 är standardvalet för nya SQLAlchemy 2-projekt och har bättre asyncio-stöd.
- **Async på riktigt eller inte alls.** Appen kör sync SQLAlchemy i FastAPI-endpoints (blockerar event-loopen under långa anrop, t.ex. fetch-all). Antingen async-sessioner (`sqlalchemy[asyncio]` finns redan som extra) eller kör tunga jobb i bakgrund.
- ~~Bakgrundsjobb för fetch/beräkning~~ — ✅ v0.5.0: `fetch-all` och `calculate` körs nu som bakgrundsjobb med statuspollning i UI:t. (Kvarstår: enkel-adress-fetch/refetch körs fortfarande i requesten; distribuerad kö behövs vid flera workers.)
- **Migrationskedjan testas** (bra!), men `alembic upgrade head` körs som root-steg i entrypoint utan lås — vid flera repliker kan två containrar migrera samtidigt. Kör migrationer som separat deploy-steg eller med advisory lock.
- **Loggning:** `LOG_LEVEL` finns i config men appliceras inte på root-loggern vid uppstart; sätt upp `logging.basicConfig`/dictConfig i `serve_cmd`.
- **Typkontroll i CI:** lägg till `mypy` eller `pyright` — kodbasen har redan bra type hints.
- **Postgres 17/18:** compose ligger kvar på `postgres:16-alpine` för att inte bryta befintliga volymer; planera uppgradering med `pg_dump`/`pg_upgrade`.
- **Versionssträng på ett ställe:** `pyproject.toml` och `__init__.py` måste hållas i synk manuellt — använd `importlib.metadata` eller `hatch-vcs`.

## Användbarhet

- ~~Progressindikator för långkörande åtgärder~~ — ✅ v0.5.0 för fetch-all och beräkning (jobbstatus pollas på åtgärdssidan). Kvarstår för CSV-import och enkel-adress-fetch.
- **Bekräftelsedialog innan destruktiva åtgärder** i webben (radera konto, refetch som raderar rader) — kontoradering har textbekräftelse, men refetch saknar varning.
- **Felmeddelanden i query-strängen** (`?result=error:...`) försvinner vid refresh och kan bli långa/fula. Flash-meddelanden via session eller cookie i stället.
- **Mobilanpassning** av tabelltunga sidor (transaktioner, audit) — horisontell scroll eller kortvy.
- **Sökfält på transaktionssidan** (tx-hash, adress, belopp) utöver befintliga filter.
- **Export av konto-ID som QR-kod** vid kontoskapande, för enkel inloggning på mobil.
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
