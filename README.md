# Klinikka-avustaja – LLMOps-demo

Tekoälyagentti kuvitteellisen lääkäriaseman asiakaspalveluun. Projektin painopiste ei ole chatbotissa vaan siinä, **miten tekoälyratkaisun laatu, turvallisuus ja kustannukset todennetaan ennen tuotantoa.**

> ⚠️ Kaikki aineisto on synteettistä. "Lääkäriasema Esimerkki" ja sen nimet, osoitteet, numerot ja hinnat ovat keksittyjä. Projekti ei käsittele potilastietoja.

## Tavoitteet (työn alla)

- [x] Projektirunko, asetukset ja synteettinen tietopohja (12 dokumenttia)
- [ ] RAG-agentti ja työkalukutsut (PydanticAI, Azure OpenAI / AI Foundry)
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
uv run pytest
```

## Rakenne

```
data/knowledge_base/   synteettinen tietopohja (markdown)
src/klinikka/          sovelluskoodi
scripts/               apuskriptit
tests/                 testit (ajetaan CI:ssä ilman API-avaimia)
```

Rakennettu Claude Coden avustamana.
