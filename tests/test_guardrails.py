"""Guardrailien testit: henkilötietojen poisto, pituusraja ja lähdevalidaattori."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from klinikka.agent import answer, build_agent
from klinikka.guardrails import (
    MAX_INPUT_CHARS,
    InputTooLongError,
    check_input,
    public_contacts,
    redact_pii,
)


@pytest.mark.parametrize(
    "text, kind",
    [
        ("Hetuni on 131052-308T, voinko varata ajan?", "henkilötunnus"),
        ("Tyttäreni 010199A123B tarvitsee rokotuksen", "henkilötunnus"),
        ("Soita minulle numeroon 040 123 4567", "puhelinnumero"),
        ("Numeroni on +358401234567", "puhelinnumero"),
        ("Laita tiedot osoitteeseen matti.meikalainen@example.com", "sähköposti"),
    ],
)
def test_pii_is_redacted(text, kind):
    result = redact_pii(text)
    assert result.findings.get(kind) == 1
    assert "POISTETTU" in result.text


@pytest.mark.parametrize(
    "text",
    [
        "Paljonko perusverenkuva maksaa? Hinta 19 € vai 29 €?",
        "Olette auki klo 7.30–18.00, entä lauantaina 9.00–14.00?",
        "Päivystysapu 116 117 ja hätänumero 112.",
        "Pääsenkö 16.11.2026 klo 08:00 vastaanotolle?",
    ],
)
def test_ordinary_text_is_not_redacted(text):
    result = redact_pii(text)
    assert not result.redacted, result.findings
    assert result.text == text


def test_public_clinic_number_is_allowed_in_output():
    allowed = public_contacts("Ajanvaraus: 000 000 000 (kuvitteellinen numero).")
    result = redact_pii("Soita numeroon 000 000 000 tai 040 123 4567.", allowed=allowed)
    assert "000 000 000" in result.text
    assert result.findings == {"puhelinnumero": 1}


def test_input_length_limit():
    assert check_input("  hei  ") == "hei"
    with pytest.raises(InputTooLongError):
        check_input("a" * (MAX_INPUT_CHARS + 1))


def _scripted_model(responses: list[dict]) -> FunctionModel:
    """Malli, joka ensin hakee ohjeista ja palauttaa sitten vuorotellen annetut vastaukset."""
    state = {"step": 0}

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = state["step"]
        state["step"] += 1
        if step == 0:
            return ModelResponse(parts=[ToolCallPart("hae_ohjeista", {"kysely": "hinnasto"})])
        output_tool = info.output_tools[0].name
        args = responses[min(step - 1, len(responses) - 1)]
        return ModelResponse(parts=[ToolCallPart(output_tool, args)])

    return FunctionModel(fn)


def test_validator_forces_retry_on_invented_source(retriever):
    model = _scripted_model(
        [
            {"vastaus": "PVK maksaa 19 €.", "tyyppi": "vastattu", "lahteet": ["keksitty.md"]},
            {"vastaus": "PVK maksaa 19 €.", "tyyppi": "vastattu", "lahteet": ["04_hinnasto.md"]},
        ]
    )
    result = answer(build_agent(model), retriever, "Paljonko PVK maksaa?")
    assert result.validation_retries == 1
    assert result.output.lahteet == ["04_hinnasto.md"]


def test_validator_rejects_answer_without_sources(retriever):
    model = _scripted_model(
        [
            {"vastaus": "Kyllä on.", "tyyppi": "vastattu", "lahteet": []},
            {"vastaus": "Ohjeissa ei mainita asiaa.", "tyyppi": "ei_tietoa", "lahteet": []},
        ]
    )
    result = answer(build_agent(model), retriever, "Onko katolla parkkihalli?")
    assert result.validation_retries == 1
    assert result.output.tyyppi == "ei_tietoa"


def test_pii_never_reaches_the_model(retriever):
    seen: list[str] = []

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(repr(messages))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"vastaus": "Ohjaan vastaanotolle.", "tyyppi": "ohjattu_ammattilaiselle"},
                )
            ]
        )

    result = answer(
        build_agent(FunctionModel(fn)), retriever, "Hetuni on 131052-308T, mikä minua vaivaa?"
    )
    assert result.pii_input == {"henkilötunnus": 1}
    assert all("131052-308T" not in s for s in seen)
