# KryptoSkatt - Användarhandledning

## Introduktion

KryptoSkatt är ett verktyg för att beräkna kapitalvinster och kapitalförluster för kryptovalutatransaktioner enligt svenska skatteregler (genomsnittsmetoden/GAV).

## Komma igång

### 1. Installation

```bash
pip install -e .
```

### 2. Konfiguration

Skapa en `.env`-fil med databasanslutning:

```env
DATABASE_URL=postgresql://användare:lösenord@localhost:5432/kryptoskatt
```

### 3. Starta databasen

```bash
docker-compose up -d
alembic upgrade head
```

## Importera transaktioner

### Från börser

Exportera dina transaktioner från respektive börs som CSV och importera:

```bash
kryptoskatt import --file path/till/fil.csv --platform coinbase
```

**Supportade plattformar:**
- `coinbase` - Coinbase-export
- `crypto_com` - Crypto.com-export  
- `mexc` - MEXC-export

Plattformen autodetekteras om den inte anges.

### Från plånböcker (blockchain)

Lägg till en plånbok:

```bash
kryptoskatt wallet add --address 0xABC123... --chain ethereum --label "Min ETH-plånbok"
```

Hämta transaktioner:

```bash
# För en specifik adress
kryptoskatt fetch --address 0xABC123... --chain ethereum

# För alla registrerade plånböcker
kryptoskatt fetch --all
```

## Beräkna skatt

### Beräkna för ett år

```bash
kryptoskatt calculate 2024
```

Detta analyserar alla transaktioner för året och beräknar:
- Antal avyttringar (försäljningar/byten)
- GAV (genomsnittligt anskaffningsvärde) per valuta
- Kapitalvinster och kapitalförluster

### Generera rapport

```bash
# CSV-format
kryptoskatt report 2024 --format csv

# JSON-format
kryptoskatt report 2024 --format json --output-dir ./rapporter

# Inkludera fullständig transaktionslista
kryptoskatt report 2024 --full
```

## Webbinterface

Starta webbservern:

```bash
kryptoskatt serve
```

Öppna `http://localhost:8000` i webbläsaren.

### Dashboard

Välj beskattningsår för att se sammanfattning.

### Årssida (K4-sammanfattning)

Visar:
- Totala försäljningsintäkter
- Totalt omkostnadsbelopp  
- Total kapitalvinst/-förlust
- Sammanfattning per valuta

### Transaktioner

Granska alla importerade transaktioner med filtrering.

### GAV-historik

Se hur genomsnittligt anskaffningsvärde har förändrats över tid för varje valuta.

### Issues

Visa flaggade problem i transaktionsdata som behöver granskas.

## Vanliga frågor

### Vad är GAV?

GAV (Genomsnittligt AnskaffningsVärde) är den metod som används i Sverige för att beräkna omkostnadsbeloppet för kryptovaluta. När du säljer kryptovaluta används det genomsnittliga anskaffningsvärdet av alla liknande tillgångar du ägt.

### Vilka transaktionstyper stöds?

- **Buy** - Köp av kryptovaluta
- **Sell** - Försäljning av kryptovaluta
- **Transfer** - Överföring mellan plånböcker/börser
- **Convert/Swap** - Växling mellan kryptovalutor
- **Reward** - Mining/staking-belöningar
- **Fee** - Transaktionsavgifter

### Hur hanteras Swaps/Converts?

Vid växling (t.ex. ETH → SOL) skapas två transaktioner:
- En "sell" av ETH
- En "buy" av SOL

Detta säkerställer korrekt GAV-beräkning.

### Vad gör jag om det finns felaktiga transaktioner?

Använd webbinterfacet för att:
1. Visa transaktioner för ett år
2. Identifiera felaktiga poster
3. Kontakta support för korrigering

## Felsökning

### "Inga transaktioner hittades"

Kontrollera att:
1. Du har importerat transaktioner: `kryptoskatt import --file ...`
2. Årtalet är korrekt (transaktioner finns för det året)

### Databasfel

Se till att:
1. PostgreSQL kör: `docker-compose ps`
2. DATABASE_URL är korrekt i .env

### API-fel för blockchain

Kontrollera att:
1. ETHERSCAN_API_KEY är satt i .env (för Ethereum)
2. SOLSCAN_API_KEY är satt i .env (för Solana)

## Support

För buggrapporter eller frågor, skapa ett ärende på GitHub.
