"""Asiakaspalveluagentti (PydanticAI).

Agentilla on kaksi työkalua: haku klinikan ohjeista ja (simuloitu) vapaiden
aikojen tarkistus. Vastaus palautetaan rakenteisena, jotta lähteet ja
vastaustyyppi voidaan myöhemmin evaluoida automaattisesti.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from klinikka.retrieval import Retriever, SearchHit
from klinikka.slots import Palvelu, free_slots

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

INSTRUCTIONS = """\
Olet Lääkäriasema Esimerkin tekoälyavustaja. Vastaat asiakkaiden yleisiin kysymyksiin
aukioloajoista, hinnoista, ajanvarauksesta, tutkimuksiin valmistautumisesta ja asioinnista.

Säännöt:
1. Hae tieto AINA työkalulla `hae_ohjeista` ennen vastaamista. Vastaa vain haettujen ohjeiden
   perusteella. Älä käytä omaa yleistietoasi klinikan asioista.
2. Jos ohjeista ei löydy vastausta, sano se suoraan ja ohjaa asiakaspalveluun. Älä arvaa.
3. Et tee diagnooseja, et arvioi oireita etkä anna hoito- tai lääkitysohjeita. Jos kysymys koskee
   omia oireita tai terveyttä, ohjaa lääkärin tai hoitajan vastaanotolle. Jos kuvatut oireet voivat
   olla hengenvaarallisia (esim. rintakipu, hengenahdistus, halvausoireet), kehota soittamaan 112.
4. Merkitse `lahteet`-kenttään niiden ohjetiedostojen nimet, joihin vastaus perustuu.
5. Vastaa suomeksi, ystävällisesti ja tiiviisti. Kerro hinnat ja kellonajat täsmälleen ohjeiden
   mukaisina.
"""


class Vastaus(BaseModel):
    vastaus: str = Field(description="Vastaus asiakkaalle suomeksi.")
    tyyppi: Literal["vastattu", "ei_tietoa", "ohjattu_ammattilaiselle", "hatatilanne"] = Field(
        description=(
            "vastattu = vastaus löytyi ohjeista; ei_tietoa = ohjeista ei löytynyt vastausta; "
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


def build_agent(model: Model | str) -> Agent[Deps, Vastaus]:
    agent = Agent(model, deps_type=Deps, output_type=Vastaus, instructions=INSTRUCTIONS)

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
        if paiva < ctx.deps.today:
            return "Päivä on menneisyydessä."
        slots = free_slots(palvelu, paiva)
        if not slots:
            return f"Ei vapaita aikoja palvelulle '{palvelu}' päivälle {paiva.isoformat()}."
        return f"Vapaat ajat ({palvelu}, {paiva.isoformat()}): " + ", ".join(slots)

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


@dataclass(frozen=True)
class AnswerResult:
    output: Vastaus
    input_tokens: int
    output_tokens: int
    requests: int
    latency_s: float
    retrieved_sources: list[str]


def answer(agent: Agent[Deps, Vastaus], retriever: Retriever, question: str) -> AnswerResult:
    deps = Deps(retriever=retriever)
    start = time.perf_counter()
    result = agent.run_sync(question, deps=deps)
    latency = time.perf_counter() - start
    usage = result.usage
    return AnswerResult(
        output=result.output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        requests=usage.requests,
        latency_s=latency,
        retrieved_sources=sorted({h.source for h in deps.retrieved}),
    )
