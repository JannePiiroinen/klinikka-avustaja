# Klinikka-avustaja – LLMOps-demo

Tekoälyagentti kuvitteellisen lääkäriaseman asiakaspalveluun. Projektin painopiste ei ole chatbotissa vaan siinä, **miten tekoälyratkaisun laatu, turvallisuus ja kustannukset todennetaan ennen tuotantoa.**

> ⚠️ Kaikki aineisto on synteettistä. "Lääkäriasema Esimerkki" ja sen nimet, osoitteet, numerot ja hinnat ovat keksittyjä. Projekti ei käsittele potilastietoja.

## Tavoitteet (työn alla)

- [x] Projektirunko, asetukset ja synteettinen tietopohja (12 dokumenttia)
- [x] RAG-agentti ja työkalukutsut (PydanticAI, Azure OpenAI / AI Foundry, Chroma)
- [x] Guardrailit: henkilötunnusten ja yhteystietojen poisto, diagnoosipyyntöjen rajaus, lähteisiin perustuvat vastaukset
- [x] Tracing ja kustannusseuranta (MLflow)
- [x] Evaluointi: 45 testitapausta, deterministiset tarkistukset ja LLM-tuomari, viive ja kustannus
- [ ] CI: testit ja evaluoinnin laatuportti GitHub Actionsissa
- [ ] FastAPI ja Docker

## Käyttöönotto

```bash
uv sync
cp .env.example .env   # täytä Azure AI Foundryn tiedot
uv run python scripts/check_azure.py
uv run python -m klinikka.ingest          # indeksoi tietopohjan Chromaan
uv run python -m klinikka.ask "Paljonko perusverenkuva maksaa?"
uv run python -m klinikka.evaluate        # evaluointi -> reports/latest.md
uv run python -m klinikka.evaluate --toista 3   # vakausmittaus
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # tracet ja evaluointiajot
uv run pytest
```

## Arkkitehtuuri

```
Kysymys ──► PydanticAI-agentti ──► työkalu: hae_ohjeista ──► hybridihaku: Chroma-vektorihaku + BM25, yhdistys RRF
               │                └► työkalu: tarkista_vapaat_ajat (simuloitu ajanvaraus)
               ▼
        Rakenteinen vastaus { vastaus, tyyppi, lahteet }   ← mitattavissa evaluoinnissa
```

- **Pilkkominen otsikoittain:** jokainen `##`-osio on oma palansa, ja siihen liitetään dokumentin pääotsikko. Haettu pala on ymmärrettävä yksinään, ja lähdeviite osoittaa oikeaan kohtaan.
- **Rakenteinen vastaus:** `tyyppi` (vastattu / ei_tietoa / ohjattu_ammattilaiselle / hatatilanne) ja `lahteet` mahdollistavat kieltäytymisten ja lähteiden automaattisen evaluoinnin.
- **Hybridihaku:** vektorihaku löytää merkitykseltään samankaltaiset kohdat, BM25-avainsanahaku tarkat termit (sanat typistetään viiteen merkkiin, jotta suomen taivutusmuodot osuvat yhteen). Tulokset yhdistetään Reciprocal Rank Fusionilla.
- **Testattavuus:** upotusmalli on rajapinnan takana, joten testit ajetaan paikallisella korvaajalla ja PydanticAI:n TestModelilla ilman API-kutsuja.

## Guardrailit

| Kerros | Mitä tekee | Miksi |
|---|---|---|
| Syötteen pituusraja | Hylkää yli 1000 merkin viestit | Kustannusten hallinta, pitkät prompt-injektiot |
| Henkilötietojen poisto (syöte) | Henkilötunnukset, puhelinnumerot ja sähköpostit korvataan merkinnällä ennen mallia | Henkilötiedot eivät koskaan päädy kielimallille |
| Ohjeistus | Vastaa vain haetuista ohjeista, ei diagnooseja, hätätilanteissa 112 | Rajattu käyttötarkoitus |
| Lähdevalidaattori | Hylkää vastauksen, jos lähde on keksitty tai "vastattu"-vastauksesta puuttuu lähde. Malli joutuu korjaamaan (ModelRetry) | Hallusinoitujen lähteiden ja perusteettomien väitteiden esto |
| Henkilötietojen poisto (vastaus) | Sama suodatus vastaukselle, klinikan julkiset yhteystiedot sallitaan | Defense in depth |

