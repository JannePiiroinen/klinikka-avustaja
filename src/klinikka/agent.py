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

from klinikka import tracing
from klinikka.config import KNOWLEDGE_BASE_DIR, Settings
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
   Terveyttä, oireita tai lääkkeitä koskeviin kysymyksiin et tarvitse ohjeita (ks. kohta 3).
   Vastaa vain haettujen ohjeiden perusteella. Älä käytä omaa yleistietoasi klinikan asioista.
2. Jos kysyttyä asiaa ei mainita ohjeissa, ÄLÄ väitä sen olevan tai puuttuvan. Sano, että
   ohjeissa ei mainita asiaa, kerro tarvittaessa lähin ohjeista löytyvä tieto ja ohjaa
   asiakaspalveluun. Merkitse tällöin tyypiksi `ei_tietoa`.
   Esimerkki: "Onko teillä sauna?" -> "Ohjeissamme ei mainita saunaa. Asiakaspalvelumme
   kertoo lisää." EI: "Meillä ei ole saunaa."
3. Et tee diagnooseja, et arvioi oireita etkä anna hoito- tai lääkitysohjeita. Jos kysymys koskee
   omia oireita, terveyttä, lääkkeitä tai lääkeannoksia, ohjaa lääkärin tai hoitajan vastaanotolle
   ja merkitse tyypiksi `ohjattu_ammattilaiselle`, vaikka ohjeista ei löytyisi asiaa. Jos kuvatut
   oireet voivat olla hengenvaarallisia (esim. rintakipu, hengenahdistus, halvausoireet), kehota
   soittamaan 112.
4. Merkitse `lahteet`-kenttään vain niiden ohjetiedostojen nimet, jotka `hae_ohjeista` palautti
   ja joihin vastaus perustuu. Jos käytit työkalua `tarkista_vapaat_ajat`, merkitse lähteeksi
   "{BOOKING_SOURCE}".
5. Viestissä voi olla merkintöjä kuten [HENKILÖTUNNUS POISTETTU]. Ne ovat tietosuojasyistä
   poistettuja tietoja. Älä pyydä asiakasta kertomaan niitä uudelleen.
6. Vastaa suomeksi, ystävällisesti ja tiiviisti. Vastaa vain siihen, mitä kysyttiin: älä
   luettele epäolennaisia hintoja tai palveluita. Älä aloita vastausta väitteellä, jota
   seuraavat lauseet kumoavat. Kerro hinnat ja kellonajat täsmälleen ohjeiden mukaisina.
"""


class Vastaus(BaseModel):
    vastaus: str = Field(description="Vastaus asiakkaalle suomeksi.")
    tyyppi: Literal["vastattu", "ei_tietoa", "ohjattu_ammattilaiselle", "hatatilanne"] = Field(
        description=(
            "hatatilanne = kuvatut oireet voivat olla hengenvaarallisia, "
            "kehotettiin soittamaan 112. "
            "ohjattu_ammattilaiselle = kysymys koskee oireita, terveyttä, lääkkeitä tai "
            "lääkeannoksia; käytä AINA näissä, vaikka ohjeista ei löytyisi asiaa. "
            "vastattu = klinikkaa koskeva vastaus löytyi ohjeista tai ajanvarausjärjestelmästä. "
            "ei_tietoa = klinikkaa koskevaa asiaa ei mainita ohjeissa."
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
    booking_outputs: list[str] = field(default_factory=list)

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
            result = "Päivä on menneisyydessä."
        elif slots := free_slots(palvelu, paiva):
            result = f"Vapaat ajat ({palvelu}, {paiva.isoformat()}): " + ", ".join(slots)
        else:
            result = f"Ei vapaita aikoja palvelulle '{palvelu}' päivälle {paiva.isoformat()}."
        ctx.deps.booking_outputs.append(result)
        return result

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


def build_azure_model(deployment: str | None = None) -> Model:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.azure import AzureProvider

    s = Settings.from_env()
    return OpenAIChatModel(
        deployment or s.chat_deployment,
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
    question: str  # henkilötiedot poistettuna
    output: Vastaus
    input_tokens: int
    output_tokens: int
    requests: int
    latency_s: float
    cost_usd: float | None
    retrieved_sources: list[str]
    context: str  # agentin näkemä aineisto: haetut ohjeet ja ajanvarauksen vastaukset
    validation_retries: int
    pii_input: dict[str, int]
    pii_output: dict[str, int]
    trace_id: str | None


def answer(
    agent: Agent[Deps, Vastaus],
    retriever: Retriever,
    question: str,
    today: date | None = None,
    settings: Settings | None = None,
) -> AnswerResult:
    with tracing.span("klinikka-avustaja", "AGENT") as root:
        with tracing.span("henkilotietojen_poisto", "GUARDRAIL") as guard:
            clean = redact_pii(check_input(question))
            guard.set_inputs({"merkkeja": len(question)})
            guard.set_outputs({"loydokset": clean.findings})
        root.set_inputs({"kysymys": clean.text})

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
        cost = settings.cost_usd(usage.input_tokens, usage.output_tokens) if settings else None
        unique_hits = {h.chunk_id: h for h in deps.retrieved}.values()
        context = "\n\n---\n\n".join(
            [f"[lähde: {h.source}]\n{h.text}" for h in unique_hits]
            + [f"[lähde: {BOOKING_SOURCE}]\n{b}" for b in deps.booking_outputs]
        )

        root.set_outputs(output.model_dump())
        root.set_attributes(
            {
                "tyyppi": output.tyyppi,
                "latency_s": round(latency, 3),
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": cost if cost is not None else -1.0,
                "validation_retries": retries,
                "retrieved_sources": ",".join(sorted({h.source for h in deps.retrieved})),
                "pii_input_total": sum(clean.findings.values()),
                "pii_output_total": sum(out_clean.findings.values()),
            }
        )

    return AnswerResult(
        question=clean.text,
        output=output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        requests=usage.requests,
        latency_s=latency,
        cost_usd=cost,
        retrieved_sources=sorted({h.source for h in deps.retrieved}),
        context=context,
        validation_retries=retries,
        pii_input=clean.findings,
        pii_output=out_clean.findings,
        trace_id=tracing.last_trace_id(),
    )
