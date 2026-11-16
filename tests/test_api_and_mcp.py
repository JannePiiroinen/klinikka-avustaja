"""REST-rajapinnan (FastAPI) ja MCP-palvelimen testit ilman API-kutsuja."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from klinikka import api, mcp_server
from klinikka.agent import build_agent
from klinikka.guardrails import MAX_INPUT_CHARS
from klinikka.service import AssistantService

NO_INFO = {"vastaus": "Ohjeissa ei mainita asiaa.", "tyyppi": "ei_tietoa", "lahteet": []}


@pytest.fixture
def service(retriever) -> AssistantService:
    return AssistantService(
        retriever=retriever, agent=build_agent(TestModel(custom_output_args=NO_INFO))
    )


@pytest.fixture
def client(service):
    api.app.state.service = service
    with TestClient(api.app) as c:
        yield c
    api.app.state.service = None


# --- REST ----------------------------------------------------------------------------------


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["hakuindeksin_paloja"] > 0


def test_kysy_returns_structured_answer(client):
    r = client.post("/kysy", json={"kysymys": "Onko teillä saunaa?"})
    assert r.status_code == 200
    body = r.json()
    assert body["tyyppi"] == "ei_tietoa"
    assert body["varavastaus"] is False
    assert body["viive_ms"] >= 0


def test_kysy_reports_redacted_personal_data(client):
    r = client.post("/kysy", json={"kysymys": "Hetuni on 131052-308T, voinko varata ajan?"})
    assert r.status_code == 200
    assert r.json()["poistetut_henkilotiedot"] == {"henkilötunnus": 1}
    assert "131052-308T" not in r.text


@pytest.mark.parametrize("kysymys", ["", "a" * (MAX_INPUT_CHARS + 1)])
def test_kysy_validates_input_length(client, kysymys):
    assert client.post("/kysy", json={"kysymys": kysymys}).status_code == 422


def test_openapi_docs_are_available(client):
    assert client.get("/openapi.json").json()["info"]["title"] == "Klinikka-avustaja"


# --- MCP -----------------------------------------------------------------------------------


@pytest.fixture
def mcp_service(service):
    mcp_server._service = service
    yield
    mcp_server._service = None


def _call(name: str, args: dict):
    result = asyncio.run(mcp_server.mcp.call_tool(name, args))
    assert not result.is_error, result.content
    data = result.structured_content
    return data["result"] if set(data) == {"result"} else data


def test_mcp_lists_three_tools():
    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert tools == {"kysy_klinikalta", "hae_klinikan_ohjeista", "vapaat_ajat"}


def test_mcp_search_returns_sources(mcp_service):
    hits = _call("hae_klinikan_ohjeista", {"kysely": "Missä kerroksessa laboratorio on?"})
    assert any("1. kerroksessa" in h["teksti"] for h in hits)
    assert all(h["lahde"].endswith(".md") for h in hits)


def test_mcp_ask_goes_through_the_agent(mcp_service):
    out = _call("kysy_klinikalta", {"kysymys": "Onko teillä saunaa?"})
    assert out["tyyppi"] == "ei_tietoa"


def test_mcp_free_slots(mcp_service):
    next_sunday = date.today() + timedelta(days=(6 - date.today().weekday()) or 7)
    assert _call("vapaat_ajat", {"palvelu": "yleislääkäri", "paiva": next_sunday.isoformat()}) == []
    past = (date.today() - timedelta(days=1)).isoformat()
    assert _call("vapaat_ajat", {"palvelu": "yleislääkäri", "paiva": past}) == []
