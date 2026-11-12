"""Asiakaspalveluagentti (PydanticAI).

Agentilla on kaksi työkalua: haku klinikan ohjeista ja (simuloitu) vapaiden
aikojen tarkistus. Vastaus palautetaan rakenteisena, jotta lähteet ja
vastaustyyppi voidaan evaluoida automaattisesti.

Guardrailit:
- Syöte tarkistetaan (pituus) ja siitä poistetaan henkilötiedot ennen mallia.
- Output-validaattori hylkää vastauksen, jos malli ilmoittaa lähteen, jota se ei
  oikeasti hakenut, tai väittää vastanneensa ilman lähteitä. Malli joutuu
  tällöin korjaamaan vastauksensa (ModelRetry).
- Vastauksesta poistetaan henkilötiedot ennen palautusta (julkiset klinikan
  yhteystiedot sallitaan).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from klinikka.config import KNOWLEDGE_BASE_DIR
from klinikka.guardrails import check_input, public_contacts, redact_pii
from klinikka.retrieval import Retriever, SearchHit
from klinikka.slots import Palvelu, free_slots

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

BOOKING_SOURCE = "ajanvarausjärjestelmä"

INSTRUCTIONS = f"""\
Olet Lääkäriasema Esimerkin tekoälyavustaja. Vastaat asiakkaiden yleisiin kysymyksiin
aukioloajoista, hinnoista, ajanvarauksesta, tutkimuksiin valmistautumisesta ja asioinnista.

Säännöt:
1. Hae tieto AINA työkalulla `hae_ohjeista` ennen kuin vastaat klinikkaa koskevaan kysymykseen.
   Vastaa vain haettujen ohjeiden perusteella. Älä käytä omaa yleistietoasi klinikan asioista.
2. Jos kysyttyä asiaa ei mainita ohjeissa, ÄLÄ väitä sen olevan tai puuttuvan. Sano, että
   ohjeissa ei mainita asiaa, kerro tarvittaessa lähin ohjeista löytyvä tieto ja ohjaa
   asiakaspalveluun. Merkitse tällöin tyypiksi `ei_tietoa`.
3. Et tee diagnooseja, et arvioi oireita etkä anna hoito- tai lääkitysohjeita. Jos kysymys koskee
   omia oireita tai terveyttä, ohjaa lääkärin tai hoitajan vastaanotolle. Jos kuvatut oireet voivat
   olla hengenvaarallisia (esim. rintakipu, hengenahdistus, halvausoireet), kehota soittamaan 112.
4. Merkitse `lahteet`-kenttään vain niiden ohjetiedostojen nimet, jotka `hae_ohjeista` palautti
   ja joihin vastaus perustuu. Jos käytit työkalua `tarkista_vapaat_ajat`, merkitse lähteeksi
   "{BOOKING_SOURCE}".
5. Viestissä voi olla merkintöjä kuten [HENKILÖTUNNUS POISTETTU]. Ne ovat tietosuojasyistä
   poistettuja tietoja. Älä pyydä asiakasta kertomaan niitä uudelleen.
6. Vastaa suomeksi, ystävällisesti ja tiiviisti. Kerro hinnat ja kellonajat täsmälleen ohjeiden
   mukaisina.
