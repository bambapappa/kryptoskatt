# KryptoSkatt: driftguide för administratörer

Den här guiden beskriver hur du driftar en **publik** KryptoSkatt-instans på en egen Linuxserver. Den förutsätter Ubuntu 24.04 LTS eller Debian 12, men fungerar på alla distributioner med Docker.

Uppsättningen består av tre containrar:

```
Internet ──443/80──▶ Caddy (automatisk HTTPS) ──internt nät──▶ app (uvicorn) ──▶ db (PostgreSQL)
```

Bara Caddy exponeras mot internet. Appen och databasen nås bara på ett internt Docker-nät (`172.28.0.0/24`).

> **Ditt ansvar som operatör:** du är personuppgiftsansvarig enligt GDPR för det användarna lagrar. Läs avsnittet [Juridik och GDPR](#juridik-och-gdpr) innan du öppnar sidan för allmänheten.

---

## Innehåll

1. [Krav](#1-krav)
2. [Förbered servern](#2-förbered-servern)
3. [Installera KryptoSkatt](#3-installera-kryptoskatt)
4. [Konfigurera `.env`](#4-konfigurera-env)
5. [Starta](#5-starta)
6. [Säkerhetskopior](#6-säkerhetskopior)
7. [Uppdatera](#7-uppdatera)
8. [Övervakning och loggar](#8-övervakning-och-loggar)
9. [Vanliga administrativa uppgifter](#9-vanliga-administrativa-uppgifter)
10. [Juridik och GDPR](#juridik-och-gdpr)
11. [Checklista före lansering](#checklista-före-lansering)
12. [Felsökning](#felsökning)

---

## 1. Krav

| Resurs | Minimum | Rekommenderat |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2 GB |
| Disk | 10 GB | 20 GB+ (databas och säkerhetskopior växer med antalet användare) |
| OS | Linux med Docker Engine 24+ och Compose v2 | Ubuntu 24.04 LTS |
| Nät | Publik IPv4-adress (IPv6 valfritt) | |
| Domän | Ett domännamn med A-post (och ev. AAAA-post) mot serverns IP | |

Inga betalda API-nycklar behövs. Se [API-nycklar](#api-nycklar).

---

## 2. Förbered servern

Kör som en användare med `sudo`-rättigheter.

### 2.1 Uppdatera och skapa en driftanvändare

```bash
sudo apt update && sudo apt full-upgrade -y
sudo adduser --disabled-password --gecos "" kryptoskatt
sudo usermod -aG sudo kryptoskatt   # valfritt, om du vill administrera som den användaren
```

### 2.2 SSH och brandvägg

Logga in med SSH-nyckel och stäng av lösenordsinloggning (`PasswordAuthentication no` i `/etc/ssh/sshd_config`, följt av `sudo systemctl restart ssh`).

```bash
sudo apt install -y ufw fail2ban unattended-upgrades
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp      # HTTP/3
sudo ufw enable
sudo dpkg-reconfigure -plow unattended-upgrades   # automatiska säkerhetsuppdateringar
```

> **Obs:** portar som Docker publicerar går förbi `ufw`. Därför publicerar den här uppsättningen bara Caddy (80/443). Appens port 8000 binds i `docker-compose.yml` bara till `127.0.0.1`, och produktionsöverlägget tar bort den helt.

### 2.3 Installera Docker

Följ Dockers officiella instruktion för din distribution: <https://docs.docker.com/engine/install/>. Därefter:

```bash
sudo usermod -aG docker kryptoskatt
# logga ut och in igen, kontrollera sedan:
docker compose version
```

### 2.4 DNS

Skapa en A-post (och eventuellt en AAAA-post) för din domän, t.ex. `kryptoskatt.example.se`, som pekar på serverns IP. Vänta tills `dig +short kryptoskatt.example.se` visar rätt adress. Caddy kan inte hämta certifikat förrän DNS pekar rätt.

---

## 3. Installera KryptoSkatt

```bash
sudo mkdir -p /opt/kryptoskatt && sudo chown kryptoskatt: /opt/kryptoskatt
sudo -iu kryptoskatt
git clone https://github.com/bambapappa/kryptoskatt.git /opt/kryptoskatt
cd /opt/kryptoskatt
cp .env.example .env
chmod 600 .env
```

Repot är privat, så servern behöver läsbehörighet. Använd en *deploy key* (Settings → Deploy keys på GitHub, endast läsbehörighet) i stället för ditt personliga konto.

---

## 4. Konfigurera `.env`

Generera hemligheter:

```bash
openssl rand -hex 24   # → POSTGRES_PASSWORD
openssl rand -hex 32   # → SECRET_KEY
```

Minsta produktionskonfiguration (resten av `.env.example` kan stå kvar):

```env
DOMAIN=kryptoskatt.example.se

POSTGRES_PASSWORD=<lösenordet från ovan>
DATABASE_URL=postgresql://kryptoskatt:<samma lösenord>@db:5432/kryptoskatt

SECRET_KEY=<nyckeln från ovan>
CORS_ORIGINS=["https://kryptoskatt.example.se"]
COOKIE_SECURE=true

OPERATOR_NAME=Ditt namn eller företagsnamn
OPERATOR_CONTACT=privacy@example.se

INACTIVE_ACCOUNT_MONTHS=24
ACCESS_LOG=false
DEBUG_MODE=false
WEB_CONCURRENCY=1
```

Förklaringar:

| Variabel | Varför |
|---|---|
| `DOMAIN` | Caddy hämtar TLS-certifikat för den här domänen |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | Måste stämma överens. Byt aldrig standardlösenordet på en publik server. |
| `SECRET_KEY` | Krypterar användarnas API-nycklar. **Ta säkerhetskopia av den.** Går den förlorad kan sparade nycklar inte dekrypteras, och användarna får lägga in dem igen. |
| `CORS_ORIGINS` | Din publika adress |
| `OPERATOR_NAME` / `OPERATOR_CONTACT` | Visas i integritetspolicyn och villkoren (GDPR art. 13). Utan dem visar sidorna en varning. |
| `INACTIVE_ACCOUNT_MONTHS` | Konton som inte använts så här länge raderas (lagringsminimering, GDPR art. 5.1 e) |
| `ACCESS_LOG` | Låt stå på `false`. Åtkomstloggar innehåller IP-adresser och delningslänkar. |
| `WEB_CONCURRENCY` | Låt stå på `1`. Begränsningen av inloggningsförsök och jobbkön ligger i processens minne. |

`FORWARDED_ALLOW_IPS` sätts av `docker-compose.prod.yml` (bara Caddys interna nät är betrott). Du behöver inte ändra den.

### API-nycklar

Sidan fungerar utan nycklar: Bitcoin, Ethereum, Base, Arbitrum, Polygon, XRP och Kadena hämtas gratis. Vill du att alla användare ska kunna hämta BNB, Solana, TRON, VeChain och Peaq kan du lägga in **gratis** nycklar (`ETHERSCAN_API_KEY`, `HELIUS_API_KEY`, `TRONSCAN_API_KEY`, `VECHAINSTATS_API_KEY`, `SUBSCAN_API_KEY`). Instansens nycklar delas då av alla användare och deras gratiskvoter. Alternativt lägger varje användare in sin egen nyckel under Inställningar.

---

## 5. Starta

```bash
cd /opt/kryptoskatt
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Vid start körs automatiskt:
1. databasmigreringar (`alembic upgrade head`)
2. radering av inaktiva konton (`kryptoskatt purge-inactive`)
3. uvicorn med `--proxy-headers --no-access-log`

Öppna `https://<din domän>`. Första anropet kan ta några sekunder medan Caddy hämtar certifikatet.

Kontrollera sedan:

```bash
curl -sI https://kryptoskatt.example.se | grep -iE "strict-transport|content-security"
curl -s  https://kryptoskatt.example.se/health          # {"status":"ok"}
curl -sI http://kryptoskatt.example.se | head -1        # 308 → https
```

Tips: skapa ett alias så du slipper skriva båda filerna:

```bash
echo "alias ks='docker compose -f /opt/kryptoskatt/docker-compose.yml -f /opt/kryptoskatt/docker-compose.prod.yml'" >> ~/.bashrc
```

---

## 6. Säkerhetskopior

`deploy/backup.sh` gör en komprimerad `pg_dump` och rensar kopior som är äldre än `BACKUP_KEEP_DAYS` (standard 14 dagar).

```bash
sudo mkdir -p /var/backups/kryptoskatt && sudo chown kryptoskatt: /var/backups/kryptoskatt
crontab -e
```

```cron
15 3 * * * /opt/kryptoskatt/deploy/backup.sh >> /home/kryptoskatt/backup.log 2>&1
```

**Kopiera säkerhetskopiorna till en annan plats** (en annan server eller objektlagring), krypterat. Exempel med `restic` eller `rclone crypt`. Spara också `.env` (särskilt `SECRET_KEY`) på ett säkert ställe skilt från servern.

**Återställ:**

```bash
ks stop app
gunzip -c /var/backups/kryptoskatt/kryptoskatt-YYYYMMDD-HHMMSS.sql.gz \
  | ks exec -T db psql -U kryptoskatt -d kryptoskatt
ks start app
```

(Återställ till en tom databas. Vid behov kan du ta bort volymen `pgdata` och starta `db` först.)

> **GDPR:** en användare som raderar sitt konto finns kvar i säkerhetskopiorna tills de roterats bort. Behåll inte kopior längre än nödvändigt, och återställ aldrig en gammal kopia utan att först ta ställning till konton som raderats efter att kopian togs.

---

## 7. Uppdatera

```bash
cd /opt/kryptoskatt
bash deploy.sh
```

`deploy.sh` tar först en säkerhetskopia, kör sedan `git pull --ff-only` och bygger om och startar om, och väntar till sist på hälsokontrollen. Migreringar körs automatiskt.

**Postgres major-uppgradering** (t.ex. 16 → 18): en ny major startar inte på en gammal datakatalog. Ta en dump, stoppa, ta bort volymen `pgdata`, sätt `POSTGRES_IMAGE` och starta. Återställ sedan dumpen enligt avsnitt 6.

**OS-uppdateringar:** `unattended-upgrades` sköter säkerhetsuppdateringar. Starta om servern när `/var/run/reboot-required` finns. Containrarna har `restart: unless-stopped` och startar själva.

---

## 8. Övervakning och loggar

| Vad | Hur |
|---|---|
| Hälsa | `https://<domän>/health` returnerar `{"status":"ok"}`. Övervaka med t.ex. Uptime Kuma eller en extern uptime-tjänst. |
| Containerstatus | `ks ps`. Appcontainern har en egen `HEALTHCHECK`. |
| Applikationsloggar | `ks logs -f app` (nivå via `LOG_LEVEL`) |
| Caddy/TLS | `ks logs -f caddy` |
| Disk | `df -h` och `docker system df`. Rensa gamla images med `docker image prune`. |

Loggarna innehåller inga IP-adresser eller åtkomstrader så länge `ACCESS_LOG=false`. Begränsa Dockers loggstorlek i `/etc/docker/daemon.json`:

```json
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
```

---

## 9. Vanliga administrativa uppgifter

**Radera inaktiva konton manuellt** (körs även vid varje start):

```bash
ks exec app kryptoskatt purge-inactive            # enligt INACTIVE_ACCOUNT_MONTHS
ks exec app kryptoskatt purge-inactive --months 12
```

Kör det gärna dagligen via cron om servern sällan startas om:

```cron
30 4 * * * docker compose -f /opt/kryptoskatt/docker-compose.yml -f /opt/kryptoskatt/docker-compose.prod.yml exec -T app kryptoskatt purge-inactive
```

**Publik prishistorik** (gemensam cache för alla): lägg CoinGecko- eller CoinMarketCap-exporter i `/opt/kryptoskatt/PriceHistory/`. Katalogen är monterad skrivskyddad i appen. Starta sedan importen från webben (*3 Beräkna → Avancerat*).

**En användare har tappat sitt konto-ID:** kontot går inte att återställa, eftersom inga identifierande uppgifter sparas. Det är avsiktligt.

**En användare begär radering eller export via e-post:** hänvisa till *Inställningar* i appen, där användaren kan göra det själv. Du kan inte veta vem som äger ett konto utan konto-ID:t. Kräv därför aldrig mindre än att personen visar upp konto-ID:t.

**Debugläge:** `DEBUG_MODE=true` exponerar rådata och destruktiva verktyg. Använd det **aldrig** på en publik server.

---

## Juridik och GDPR

Det här är ingen juridisk rådgivning. Låt en jurist granska innan lansering.

- **Du är personuppgiftsansvarig.** Plånboksadresser och transaktioner räknas som personuppgifter, eftersom de kan kopplas till en person. Namn och kontaktuppgift anges i `OPERATOR_NAME` och `OPERATOR_CONTACT` och visas i `/integritet`.
- **Villkor och integritetspolicy** finns i `src/kryptoskatt/web/templates/legal/`. Anpassa dem efter din verksamhet (t.ex. om du tar betalt eller driver sidan som företag) och uppdatera datumet överst.
- **Personuppgiftsbiträde:** din hosting-leverantör behandlar data åt dig. Se till att du har ett personuppgiftsbiträdesavtal (DPA), vilket de flesta leverantörer erbjuder i sina villkor. Välj helst en leverantör och ett datacenter inom EU/EES.
- **Tredje parter:** servern skickar plånboksadresser till blockkedjeutforskare (Blockscout, Blockstream m.fl.) när användare hämtar transaktioner. Det står i integritetspolicyn. Lägger du till fler källor eller nycklar ska texten uppdateras.
- **Personuppgiftsincident:** upptäcker du ett intrång ska du anmäla det till IMY inom 72 timmar om det inte är osannolikt att det medför en risk för de registrerade (GDPR art. 33).
- **Lagringstid:** konton raderas efter `INACTIVE_ACCOUNT_MONTHS`, och säkerhetskopior roteras efter `BACKUP_KEEP_DAYS`. Håll integritetspolicyn och de verkliga tiderna i takt.
- **Cookies:** bara nödvändiga cookies används, så ingen samtyckesbanner behövs. Lägger du till analysverktyg eller liknande krävs samtycke.
- **Ansvar:** villkoren begränsar ansvaret "i den utsträckning lagen tillåter". Ansvar för uppsåt, grov vårdslöshet och tvingande konsumenträtt kan inte avtalas bort.

---

## Checklista före lansering

- [ ] DNS pekar på servern, och HTTPS fungerar (`curl -sI https://…`)
- [ ] `ufw` är aktivt med bara 22, 80 och 443 öppna. SSH går bara med nyckel.
- [ ] `.env` har `chmod 600`, starka `POSTGRES_PASSWORD` och `SECRET_KEY`, samt `DOMAIN`, `CORS_ORIGINS`, `OPERATOR_NAME` och `OPERATOR_CONTACT`
- [ ] `DEBUG_MODE=false`, `ACCESS_LOG=false`, `WEB_CONCURRENCY=1`
- [ ] Appen startad med `docker-compose.prod.yml`, så att port 8000 inte är nåbar utifrån (`curl http://<ip>:8000` ska misslyckas)
- [ ] Nattlig säkerhetskopia via cron, kopierad till annan plats. `.env` sparad separat.
- [ ] Återställning testad minst en gång
- [ ] Hälsoövervakning av `/health`
- [ ] `/villkor` och `/integritet` granskade och anpassade, med operatörsuppgifterna ifyllda
- [ ] Personuppgiftsbiträdesavtal med hosting-leverantören
- [ ] Rutin för personuppgiftsincidenter (vem gör vad inom 72 timmar)

---

## Felsökning

| Symptom | Orsak / åtgärd |
|---|---|
| Caddy får inget certifikat | DNS pekar fel, eller så är port 80/443 blockerad. Kontrollera `ks logs caddy`. |
| `DOMAIN` saknas vid start | Sätt `DOMAIN` i `.env` |
| Alla användare spärras vid inloggning samtidigt | Appen ser proxyns IP som klient-IP. Starta med `docker-compose.prod.yml`, som sätter `FORWARDED_ALLOW_IPS`. |
| "Servern saknar SECRET_KEY" när användare sparar nycklar | Sätt `SECRET_KEY` och starta om. Byt den aldrig efteråt, eftersom sparade nycklar då inte längre kan läsas. |
| `could not connect to server` | `ks ps`: är `db` frisk? Stämmer `DATABASE_URL` mot `POSTGRES_PASSWORD`? |
| Migrering misslyckas vid uppdatering | `ks logs app`. Återställ säkerhetskopian från innan `deploy.sh` och rapportera felet. |
| Disken full | `docker image prune -a`, rotera säkerhetskopior, kontrollera `docker system df` |
