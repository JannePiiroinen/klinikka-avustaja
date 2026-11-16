"""REST-rajapinta (FastAPI).

Käynnistys:  uv run uvicorn klinikka.api:app --reload
Dokumentaatio ja kokeilu selaimessa:  http://127.0.0.1:8000/docs

    curl -X POST http://127.0.0.1:8000/kysy -H "Content-Type: application/json" \\
         -d '{"kysymys": "Paljonko perusverenkuva maksaa?"}'
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from klinikka.guardrails import MAX_INPUT_CHARS
from klinikka.service import AssistantService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Testit asettavat oman palvelunsa etukäteen; muuten luodaan oikea palvelu ympäristöstä.
    if getattr(app.state, "service", None) is None:
        if os.getenv("KLINIKKA_TRACING", "1") == "1":
            from klinikka.tracing import setup_tracing

            setup_tracing()
        app.state.service = AssistantService.from_env()
    yield


app = FastAPI(
    title="Klinikka-avustaja",
    version="0.1.0",
    description=(
        "Kuvitteellisen lääkäriaseman tekoälyavustaja. Henkilötiedot poistetaan ennen "
        "kielimallia, vastaukset perustuvat klinikan ohjeisiin ja jokainen kysely jäljitetään."
    ),
    lifespan=lifespan,
)


class KysymysIn(BaseModel):
    kysymys: str = Field(
        min_length=1,
        max_length=MAX_INPUT_CHARS,
        examples=["Pitääkö kolesterolikokeeseen olla syömättä?"],
    )


class VastausOut(BaseModel):
    vastaus: str
    tyyppi: Literal["vastattu", "ei_tietoa", "ohjattu_ammattilaiselle", "hatatilanne"]
    lahteet: list[str]
    varavastaus: bool = Field(description="True, jos malli ei tuottanut hyväksyttävää vastausta.")
    poistetut_henkilotiedot: dict[str, int] = Field(
        description="Kysymyksestä poistettujen henkilötietojen määrät tyypeittäin."
    )
    viive_ms: int
    kustannus_usd: float | None
    trace_id: str | None


class Terveys(BaseModel):
    status: Literal["ok"]
    hakuindeksin_paloja: int


@app.get("/health", response_model=Terveys)
def health(request: Request) -> Terveys:
    service: AssistantService = request.app.state.service
    return Terveys(status="ok", hakuindeksin_paloja=service.retriever.count())


# Synkroninen endpoint: FastAPI ajaa sen säiepoolissa, joten agentin run_sync ei estä muita
# pyyntöjä.
@app.post("/kysy", response_model=VastausOut)
def kysy(body: KysymysIn, request: Request) -> VastausOut:
    service: AssistantService = request.app.state.service
    r = service.ask(body.kysymys)
    return VastausOut(
        vastaus=r.output.vastaus,
        tyyppi=r.output.tyyppi,
        lahteet=r.output.lahteet,
        varavastaus=r.fallback,
        poistetut_henkilotiedot=r.pii_input,
        viive_ms=round(r.latency_s * 1000),
        kustannus_usd=r.cost_usd,
        trace_id=r.trace_id,
    )
