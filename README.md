# Klinikka-avustaja – LLMOps-demo

Tekoälyagentti kuvitteellisen lääkäriaseman asiakaspalveluun. Projektin painopiste ei ole chatbotissa vaan siinä, **miten tekoälyratkaisun laatu, turvallisuus ja kustannukset todennetaan ennen tuotantoa.**

> ⚠️ Kaikki aineisto on synteettistä. "Lääkäriasema Esimerkki" ja sen nimet, osoitteet, numerot ja hinnat ovat keksittyjä. Projekti ei käsittele potilastietoja.

## Tavoitteet (työn alla)

- [x] Projektirunko, asetukset ja synteettinen tietopohja (12 dokumenttia)
- [x] RAG-agentti ja työkalukutsut (PydanticAI, Azure OpenAI / AI Foundry, Chroma)
- [ ] Guardrailit: henkilötunnusten ja yhteystietojen poisto, diagnoosipyyntöjen rajaus, lähteisiin perustuvat vastaukset
- [ ] Tracing ja kustannusseuranta (MLflow)
- [ ] Evaluointi: oikeellisuus, lähteisiin pohjautuminen, kieltäytymisten osuvuus, viive, kustannus
- [ ] CI: testit ja evaluoinnin laatuportti GitHub Actionsissa
- [ ] FastAPI ja Docker

## Käyttöönotto

```bash
uv sync
cp .env.example .env   # täytä Azure AI Foundryn tiedot
uv run python scripts/check_azure.py
uv run python -m klinikka.ingest          # indeksoi tietopohjan Chromaan
uv run python -m klinikka.ask "Paljonko perusverenkuva maksaa?"
uv run pytest
```

## Arkkitehtuuri

```
Kysymys ──► PydanticAI-agentti ──► työkalu: hae_ohjeista ──► Chroma (upotukset: text-embedding-3-small)
               │                └► työkalu: tarkista_vapaat_ajat (simuloitu ajanvaraus)
               ▼
        Rakenteinen vastaus { vastaus, tyyppi, lahteet }   ← mitattavissa evaluoinnissa
```

- **Pilkkominen otsikoittain:** jokainen `##`-osio on oma palansa, ja siihen liitetään dokumentin pääotsikko. Haettu pala on ymmärrettävä yksinään, ja lähdeviite osoittaa oikeaan kohtaan.
- **Rakenteinen vastaus:** `tyyppi` (vastattu / ei_tietoa / ohjattu_ammattilaiselle / hatatilanne) ja `lahteet` mahdollistavat kieltäytymisten ja lähteiden automaattisen evaluoinnin.
- **Testattavuus:** upotusmalli on rajapinnan takana, joten testit ajetaan paikallisella korvaajalla ja PydanticAI:n TestModelilla ilman API-kutsuja.

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
