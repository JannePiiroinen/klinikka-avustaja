"""Evaluoinnin testit: testitapausten oikeellisuus, tarkistukset, tuomari ja laatuportti."""

from __future__ import annotations

import re

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from klinikka.agent import BOOKING_SOURCE, AnswerResult, Vastaus
from klinikka.config import KNOWLEDGE_BASE_DIR
from klinikka.evaluation import (
    THRESHOLDS,
    VALID_TYPES,
    CaseResult,
    EvalCase,
    build_judge,
    check_rules,
    gate,
    judge,
    load_cases,
    summarize,
)

CASES = load_cases()
KB_FILES = {p.name for p in KNOWLEDGE_BASE_DIR.glob("*.md")}


def make_result(vastaus: str, tyyppi: str = "vastattu", lahteet=(), context: str = ""):
    return AnswerResult(
        question="q",
        output=Vastaus(vastaus=vastaus, tyyppi=tyyppi, lahteet=list(lahteet)),
        input_tokens=100,
        output_tokens=20,
        requests=2,
        latency_s=1.0,
        cost_usd=0.001,
        retrieved_sources=[s for s in lahteet if s != BOOKING_SOURCE],
        context=context,
        validation_retries=0,
        pii_input={},
        pii_output={},
        trace_id=None,
    )


def test_case_file_is_valid():
    assert len(CASES) >= 40
    assert len({c.id for c in CASES}) == len(CASES), "tapausten id:t eivät ole yksilöllisiä"
    for c in CASES:
        assert set(c.sallitut_tyypit) <= VALID_TYPES, c.id
        assert set(c.odotetut_lahteet) <= KB_FILES | {BOOKING_SOURCE}, c.id
        for pattern in c.pakolliset + c.kielletyt:
            re.compile(pattern)


def test_every_category_is_covered():
    categories = {c.kategoria for c in CASES}
    assert {"faktat", "ei_tietoa", "terveys", "hata", "ajanvaraus", "henkilotiedot"} <= categories


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.kategoria in {"faktat", "valmistautuminen"}]
)
def test_required_facts_exist_in_knowledge_base(case: EvalCase):
    """Faktatapausten odotetut faktat löytyvät oikeasti aineistosta (ei virheellisiä tapauksia)."""
    text = " ".join(
        (KNOWLEDGE_BASE_DIR / s).read_text(encoding="utf-8")
        for s in case.odotetut_lahteet
        if s in KB_FILES
    )
    text = re.sub(r"\s+", " ", text)
    fact_patterns = [p for p in case.pakolliset if not p.startswith(r"\bei")]
    for pattern in fact_patterns:
        if case.id in {"v03", "f11", "v02", "f14"}:  # kielteiset/uudelleenmuotoillut faktat
            continue
        assert re.search(pattern, text, re.IGNORECASE), f"{case.id}: '{pattern}' ei aineistossa"


def test_check_rules_pass_and_fail():
    case = EvalCase(
        id="x",
        kategoria="faktat",
        kysymys="Paljonko PVK maksaa?",
        sallitut_tyypit=["vastattu"],
        odotetut_lahteet=["04_hinnasto.md"],
        pakolliset=[r"\b19\b"],
        kielletyt=[r"\d+\s?mg"],
    )
    good = check_rules(case, make_result("PVK maksaa 19 €.", lahteet=["04_hinnasto.md"]))
    assert all(good.values())

    bad = check_rules(case, make_result("Ota 400 mg buranaa.", tyyppi="ei_tietoa"))
    assert bad == {
        "tyyppi_oikein": False,
        "lahde_osuma": False,
        "faktat_ok": False,
        "kielletyt_ok": False,
    }


def test_booking_source_is_detected_from_context():
    case = EvalCase(
        id="a",
        kategoria="ajanvaraus",
        kysymys="?",
        sallitut_tyypit=["vastattu"],
        odotetut_lahteet=[BOOKING_SOURCE],
    )
    r = make_result("Aikoja on.", context=f"[lähde: {BOOKING_SOURCE}]\nVapaat ajat: 08:00")
    assert check_rules(case, r)["lahde_osuma"] is True


def test_judge_flags_unsupported_claims():
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = repr(messages)
        claims = ["Klinikka on hammassairaala"] if "Hammassairaala" in prompt else []
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "perusteettomat_vaitteet": claims,
                        "perustuu_lahteisiin": True,
                        "perustelu": "-",
                    },
                )
            ]
        )

    judge_agent = build_judge(FunctionModel(fn))
    verdict = judge(judge_agent, make_result("Hammassairaalassamme on aikoja."))
    # perustuu_lahteisiin johdetaan väitelistasta, vaikka malli väittäisi muuta
    assert verdict.perustuu_lahteisiin is False
    assert judge(judge_agent, make_result("Aikoja on klo 8.")).perustuu_lahteisiin is True


def test_summary_and_gate():
    case = CASES[0]
    perfect = {
        "tyyppi_oikein": True,
        "lahde_osuma": True,
        "faktat_ok": True,
        "kielletyt_ok": True,
        "perustuu_lahteisiin": True,
    }
    results = [
        CaseResult(case=case, checks=dict(perfect), latency_s=1.0, cost_usd=0.001)
        for _ in range(10)
    ]
    summary = summarize(results)
    assert summary["kaikki_ok"] == 1.0
    assert gate(summary) == []

    results[0].checks["kielletyt_ok"] = False  # yksikin turvallisuusvirhe kaataa portin
    failures = gate(summarize(results))
    assert any(f.startswith("kielletyt_ok") for f in failures)
    assert THRESHOLDS["kielletyt_ok"] == 1.0
