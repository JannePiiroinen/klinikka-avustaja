"""MCP-palvelin (Model Context Protocol).

Avaa klinikan työkalut mille tahansa MCP-yhteensopivalle asiakkaalle, kuten Claude
Desktopille tai muulle agentille. Asiakkaan oma kielimalli päättää, milloin työkaluja
kutsutaan; guardrailit ovat silti voimassa, koska ne ovat palvelimen puolella.

Käynnistys (stdio, asiakas käynnistää tämän itse):
    uv run python -m klinikka.mcp_server

Työkalut:
    kysy_klinikalta        koko agentti: guardrailit, haku, validaattori, varavastaus
    hae_klinikan_ohjeista  pelkkä hybridihaku tietopohjasta lähteineen
    vapaat_ajat            ajanvarausjärjestelmän vapaat ajat
"""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from klinikka.guardrails import check_input, redact_pii
from klinikka.service import AssistantService
from klinikka.slots import Palvelu, free_slots

mcp = MCPServer(
    "klinikka-avustaja",
    instructions=(
        "Lääkäriasema Esimerkin (kuvitteellinen) työkalut: aukioloajat, hinnat, ajanvaraus ja "
        "tutkimuksiin valmistautuminen. Älä lähetä työkaluille henkilötunnuksia tai "
        "terveystietoja; ne poistetaan automaattisesti."
    ),
)

_service: AssistantService | None = None


class KlinikanVastaus(BaseModel):
    vastaus: str
    tyyppi: str
    lahteet: list[str]
    varavastaus: bool


def get_service() -> AssistantService:
    global _service
    if _service is None:
        _service = AssistantService.from_env()
    return _service


@mcp.tool()
def kysy_klinikalta(kysymys: str) -> KlinikanVastaus:
    """Kysy klinikan tekoälyavustajalta. Vastaus perustuu klinikan ohjeisiin ja sisältää
    lähteet sekä vastaustyypin (vastattu / ei_tietoa / ohjattu_ammattilaiselle / hatatilanne).

    Args:
        kysymys: Asiakkaan kysymys suomeksi, esim. "Paljonko perusverenkuva maksaa?"
    """
    r = get_service().ask(kysymys)
    return KlinikanVastaus(
        vastaus=r.output.vastaus,
        tyyppi=r.output.tyyppi,
        lahteet=r.output.lahteet,
        varavastaus=r.fallback,
    )


@mcp.tool()
def hae_klinikan_ohjeista(kysely: str) -> list[dict]:
    """Hae klinikan ohjeista kyselyyn liittyvät kohdat (hybridihaku: merkitys + avainsanat).

    Args:
        kysely: Hakulause, esim. "verikokeen paasto" tai "ajan peruminen".
    """
    clean = redact_pii(check_input(kysely)).text
    return [
        {"lahde": h.source, "otsikko": h.label, "teksti": h.text}
        for h in get_service().retriever.search(clean)
    ]


@mcp.tool()
def vapaat_ajat(palvelu: Palvelu, paiva: date) -> list[str]:
    """Hae vapaat vastaanottoajat palvelulle ja päivälle (simuloitu ajanvarausjärjestelmä).

    Args:
        palvelu: Palvelu, jolle aikaa haetaan.
        paiva: Päivämäärä muodossa VVVV-KK-PP.
    """
    if paiva < date.today():
        return []
    return free_slots(palvelu, paiva)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