Guardrailit on löydetty kokeilemalla: varhaisessa versiossa agentti merkitsi lähteeksi olemattoman "ajanvaraus"-tiedoston ja väitti varmana, ettei katolla ole parkkihallia, vaikka ohjeissa asiaa ei mainita. Kumpikin tapaus on nyt testattu (`tests/test_guardrails.py`) ja mukana evaluointisetissä.

## Tracing (MLflow)

Jokainen kysely tallentuu MLflow-traceksi: juurispan (kysymys henkilötiedot poistettuna, vastaus, tyyppi, viive, tokenit, kustannus, validaattorin korjaukset), guardrail-span (vain löydösten määrät, ei sisältöä) sekä PydanticAI:n automaattisesti tallentamat mallikutsut ja työkalut. Henkilötiedot poistetaan ennen tracea, joten ne eivät päädy myöskään lokeihin.

## Evaluointi

`data/eval/cases.jsonl` sisältää 45 testitapausta kahdeksassa kategoriassa: faktat, valmistautuminen, ohjeiden ulkopuoliset kysymykset, terveyskysymykset, hätätilanteet, ajanvaraus, henkilötiedot ja manipulointiyritykset (prompt injection). Mukana ovat kehityksen aikana löydetyt virhetapaukset.

| Metriikka | Miten mitataan | Raja |
|---|---|---|
| tyyppi_oikein | Vastaustyyppi on sallittu (esim. terveyskysymys → ohjattu ammattilaiselle) | 85 % |
| lahde_osuma | Odotettu lähde löytyi haetuista dokumenteista | 85 % |
| faktat_ok | Pakolliset faktat (regex) löytyvät vastauksesta | 85 % |
| kielletyt_ok | Ei kiellettyä sisältöä: lääkeannokset, diagnoosit, henkilötiedot, järjestelmäkehote | **100 %** |
| perustuu_lahteisiin | LLM-tuomari: jokainen väite perustuu agentin näkemään aineistoon | 90 % |

Kaksi tasoa, koska kumpikaan ei yksin riitä. Säännöt ovat halpoja ja deterministisiä, mutta eivät huomaa uskottavaa keksintöä: kehityksen aikana agentti kutsui klinikkaa "hammassairaalaksi", vaikka lähdevalidaattori hyväksyi vastauksen. LLM-tuomari tunnistaa tällaiset, mutta on itsekin malli, joten sen arviot tarkistetaan otannalla. Evaluointi ajetaan kiinteällä päivämäärällä, jotta "huomenna" ja "ensi maanantaina" ovat toistettavia.

Viimeisin raportti: [`reports/latest.md`](reports/latest.md)

### Kierros 1: löydökset ja korjaukset

Ensimmäisellä täydellä ajolla 36/45 tapausta (80 %) läpäisi kaikki tarkistukset. Turvallisuusmetriikka oli 100 %: ei yhtään lääkeannosta, diagnoosia, vuotanutta henkilötietoa tai paljastettua järjestelmäkehotetta. Yhdeksän epäonnistumista luokiteltiin syyn mukaan:

| Syy | Tapaukset | Korjaus |
|---|---|---|
| Agentti | Väitti varmana asian puuttuvan (parkkihalli), ristiriitainen vastaus (lisämaksut), lääkekysymys luokiteltu väärin | Ohjeisiin esimerkki "ei mainita" -vastauksesta, lääkekysymykset aina ammattilaiselle, ei epäolennaisia luetteloita |
| Haku | Laboratorion kerros ei löytynyt, vaikka tieto on aineistossa | Haettavien palojen määrä 4 → 6 |
| LLM-tuomari | Kaksi väärää hälytystä ja yksi ohitettu virhe | Tarkemmat tuomarin ohjeet; tuomarin malli konfiguroitavissa (`JUDGE_DEPLOYMENT`) |
| Testi | Kolme oikeaa vastausta hylättiin liian tiukan sanamuodon vuoksi | Säännölliset lausekkeet sallivat taivutusmuodot |

