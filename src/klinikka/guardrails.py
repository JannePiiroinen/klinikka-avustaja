"""Syötteen ja tulosteen guardrailit.

1. Henkilötietojen poisto: henkilötunnukset, puhelinnumerot ja sähköpostiosoitteet
   korvataan merkinnällä ENNEN kuin teksti lähetetään kielimallille. Sama suodatus
   ajetaan myös mallin vastaukselle (defense in depth).
2. Syötteen pituusraja: estää kustannusten karkaamisen ja pitkät prompt-injektiot.

Säännöt ovat tarkoituksella yksinkertaisia ja testattavia säännöllisiä lausekkeita.
Tuotannossa näitä täydennettäisiin esimerkiksi nimien tunnistuksella (NER).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_INPUT_CHARS = 1000

# Henkilötunnus: PPKKVV + välimerkki + yksilönumero + tarkiste. Kaikki hetun näköiset
# merkkijonot poistetaan tarkisteesta riippumatta: väärä positiivinen on halvempi kuin vuoto.
_HETU = re.compile(r"\b\d{6}[-+ABCDEFUVWXY]\d{3}[0-9A-Y]\b", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# Suomalaiset puhelinnumerot: +358 tai 0 alussa ja vähintään 6 numeroa perässä.
# Ei osu hintoihin ("19 €") eikä kellonaikoihin ("7.30–18.00").
_PHONE = re.compile(r"(?<![\w+])(?:\+358|00358|0)(?:[ -]?\d){6,11}\b")

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("henkilötunnus", _HETU, "[HENKILÖTUNNUS POISTETTU]"),
    ("sähköposti", _EMAIL, "[SÄHKÖPOSTI POISTETTU]"),
    ("puhelinnumero", _PHONE, "[PUHELINNUMERO POISTETTU]"),
]


@dataclass(frozen=True)
class RedactionResult:
    text: str
    findings: dict[str, int]  # tyyppi -> lukumäärä

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def redact_pii(text: str, allowed: frozenset[str] = frozenset()) -> RedactionResult:
    """Poistaa henkilötiedot. `allowed` sisältää julkiset tiedot (esim. klinikan oma
    puhelinnumero), joita ei poisteta. Vertailu tehdään pelkillä numeroilla/merkeillä."""
    findings: dict[str, int] = {}
    for name, pattern, replacement in _RULES:
        count = 0

        def _sub(match: re.Match[str], replacement: str = replacement) -> str:
            nonlocal count
            value = match.group(0)
            if value.lower() in allowed or _digits(value) in allowed:
                return value
            count += 1
            return replacement

        text = pattern.sub(_sub, text)
        if count:
            findings[name] = count
    return RedactionResult(text=text, findings=findings)


def public_contacts(*texts: str) -> frozenset[str]:
    """Kerää julkisesta aineistosta löytyvät puhelinnumerot ja sähköpostit sallittujen
    listalle, jotta avustaja saa kertoa esimerkiksi klinikan oman numeron."""
    allowed: set[str] = set()
    for text in texts:
        allowed.update(_digits(m) for m in _PHONE.findall(text))
        allowed.update(m.lower() for m in _EMAIL.findall(text))
    return frozenset(allowed)


class InputTooLongError(ValueError):
    pass


def check_input(text: str) -> str:
    text = text.strip()
    if len(text) > MAX_INPUT_CHARS:
        raise InputTooLongError(
            f"Viesti on liian pitkä ({len(text)} merkkiä, enintään {MAX_INPUT_CHARS})."
        )
    return text