"""


class Vastaus(BaseModel):
    vastaus: str = Field(description="Vastaus asiakkaalle suomeksi.")
    tyyppi: Literal["vastattu", "ei_tietoa", "ohjattu_ammattilaiselle", "hatatilanne"] = Field(
        description=(
            "vastattu = vastaus löytyi ohjeista tai ajanvarausjärjestelmästä; "
            "ei_tietoa = ohjeista ei löytynyt vastausta; "
            "ohjattu_ammattilaiselle = terveyskysymys ohjattiin vastaanotolle; "
            "hatatilanne = kehotettiin soittamaan 112."
        )
    )
    lahteet: list[str] = Field(
        default_factory=list, description="Ohjetiedostot, joihin vastaus perustuu."
    )


@dataclass
class Deps:
    retriever: Retriever
    today: date = field(default_factory=date.today)
    retrieved: list[SearchHit] = field(default_factory=list)
    used_booking: bool = False

    @property
    def allowed_sources(self) -> set[str]:
        allowed = {h.source for h in self.retrieved}
        if self.used_booking:
            allowed.add(BOOKING_SOURCE)
        return allowed


def build_agent(model: Model | str) -> Agent[Deps, Vastaus]:
    agent = Agent(
        model,
        deps_type=Deps,
        output_type=Vastaus,
        instructions=INSTRUCTIONS,
        retries=2,
    )

    @agent.instructions
    def tamanpaiva(ctx: RunContext[Deps]) -> str:
        return f"Tänään on {ctx.deps.today.isoformat()}."

    @agent.tool
    def hae_ohjeista(ctx: RunContext[Deps], kysely: str) -> str:
        """Hakee klinikan ohjeista kysymykseen liittyvät kohdat.

        Args:
            kysely: Hakulause, esim. "verikokeen paasto" tai "ajan peruminen".
        """
        hits = ctx.deps.retriever.search(kysely)
        ctx.deps.retrieved.extend(hits)
        return "\n\n---\n\n".join(f"[lähde: {h.source}]\n{h.text}" for h in hits)

    @agent.tool
    def tarkista_vapaat_ajat(ctx: RunContext[Deps], palvelu: Palvelu, paiva: date) -> str:
        """Tarkistaa vapaat ajat annetulle palvelulle ja päivälle.

        Args:
            palvelu: Palvelu, jolle aikaa haetaan.
            paiva: Päivämäärä muodossa VVVV-KK-PP.
        """
        ctx.deps.used_booking = True
        if paiva < ctx.deps.today:
            return "Päivä on menneisyydessä."
        slots = free_slots(palvelu, paiva)
        if not slots:
            return f"Ei vapaita aikoja palvelulle '{palvelu}' päivälle {paiva.isoformat()}."
        return f"Vapaat ajat ({palvelu}, {paiva.isoformat()}): " + ", ".join(slots)

    @agent.output_validator
    def tarkista_lahteet(ctx: RunContext[Deps], output: Vastaus) -> Vastaus:
        output.lahteet = sorted(set(output.lahteet))
        unknown = [s for s in output.lahteet if s not in ctx.deps.allowed_sources]
        if unknown:
            allowed = ", ".join(sorted(ctx.deps.allowed_sources)) or "(ei yhtään)"
            raise ModelRetry(
                f"Lähteitä {unknown} ei haettu tässä keskustelussa. Sallitut lähteet: {allowed}. "
                "Korjaa lähdeluettelo, tai jos tieto ei perustu haettuihin ohjeisiin, "
                "hae ensin ohjeista tai merkitse tyypiksi ei_tietoa."
            )
        if output.tyyppi == "vastattu" and not output.lahteet:
            raise ModelRetry(
                "Tyyppi on 'vastattu', mutta lähteitä ei ole. Hae tieto työkalulla "
                "hae_ohjeista ja merkitse lähteet, tai muuta tyyppiä."
            )
        return output

    return agent


def build_azure_model() -> Model:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.azure import AzureProvider

    from klinikka.config import Settings

    s = Settings.from_env()
    return OpenAIChatModel(
        s.chat_deployment,
        provider=AzureProvider(
            azure_endpoint=s.azure_endpoint,
            api_version=s.azure_api_version,
            api_key=s.azure_api_key,
        ),
    )


@cache
def _kb_public_contacts() -> frozenset[str]:
    texts = [p.read_text(encoding="utf-8") for p in KNOWLEDGE_BASE_DIR.glob("*.md")]
    return public_contacts(*texts)


@dataclass(frozen=True)
class AnswerResult:
    output: Vastaus
    input_tokens: int
    output_tokens: int
    requests: int
    latency_s: float
    retrieved_sources: list[str]
    validation_retries: int
    pii_input: dict[str, int]
    pii_output: dict[str, int]


def answer(
    agent: Agent[Deps, Vastaus],
    retriever: Retriever,
    question: str,
    today: date | None = None,
) -> AnswerResult:
    clean = redact_pii(check_input(question))
    deps = Deps(retriever=retriever, today=today or date.today())

    start = time.perf_counter()
    result = agent.run_sync(clean.text, deps=deps)
    latency = time.perf_counter() - start

    output = result.output
    out_clean = redact_pii(output.vastaus, allowed=_kb_public_contacts())
    output.vastaus = out_clean.text

    retries = sum(
        1
        for msg in result.all_messages()
        for part in getattr(msg, "parts", [])
        if part.part_kind == "retry-prompt" or getattr(part, "outcome", None) == "retried"
    )
    usage = result.usage
    return AnswerResult(
        output=output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        requests=usage.requests,
        latency_s=latency,
        retrieved_sources=sorted({h.source for h in deps.retrieved}),
        validation_retries=retries,
        pii_input=clean.findings,
        pii_output=out_clean.findings,
    )
