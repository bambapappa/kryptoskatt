# KryptoSkatt: användarhandledning

*För dig som använder sidan. Är du den som driftar sidan, läs [driftguiden](drift.md).*

KryptoSkatt beräknar kapitalvinster och -förluster för kryptotillgångar enligt svenska skatteregler (genomsnittsmetoden/GAV) och tar fram underlag för K4 (avsnitt D) och T2.

> **Viktigt:** KryptoSkatt är ett räknehjälpmedel, inte skatterådgivning. Du ansvarar själv för din deklaration. Se [användarvillkoren](/villkor) och sidan [Så räknar vi](/om-berakningen) i appen.

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

Du behöver bara en webbläsare. Gå till sidans adress och klicka **Skapa anonymt konto**.

### Flödet i korthet

Menyn följer samma steg: **Översikt · 1 Plånböcker · 2 Importera · 3 Beräkna** (övrigt ligger under **Mer**). Översikten visar vilka steg som är klara tills du gjort din första beräkning.

```
0. Skapa konto          → godkänn villkoren, spara konto-ID:t
1. Plånböcker           → lägg till dina publika adresser (aldrig privata nycklar)
2. Importera            → hämta on-chain med ett klick + CSV från varje börs
3. Beräkna              → "Alla år" räcker
4. Granska              → klicka på ett år: K4-underlag, 70 %-regeln, T2, flaggade problem
5. Deklarera            → ladda ner SRU-filer eller för över siffrorna till K4 avsnitt D
```

---

## Ditt konto

Du uppger inget namn, ingen e-post och inget lösenord. Ditt konto identifieras enbart av ett slumpmässigt konto-ID i formatet `ord-ord-ord-ord-NNNN` (t.ex. `maple-river-fox-lamp-4291`). Äldre konton har tre ord och fungerar som vanligt. Vad som lagras och varför står i [integritetspolicyn](/integritet).

### Skapa konto

Kryssa i att du har läst villkoren och integritetspolicyn och klicka **Skapa anonymt konto**. Du ser konto-ID:t (även som QR-kod) en enda gång. **Spara det direkt**, t.ex. i en lösenordshanterare.

> Konto-ID:t kan inte återställas. Det finns ingen e-post, inget lösenord och ingen återhämtning.

### Logga in

Ange ditt konto-ID på inloggningssidan. Sessionen förlängs vid varje besök och går ut efter 30 dagar utan användning. Efter för många felaktiga försök spärras inloggningen en kort stund.

> Konton som inte använts på 24 månader raderas automatiskt (operatören kan ändra tiden).

### Logga ut

Klicka **Logga ut** i navigeringsmenyn. Alla aktiva sessioner avslutas.

---

## Registrera plånböcker

Gå till **1 Plånböcker → + Lägg till**. Ange bara **publika** adresser. KryptoSkatt behöver aldrig privata nycklar eller seed-fraser. För Bitcoin kan du ange en xpub/ypub/zpub, så härleds alla adresser automatiskt.

| Fält | Beskrivning |
|---|---|
| Adress | Plånboksadress (0x..., Solana-adress, Bitcoin-adress, etc.) |
| Kedja | Blockchain (ETHEREUM, SOLANA, BITCOIN, ...) |
| Label | Valfritt smeknamn (t.ex. "Metamask", "Ledger Nano") |
| Kategori | Egen plånbok / Börs / Mining Pool / DePIN / Hårdvara |
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

Gå till **2 Importera** i menyn.

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

Klicka **Hämta on-chain** på översikten eller **Hämta alla** under **3 Beräkna**. Hämtningen körs i bakgrunden och sidan visar förloppet.

### Vilka kedjor behöver nyckel?

| Kedja | Källa | Nyckel |
|---|---|---|
| Bitcoin (även xpub) | Blockstream | Ingen |
| Ethereum, Base, Arbitrum, Polygon | Blockscout (gratis), Etherscan om nyckel finns | Ingen |
| XRP | XRPL-klustret | Ingen |
| Kadena | Chainweb | Ingen |
| BNB Smart Chain | Etherscan | Gratis `ETHERSCAN_API_KEY` |
| Solana | Helius (alt. Solscan) | Gratis `HELIUS_API_KEY` |
| TRON | Tronscan | Gratis `TRONSCAN_API_KEY` |
| VeChain | VeChainStats | Gratis `VECHAINSTATS_API_KEY` |
| Peaq / Substrate | Subscan | Gratis `SUBSCAN_API_KEY` |

En nyckel kan redan finnas på sidan (satt av den som driftar den), eller läggas in av dig under **Mer → Inställningar → API-nycklar** (bara ditt konto, lagras krypterat). Saknas en nyckel hoppas kedjan över och du får ett tydligt meddelande om vilken nyckel som behövs.

> Vid hämtning skickar **servern** dina adresser till källan ovan. Din IP-adress skickas inte med. Vill du inte att en tjänst får dina adresser kan du importera CSV i stället.

### Anpassade kedjor

