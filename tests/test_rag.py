"""RAG-putken testit ilman API-kutsuja.

FakeEmbedder tekee sanapussiupotuksen, joten haku toimii paikallisesti ja
deterministisesti. Agentin työkaluketju testataan PydanticAI:n TestModelilla.
"""

from __future__ import annotations

from datetime import date

from pydantic_ai.models.test import TestModel

from klinikka.agent import Deps, Vastaus, answer, build_agent
from klinikka.chunking import chunk_markdown, load_chunks
from klinikka.config import KNOWLEDGE_BASE_DIR
from klinikka.slots import free_slots

# TestModel generoisi muuten satunnaiset lähteet, jotka validaattori (oikein) hylkää.
NO_INFO = {"vastaus": "Ohjeissa ei mainita asiaa.", "tyyppi": "ei_tietoa", "lahteet": []}


def test_chunking_splits_by_section_and_keeps_title():
    md = "# Hinnasto\nJohdanto.\n\n## Laboratorio\n- PVK: 19 €\n\n## Muut\nTekstiä."
    chunks = chunk_markdown("x.md", md)
    assert [c.section for c in chunks] == ["", "Laboratorio", "Muut"]
    assert chunks[1].text.startswith("# Hinnasto\n## Laboratorio")
    assert chunks[1].label == "Hinnasto > Laboratorio"


def test_every_document_produces_chunks():
    chunks = load_chunks(KNOWLEDGE_BASE_DIR)
    sources = {c.source for c in chunks}
    assert len(sources) == len(list(KNOWLEDGE_BASE_DIR.glob("*.md")))
    assert len({c.id for c in chunks}) == len(chunks), "palojen id:t eivät ole yksilöllisiä"


def test_search_finds_relevant_document(retriever):
    hits = retriever.search("mitkä tutkimukset vaativat paaston, paastoa vaativat tutkimukset", k=3)
    assert "05_laboratorioon_valmistautuminen.md" in {h.source for h in hits}


def test_free_slots_are_deterministic_and_respect_opening_hours():
    monday, saturday, sunday = date(2026, 11, 16), date(2026, 11, 21), date(2026, 11, 22)
    assert free_slots("yleislääkäri", monday) == free_slots("yleislääkäri", monday)
    assert free_slots("yleislääkäri", sunday) == []
    assert free_slots("ultraääni", saturday) == []
    assert all("09:00" <= s <= "14:30" for s in free_slots("yleislääkäri", saturday))


def test_agent_calls_tools_and_returns_structured_answer(retriever):
    agent = build_agent(TestModel(custom_output_args=NO_INFO))
    result = answer(agent, retriever, "Paljonko perusverenkuva maksaa?")
    assert isinstance(result.output, Vastaus)
    assert result.retrieved_sources, "agentin olisi pitänyt hakea ohjeista"
    assert result.requests >= 2  # työkalukutsu + lopullinen vastaus


def test_slot_tool_can_be_called_by_agent(retriever):
    agent = build_agent(TestModel(call_tools=["tarkista_vapaat_ajat"], custom_output_args=NO_INFO))
    deps = Deps(retriever=retriever, today=date(2026, 11, 16))
    result = agent.run_sync("Onko vapaita aikoja?", deps=deps)
    tool_returns = [
        part.content
        for msg in result.all_messages()
        for part in getattr(msg, "parts", [])
        if part.part_kind == "tool-return"
    ]
    assert tool_returns, "työkalua ei kutsuttu"
