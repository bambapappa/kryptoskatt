# KryptoSkatt — Användarhandledning

KryptoSkatt beräknar kapitalvinster och -förluster för kryptovalutatransaktioner enligt svenska skatteregler (genomsnittsmetoden/GAV) och genererar underlag för K4- och T2-blanketterna.

---

## Innehåll

1. [Komma igång](#komma-igång)
2. [Ditt konto](#ditt-konto)
3. [Registrera plånböcker](#registrera-plånböcker)
4. [Importera transaktioner](#importera-transaktioner)
5. [Hämta on-chain-transaktioner](#hämta-on-chain-transaktioner)
6. [Beräkna skatt](#beräkna-skatt)
7. [Rapporter](#rapporter)
8. [Datakvalitet och problem](#datakvalitet-och-problem)
9. [Priser](#priser)
10. [Inställningar](#inställningar)
11. [Vanliga frågor](#vanliga-frågor)
12. [Felsökning](#felsökning)

---

## Komma igång

### Alternativ 1 — Docker (rekommenderas)

```bash
cp .env.example .env
# Fyll i DATABASE_URL och eventuella API-nycklar
docker-compose up -d
```

Öppna `http://localhost:8000` i webbläsaren.

### Alternativ 2 — Lokal installation

```bash
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
kryptoskatt serve --port 8000
```

### Flödet i korthet

```
1. Skapa konto          → spara ditt konto-ID på ett säkert ställe
2. Lägg till plånböcker → ange adress + kedja för varje plånbok
3. Importera CSV-filer  → en fil per börs
4. Hämta on-chain       → för plånböcker du angett
5. Kör beräkning        → välj skatteår
6. Granska rapport      → K4-underlag, T2, revisionsunderlag
```

---

## Ditt konto

KryptoSkatt lagrar **inga personuppgifter**. Ditt konto identifieras enbart av ett slumpmässigt konto-ID i formatet `ord-ord-ord-NNNN` (t.ex. `maple-river-fox-4291`).

### Skapa konto

Klicka **Skapa anonymt konto** på inloggningssidan. Du ser konto-ID:t en enda gång — **spara det direkt**, t.ex. i ett lösenordshanteringsprogram.

> Konto-ID:t kan inte återställas. Det finns ingen e-post, inget lösenord och ingen återhämtning.

### Logga in

Ange ditt konto-ID på inloggningssidan. Sessionen är giltig i 30 dagar.

### Logga ut

Klicka **Logga ut** i navigeringsmenyn. Alla aktiva sessioner avslutas.

---

## Registrera plånböcker

Gå till **Plånböcker → + Lägg till** eller **Inställningar → Kom igång**.

| Fält | Beskrivning |
|---|---|
| Adress | Plånboksadress (0x..., Solana-adress, Bitcoin-adress, etc.) |
| Kedja | Blockchain (ETHEREUM, SOLANA, BITCOIN, ...) |
| Label | Valfritt smeknamn (t.ex. "Metamask", "Ledger Nano") |
| Kategori | Eigen plånbok / Börs / Mining Pool / DePIN / Hårdvara |
| Min | Kryssar du i "Min" ingår adressen i on-chain-hämtning |

### Okänd kedja

Du kan registrera adresser på kedjor som inte stöds direkt. De sparas men hoppas över vid hämtning tills du konfigurerat en adapter under **Inställningar → Anpassade kedjor**.

### Adressformat

KryptoSkatt validerar adressformatet för kända kedjor:

| Kedja | Format |
|---|---|
| Ethereum / Polygon / BNB / Base / Arbitrum | `0x` + 40 hexadecimala tecken |
| Bitcoin (Legacy) | Börjar med `1` eller `3`, 26–34 tecken |
| Bitcoin (Bech32) | Börjar med `bc1` |
| Solana | Base58, 32–44 tecken |
| TRON | Börjar med `T`, totalt 34 tecken |
| XRP | Börjar med `r`, 25–35 tecken |
| Kadena | Börjar med `k:` eller `w:` |

---

## Importera transaktioner

Gå till **Importera** i navigeringsmenyn.

### Exportera från börs

| Börs | Var hittar du exporten |
|---|---|
| **Coinbase** | Konto → Skatter → Generera rapport → Transactions CSV |
| **Coinbase Advanced** | Portfolio → Statements → Fill statements |
| **Crypto.com** | Konto → Transaktionshistorik → Exportera CSV |
| **MEXC** | Ordrar → Orderhistorik → Exportera |
| **Binance** | Plånbok → Transaktionshistorik → Exportera |
| **KuCoin** | Konton → Handelshistorik → Exportera |
| **Kraken** | Historik → Exportera ledger |
| **Bybit** | Ordrar → Orderhistorik → Exportera |
| **Ledger Live** | Konton → välj konto → Exportera operationshistorik |

### Ladda upp

1. Välj fil (CSV eller TSV)
2. Välj plattform — eller låt **Auto-detektera** avgöra formatet
3. Klicka **Importera**

Resultatet visar antal importerade rader, eventuella dubbletter som filtrerades bort, och om platformen detekterades korrekt.

### Manuell swap-CSV

För swaps som inte fångats av annan parser:

```csv
timestamp_utc,from_coin,from_amount,to_coin,to_amount,fee_coin,fee_amount,tx_hash
2024-05-15T12:00:00Z,ETH,0.5,SOL,10.2,ETH,0.002,0xabc...
```

---

## Hämta on-chain-transaktioner

Gå till **Åtgärder** och klicka **Hämta alla plånböcker**, eller klicka **Hämta** bredvid en enskild plånbok på sidan **Plånböcker**.

### API-nycklar

Vissa kedjor kräver en API-nyckel i `.env`:

| Kedja | Miljövariabel |
|---|---|
| Ethereum / Polygon / BNB / Base / Arbitrum | `ETHERSCAN_API_KEY` |
| Solana | `HELIUS_API_KEY` (alternativt `SOLSCAN_API_KEY`) |
| TRON | `TRONSCAN_API_KEY` |
| VeChain | `VECHAINSTATS_API_KEY` |
| Peaq / Substrate | `SUBSCAN_API_KEY` |
| Bitcoin, XRP, Kadena | Ingen nyckel krävs |

Gratis nycklar räcker för personligt bruk.

### Anpassade kedjor

Gå till **Inställningar → Anpassade kedjor** för att lägga till en Blockscout- eller Etherscan-kompatibel utforskare för en kedja som inte stöds direkt.

---

## Beräkna skatt

Gå till **Åtgärder** och välj skatteår under **Beräkna skatt**, eller klicka **Kör beräkning** på dashboard.

Beräkningspipelinen kör:
1. **Avduplicering** — markerar dubbletter (t.ex. om en transaktion finns i både CSV och on-chain-data)
2. **Prisberikning** — hämtar SEK-priser från CoinGecko och Riksbanken
3. **Transfermatchning** — kopplar TRANSFER_OUT ↔ TRANSFER_IN för att undvika felaktig skattepliktig avyttring
4. **GAV-beräkning** — beräknar genomsnittligt anskaffningsvärde och kapitalvinst/-förlust per avyttring

Körning tar vanligtvis några sekunder men kan ta längre tid vid många transaktioner och saknade priser.

---

## Rapporter

Klicka på ett år på **Dashboard** för att öppna K4-sammanfattningen.

### K4-rapport (kapitalvinster)

Visar per kryptovaluta:
- **Försäljningspris SEK** — totala intäkter
- **Omkostnadsbelopp SEK** — GAV × antal sålda enheter
- **Vinst / Förlust SEK** — skillnaden

Ladda ner som **CSV** (direkt infogningsbar i Skatteverkets e-tjänst), **JSON** (programmatisk hantering) eller **K4-underlag HTML** (för utskrift).

### T2-rapport (mining / staking-inkomster)

Visar rewards och staking-utbetalningar med SEK-värde vid mottagningstillfället. Lägg till manuella poster (t.ex. hårdvarukostnader) under **Åtgärder → T2-poster**.

### Revisionsunderlag

Komplett transaktionslista med källplatform, tx-hash och klassificering — lämplig att spara om Skatteverket begär underlag.

### GAV-historik

Visar hur genomsnittspriset för varje kryptovaluta förändrats för varje transaktion.

### Nettopositoner

Visar nuvarande innehav (i slutet av skatteåret) med GAV-kostnadsbas — användbart för att stämma av mot börskonton.

---

## Datakvalitet och problem

Gå till **K4-sammanfattning → Flaggade problem** för en lista med varningar.

| Problem | Allvarlighet | Åtgärd |
|---|---|---|
| TRANSFER_OUT utan matchande TRANSFER_IN | Varning | Kontrollera om du skickat till en egen plånbok. Lägg till plånboken om så är fallet och hämta dess transaktioner. Matcha manuellt under **Transfereringar**. |
| Saknat pris | Info | Ladda upp manuell prisfil under **Priser**, eller acceptera att avyttringen utelämnas ur K4 |
| Negativt saldo | Fel | Transaktioner saknas — kontrollera att alla köp/mottagningar är importerade |
| Obalanserad swap | Varning | SWAP_OUT utan SWAP_IN (eller vice versa) — kontrollera import |

### Transfermatchning

Gå till **År → Transfereringar** för att se automatiskt matchade och omatchade transfereringar. Skapa manuella kopplingar för transaktioner som inte matchades automatiskt.

### Spamiga mynt

På K4-sammanfattningssidan kan du markera okända mynt (scam-tokens, spam-airdroppar) som spam. De döljs från rapporten och inkluderas inte i beräkningarna.

---

## Priser

KryptoSkatt hämtar historiska SEK-priser automatiskt via CoinGecko och Riksbanken. För obskyra kryptovalutor som saknas i CoinGecko kan du ange priser manuellt.

### Manuell prisfil

Gå till **Åtgärder → Manuella priser** och ladda upp en CSV-fil:

```csv
coin,date,price_sek
GEOD,2025-07-12,0.054
BONO,2025-10-20,0.001
```

Manuella priser prioriteras före CoinGecko. Kör **Beräkna** efteråt för att applicera.

### PriceHistory-katalogen

Lägg CSV-filer med historiska priser i mappen `PriceHistory/` (Docker: monterad volym) och kör **Importera prishistorik** under **Åtgärder**. Formatet är detsamma som ovan.

---

## Inställningar

Gå till **Inställningar** i navigeringsmenyn.

### Kontoinformation

Visar ditt konto-ID och skapandedatum.

### Aktiva sessioner

Visar alla aktiva sessioner (webbläsare/enheter). Du kan avsluta enskilda sessioner eller alla utom den nuvarande.

### Anpassade kedjor

Lägg till blockchain-adapters för kedjor som inte stöds direkt:
1. Klicka **Lägg till ny kedja**
2. Ange kedjans namn (t.ex. `MYCHAIN`)
3. Välj adapter-typ (`blockscout` eller `etherscan`)
4. Ange Explorer-URL och native coin
5. Ange API-nyckel om utforskaren kräver det

### Exportera kontodata (GDPR)

Gå till API: `GET /api/v1/account/export` för att ladda ner all din data som JSON (plånböcker, transaktioner, disposals, GAV-historik).

### Radera konto

Under **Inställningar → Radera konto**: skriv `DELETE MY ACCOUNT` i bekräftelsefältet. All data raderas permanent och kan inte återställas.

---

## Vanliga frågor

### Vad är GAV (genomsnittsmetoden)?

Vid försäljning av kryptovaluta beräknas omkostnadsbeloppet som det genomsnittliga anskaffningsvärdet av alla enheter av det myntet du ägt. Varje nytt köp uppdaterar genomsnittpriset.

**Exempel:**
- Köper 1 BTC för 300 000 kr → GAV = 300 000 kr/BTC
- Köper ytterligare 1 BTC för 500 000 kr → GAV = (300 000 + 500 000) / 2 = 400 000 kr/BTC
- Säljer 1 BTC för 600 000 kr → Vinst = 600 000 − 400 000 = 200 000 kr

### Vad räknas som en avyttring?

Skattepliktiga händelser inkluderar:
- Försäljning av kryptovaluta mot SEK eller annan valuta
- Byte (swap) av en kryptovaluta mot en annan
- Betalning med kryptovaluta
- Skicka kryptovaluta till en okänd adress (TRANSFER_OUT utan match)

*Inte* skattepliktiga händelser:
- Flytta kryptovaluta mellan egna plånböcker (korrekt matchad transferering)
- Mottagna rewards och staking (beskattas i stället som inkomst i T2)

### Hur hanteras rewards och staking?

Rewards (`REWARD`-transaktioner) inkluderas i T2-rapporten med marknadsvärdet i SEK vid mottagningstillfället. De ingår alltså inte i K4 vid mottagnandet, men påverkar framtida GAV om du säljer dem.

### Varför saknas priser för ett mynt?

Priser hämtas från CoinGecko. Mycket nya, obscura eller avlistade mynt saknas ofta. Ladda upp en manuell prisfil för dessa (se [Priser](#priser)).

### Kan jag använda verktyget för flera börser?

Ja. Importera CSV-filer från alla börser du handlat på. KryptoSkatt avduplicerar automatiskt transaktioner som finns i flera källor (t.ex. om du både hämtar on-chain och importerar från börs för samma adress).

### Vad händer om en TRANSFER_OUT inte matchas?

Den behandlas som en skattepliktig avyttring med okänt försäljningspris, vilket visas som ett problem under **Flaggade problem**. Om det faktiskt var en flytt till din egen plånbok: registrera mottagaradressen, hämta dess transaktioner, och KryptoSkatt matchar automatiskt. Annars: matcha manuellt under **Transfereringar**.

---

## Felsökning

### "Inga beräknade avyttringar hittades" på dashboard

1. Kontrollera att transaktioner är importerade (gå till ett år → Transaktioner)
2. Kör beräkning under **Åtgärder**

### Import misslyckas med parsningsfel

- Kontrollera att filen är exporterad i rätt format från börsen
- Prova att ange plattform manuellt istället för auto-detektering
- Kontrollera att filen är UTF-8 eller latin-1-kodad (inga specialtecken i filnamnet)

### On-chain-hämtning returnerar inga transaktioner

1. Kontrollera att API-nyckeln är korrekt i `.env`
2. Verifiera att adressen är registrerad som **Min** plånbok
3. Prova i en utforskare (t.ex. etherscan.io) att transaktioner faktiskt finns

### Databasfel / "could not connect"

```bash
docker-compose ps            # Kontrollera att postgres körs
docker-compose logs db       # Se eventuella DB-fel
```

Kontrollera att `DATABASE_URL` i `.env` stämmer.

### Priset för ett mynt verkar fel

1. Gå till **Åtgärder → Importera prishistorik** för att uppdatera cachen
2. Ladda upp en manuell prisfil med korrekta priser
3. Kör beräkning igen

### Negativt GAV-saldo

Uppstår om det saknas köptransaktioner. Vanliga orsaker:
- Du hanterade kryptovalutan innan du började använda KryptoSkatt
- En börsimport är ofullständig
- Transaktioner existerar på en kedja du inte lagt till

Lösning: importera historiska transaktioner bakåt i tid tills saldot stämmer.