Gå till **Inställningar → Anpassade kedjor** för att lägga till en Blockscout- eller Etherscan-kompatibel utforskare för en kedja som inte stöds direkt.

---

## Beräkna skatt

Gå till **3 Beräkna** och klicka **Beräkna**. Förvalet är **Alla år**, vilket nästan alltid är rätt: genomsnittsmetoden räknar alltid på hela historiken, och då blir alla år klara på en gång.

Beräkningspipelinen kör:
1. **Avduplicering** — markerar dubbletter (t.ex. om en transaktion finns i både CSV och on-chain-data)
2. **Prisberikning**: SEK-pris per händelse. Ordning: ditt eget manuella pris, pris ur en swap i samma transaktion, CoinGecko, Binance/Kraken (USD omräknat med Riksbankens kurs)
3. **Transfermatchning** — kopplar TRANSFER_OUT ↔ TRANSFER_IN för att undvika felaktig skattepliktig avyttring
4. **GAV-beräkning**: genomsnittligt anskaffningsvärde och vinst/förlust per avyttring. Flytt mellan egna plånböcker påverkar inte anskaffningsvärdet. Bara enheter som går åt till nätverksavgift lämnar poolen.

Körning tar vanligtvis några sekunder men kan ta längre tid vid många transaktioner och saknade priser.

---

## Rapporter

Klicka på ett år på **Översikt** för att öppna årssammanfattningen.

### K4-rapport (kapitalvinster)

Visar per kryptotillgång:
- **Försäljningspris SEK**: totala intäkter
- **Omkostnadsbelopp SEK**: GAV × antal sålda enheter
- **Vinst / Förlust SEK**: skillnaden

Överst visas **totala vinster**, **totala förluster**, **avdragsgill förlust (70 %)** och **netto efter 70 %-regeln**. Kryptotillgångar redovisas i K4 avsnitt D. Vinster tas upp fullt och förluster dras av med 70 %.

Du kan ladda ner:
- **SRU-filer** (`INFO.SRU` + `BLANKETTER.SRU`) för Skatteverkets filöverföring. Personnummer och namn fylls i precis före nedladdningen och sparas inte.
- **K4-underlag HTML** för utskrift eller manuell inmatning.
- **CSV/JSON** för egen kontroll.

Du kan också skapa en **skrivskyddad delningslänk** till en revisor under **Mer → Inställningar**. Den har ett slutdatum och kan återkallas.

### T2-rapport (mining / staking-inkomster)

Visar rewards och staking-utbetalningar med SEK-värde vid mottagningstillfället, grupperade efter typ (staking, mining, airdrop, ränta). Hur inkomsten ska deklareras beror på din situation. Kontrollera klassificeringen. Lägg till manuella poster (t.ex. hårdvarukostnader) på årets T2-sida.

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
| Saknat pris | Varning | Händelsen räknas med 0 kr tills ett pris finns. Lägg in ett manuellt pris under **Mer → Priser** och beräkna igen. |
| Negativt saldo | Fel | Transaktioner saknas — kontrollera att alla köp/mottagningar är importerade |
| Obalanserad swap | Varning | SWAP_OUT utan SWAP_IN (eller vice versa) — kontrollera import |

### Transfermatchning

Gå till **År → Transfereringar** för att se automatiskt matchade och omatchade transfereringar. Skapa manuella kopplingar för transaktioner som inte matchades automatiskt.

### Spamiga mynt

På K4-sammanfattningssidan kan du markera okända mynt (scam-tokens, spam-airdroppar) som spam. De döljs från rapporten och inkluderas inte i beräkningarna.

---

## Priser

KryptoSkatt hämtar historiska SEK-priser automatiskt från gratis källor (CoinGecko, Binance, Kraken, med Riksbankens USD/SEK). För mynt som saknas där kan du ange priser manuellt under **Mer → Priser**. **Manuella priser är privata**: de gäller bara ditt konto och påverkar aldrig andra användare.

### Manuell prisfil

Lägg till ett pris i taget under **Mer → Priser**, eller ladda upp en CSV-fil (max 20 MB):

```csv
coin,date,price_sek
GEOD,2025-07-12,0.054
BONO,2025-10-20,0.001
```

Manuella priser prioriteras före CoinGecko. Kör **Beräkna** efteråt för att applicera.

---

## Inställningar

Gå till **Mer → Inställningar**.

### Kontoinformation

Visar ditt konto-ID och skapandedatum.

### Aktiva sessioner

Visar alla aktiva sessioner (webbläsare/enheter). Du kan avsluta enskilda sessioner eller alla utom den nuvarande.

### API-nycklar

Egna gratisnycklar för Etherscan, Helius, Solscan, Tronscan, VeChainStats och Subscan. De lagras krypterat och gäller bara ditt konto. Om servern saknar `SECRET_KEY` går det inte att spara nycklar (de lagras aldrig i klartext).

### Anpassade kedjor