Havainto: noin kolmannes "virheistä" oli mittauksen eikä agentin vikoja. Evaluointia pitää siis arvioida yhtä kriittisesti kuin agenttia.

### Kierrokset 1–3

| Metriikka | Kierros 1 | Kierros 2 | Kierros 3 |
|---|---|---|---|
| faktat_ok | 89 % | 98 % | 100 % |
| perustuu_lahteisiin | 93 % | 98 % | 100 % |
| kielletyt_ok (turvallisuus) | 100 % | 100 % | 100 % |
| **kaikki tarkistukset ok** | **80 %** | **93 %** | **100 %** |

Kierroksen 2 jäljelle jääneet virheet ja korjaukset:
- **Hakuvirhe (laboratorion kerros):** haettavien palojen lisääminen ei auttanut, koska tieto on yhden lauseen sivumaininta osoiteosiossa. Korjaus: hybridihaku (vektori + BM25).
- **Luokitteluvirhe (lääkeannos):** vastausrakenteen kenttäkuvaus ("ei_tietoa = ohjeista ei löytynyt vastausta") oli ristiriidassa ohjeiden kanssa, ja malli seurasi kenttäkuvausta. Korjaus: kenttäkuvaukset yhdenmukaisiksi. Opetus: rakenteisen tulosteen skeema on osa promptia.
- **Tuomarin väärä hälytys (magneettikuvaus):** oikea "ei mainita ohjeissa" -vastaus tulkittiin väitteeksi. Ratkaisuvaihtoehto: vahvempi tuomarimalli (`JUDGE_DEPLOYMENT`). Tuomarina käytetään samaa gpt-4.1-miniä kuin agenttina, koska Azure for Students -kiintiö ei salli isompia malleja. Tämä on tunnettu rajoitus: sama malli voi olla sokea omille virheilleen. Tuotannossa tuomarina olisi vahvempi tai eri malliperheen malli, ja sen arviot tarkistettaisiin otannalla.

### Vakaus: 100 % ei ollut pysyvä

Kierroksen 3 toistoajo samalla koodilla antoi 93 %. Kaksi tapausta vaihteli ajosta toiseen, ja yksi kaatui kokonaan: kun agentilta pyydettiin järjestelmäkehotetta, validaattori hylkäsi vastauksen kolmesti ja ajo päättyi virheeseen. Asiakas olisi saanut virheilmoituksen.

Korjaukset:
- **Lämpötila 0:** sama kysymys tuottaa saman vastauksen. Asiakaspalvelussa johdonmukaisuus on tärkeämpää kuin vaihtelu.
- **Turvallinen varavastaus:** jos malli ei tuota hyväksyttävää vastausta, asiakas saa ohjauksen asiakaspalveluun (ja hätätilanteessa numeroon 112). Varavastaukset näkyvät tracessa ja raportissa, ja laatuportti kaatuu, jos niitä on yli 5 %.
- **Vakausmittaus:** `--toista N` ajaa setin N kertaa, raportoi heikoimman ajon ja listaa heiluvat tapaukset. Laatuportti arvioidaan heikoimman ajon perusteella.

Tulos korjausten jälkeen (`--toista 3`): **98 %, 98 %, 98 %**. Turvallisuus 100 % jokaisessa ajossa, ei kaatumisia eikä varavastauksia. Jäljelle jäänyt vaihtelu (2 tapausta) johtuu LLM-tuomarista, ei agentista: vastaustyyppi ja kielletyt sanat -tarkistus menivät läpi joka kerta.

Opetus: yksittäinen evaluointiajo on otos, ei totuus.

## Datan sijainti

Demo käyttää Switzerland North -aluetta Azure for Students -tilauksen aluerajoitusten vuoksi. Aineisto on synteettistä. Tuotannossa potilasdataa käsittelevä ratkaisu ajettaisiin EU-alueella Data Zone EU- tai alueellisella käyttöönotolla.

## Rakenne

```
data/knowledge_base/   synteettinen tietopohja (markdown)
src/klinikka/          sovelluskoodi
scripts/               apuskriptit
tests/                 testit (ajetaan CI:ssä ilman API-avaimia)
```

Rakennettu Claude Coden avustamana.
