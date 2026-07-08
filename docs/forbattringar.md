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
- ~~Typkontroll i CI~~ — ✅ `mypy` körs i CI (gradvis: kärnan typkontrolleras, chain-adapters och webb-lagret är undantagna tills de kan stramas åt). Fångade direkt en riktig bugg i `issues`-kommandot.
- ~~Postgres 17~~ — ✅ compose och CI kör nu `postgres:17-alpine`. Befintlig `pgdata`-volym kräver dump/restore vid uppgradering (se README).
- ~~Versionssträng på ett ställe~~ — ✅ v0.5.0: `pyproject.toml` läser versionen dynamiskt från `kryptoskatt.__version__`.

## Användbarhet

- ~~Progressindikator för långkörande åtgärder~~ — ✅ v0.5.0 för fetch-all och beräkning (jobbstatus pollas på åtgärdssidan). Kvarstår för CSV-import och enkel-adress-fetch.
- ~~Bekräftelsedialog innan destruktiva åtgärder~~ — fanns redan för refetch (confirm-dialog) och kontoradering (textbekräftelse).
- **Felmeddelanden i query-strängen** (`?result=error:...`) försvinner vid refresh och kan bli långa/fula. Flash-meddelanden via session eller cookie i stället.
- ~~Mobilanpassning av tabeller~~ — fanns redan (`.table-container` med horisontell scroll används på alla tabelltunga sidor).
- ~~Sökfält på transaktionssidan~~ — ✅ v0.5.0: fritextsök på tx-hash, adresser och coin.
- ~~QR-kod för konto-ID~~ — ✅ v0.5.0: visas som inline-SVG på kontoskapande-sidan.
- ~~Svenska/engelska språkval~~ — ✅ v0.5.0: i18n-infrastruktur (språkcookie + `t()`), navigering/footer översatt, växlare i headern. Övriga sidor kan wrappas inkrementellt.
- **Onboarding: CSV-import som steg.** Onboardingen hanterar bara adresser; många användare börjar med börs-CSV:er.

## Funktioner

- ~~År-till-år-överföring~~ — ✅ visar per mynt ingående (från föregående år) och utgående GAV-balans/omkostnad, härlett ur GavLedger. Webbsida, CSV-nedladdning och `report --format carryover`.
- ~~SRU-fil-export för K4~~ — ✅ v0.5.0: genererar INFO.SRU + BLANKETTER.SRU (avsnitt D) för uppladdning via Skatteverkets Filöverföring. Webb (ZIP) + CLI (`report --format sru`).
- ~~Fler börser~~ — ✅ v0.5.0: Bitstamp, OKX och Gate.io tillagda med autodetektering. Kvarstår: Safello och BTCX (inget publikt dokumenterat exportformat — bidra gärna med en anonymiserad exempelfil).
- ~~xpub-stöd för Bitcoin~~ — ✅ v0.5.0: härleder P2PKH/P2SH/P2WPKH-adresser från xpub/ypub/zpub (BIP32) med gap-limit-scan. CLI `wallet add-xpub` + webbformulär.
- ~~Staking/lending-klassificering~~ — ✅ v0.5.0: `reward_type` (staking/mining/airdrop/interest) sätts av parsers och kan sättas manuellt; T2 grupperar per typ.
- ~~NFT-stöd~~ — ✅ NFT-liggare (`nft`-CSV) registrerar köp/sälj i SEK som unika per-token-tillgångar (`NFT:<samling>#<token-id>`) som går genom GAV → K4/SRU. Ledgers NFT-operationer taggas för spårbarhet (Ledger-exporten saknar token-identitet).
- ~~Priskällor~~ — ✅ Binance och Kraken publik OHLC (USD/USDT-stängning → SEK via Riksbanken) provas efter CoinGecko och före CoinAPI, utan API-nyckel.
- **Notifieringar:** e-post/webhook när fetch-all hittar nya transaktioner (kräver dock att anonymitetsprincipen ses över).
- ~~Read-only delningslänk~~ — ✅ tidsbegränsad, återkallningsbar token (hashad) som visar K4-sammanställning, GAV-överföring och nettopositoner skrivskyddat utan inloggning. Hanteras under Inställningar.
- ~~API-nycklar per konto~~ — ✅ konton kan lägga in egna Etherscan/Helius/Solscan/Tronscan/VeChainStats/Subscan-nycklar (krypterat); adaptrar faller tillbaka till instansens nyckel.