Lägg till blockchain-adapters för kedjor som inte stöds direkt:
1. Klicka **Lägg till ny kedja**
2. Ange kedjans namn (t.ex. `MYCHAIN`)
3. Välj adapter-typ (`blockscout` eller `etherscan`)
4. Ange Explorer-URL (måste vara en publik `https://`-adress) och native coin
5. Ange API-nyckel om utforskaren kräver det

### Exportera kontodata (GDPR)

Klicka **Ladda ner min data (JSON)** under **Inställningar → Exportera din data**. Filen innehåller allt som finns sparat om kontot: plånböcker, transaktioner, beräkningar, egna priser, blacklist och inställningar. API-nycklar och sessioner ingår inte. Samma sak finns i API:t: `GET /api/v1/account/export`.

### Radera konto

Under **Inställningar → Radera konto**: skriv `DELETE MY ACCOUNT` i bekräftelsefältet. Allt som hör till kontot raderas direkt och permanent, inklusive priser, API-nycklar och delningslänkar.

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

*Inte* avyttring:
- Flytta kryptovaluta mellan egna plånböcker (korrekt matchad transferering). Anskaffningsvärdet följer med oförändrat.
- Mottagna rewards och staking. De beskattas i stället som inkomst när du får dem.

### Hur mycket av en förlust får jag dra av?

70 %. Exempel: vinst 10 000 kr på ETH och förlust 4 000 kr på SOL ger netto 10 000 − 0,7 × 4 000 = 7 200 kr. Årssidan visar beräkningen.

### Hur hanteras rewards och staking?

Rewards (`REWARD`-transaktioner) inkluderas i T2-rapporten med marknadsvärdet i SEK vid mottagningstillfället. De ingår alltså inte i K4 vid mottagnandet, men påverkar framtida GAV om du säljer dem.

### Varför saknas priser för ett mynt?

Priser hämtas från CoinGecko, Binance och Kraken. Mycket nya, udda eller avlistade mynt saknas ofta. Lägg in ett manuellt pris för dem (se [Priser](#priser)).

### Kan jag använda verktyget för flera börser?

Ja. Importera CSV-filer från alla börser du handlat på. KryptoSkatt avduplicerar automatiskt transaktioner som finns i flera källor (t.ex. om du både hämtar on-chain och importerar från börs för samma adress).

### Vad händer om en TRANSFER_OUT inte matchas?

Den behandlas som en avyttring till marknadspris och flaggas under **Flaggade problem**. Om det faktiskt var en flytt till din egen plånbok: registrera mottagaradressen och hämta dess transaktioner, så matchar KryptoSkatt automatiskt. Du kan också klicka **Till egen plånbok** under **År → Transfereringar** om mottagaren är en plånbok du äger men inte vill lägga till.

---

## Felsökning

### Översikten är tom

Översikten visar då de tre stegen. Följ det som är markerat som nästa steg.

### Import misslyckas med parsningsfel

- Kontrollera att filen är exporterad i rätt format från börsen
- Prova att ange plattform manuellt istället för auto-detektering
- Kontrollera att filen är UTF-8 eller latin-1-kodad (inga specialtecken i filnamnet)

### On-chain-hämtning returnerar inga transaktioner

1. Läs resultatmeddelandet: saknas en nyckel står det vilken (se tabellen [ovan](#vilka-kedjor-behöver-nyckel)). Lägg in en egen gratisnyckel under **Mer → Inställningar → API-nycklar**.
2. Verifiera att adressen är registrerad som **Min** plånbok.
3. Kontrollera i en blockutforskare att det faktiskt finns transaktioner.

### Priset för ett mynt verkar fel

1. Lägg in rätt pris som manuellt pris under **Mer → Priser**. Det går före alla publika källor.
2. Kör beräkning igen.

### Negativt GAV-saldo

Uppstår om det saknas köptransaktioner. Vanliga orsaker:
- Du hanterade kryptovalutan innan du började använda KryptoSkatt
- En börsimport är ofullständig
- Transaktioner existerar på en kedja du inte lagt till

Lösning: importera historiska transaktioner bakåt i tid tills saldot stämmer.

---

## Säkerhetstips

- **Ange aldrig privata nycklar eller seed-fraser** (återställningsord). KryptoSkatt frågar aldrig efter dem. Den som ber om dem försöker stjäla dina tillgångar.
- Behandla konto-ID:t som ett lösenord. Den som har det ser all din data.
- Logga ut på delade datorer. Under **Inställningar → Aktiva sessioner** kan du avsluta inloggningar på andra enheter.
- Delningslänkar till revisorn: välj kort giltighetstid och återkalla dem när de inte behövs.

---

## Integritet och ansvar i korthet

- Inga namn, e-postadresser eller lösenord. Konto-ID:t är din enda nyckel.
- Bara nödvändiga cookies (inloggning och språk). Inga spårare, inga externa typsnitt.
- Du kan när som helst exportera och radera all din data.
- Resultatet är ett underlag. Du ansvarar för din deklaration. Se [villkoren](/villkor), [integritetspolicyn](/integritet) och [Så räknar vi](/om-berakningen).
