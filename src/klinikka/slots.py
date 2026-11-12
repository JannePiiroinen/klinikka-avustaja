"""Simuloitu ajanvarausjärjestelmä.

Oikeassa ratkaisussa tämä kutsuisi ajanvarauksen rajapintaa. Demossa vapaat
ajat lasketaan deterministisesti päivämäärästä, jotta testit ja evaluointi
ovat toistettavia.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal

Palvelu = Literal[
    "yleislääkäri", "erikoislääkäri", "sairaanhoitaja", "etävastaanotto", "ultraääni", "rokotus"
]

# Aukioloajat aineiston (02_aukioloajat.md) mukaisesti: (ensimmäinen, viimeinen) alkava tunti
_WEEKDAY_HOURS = {"ultraääni": (8, 15)}
_DEFAULT_WEEKDAY = (7, 19)
_SATURDAY = (9, 14)


def free_slots(palvelu: Palvelu, paiva: date) -> list[str]:
    weekday = paiva.weekday()  # 0 = maanantai, 6 = sunnuntai
    if weekday == 6:
        return []
    if weekday == 5:
        if palvelu == "ultraääni":
            return []
        first, last = _SATURDAY
    else:
        first, last = _WEEKDAY_HOURS.get(palvelu, _DEFAULT_WEEKDAY)

    candidates = [f"{h:02d}:{m:02d}" for h in range(first, last + 1) for m in (0, 30)]
    # Deterministinen "varaustilanne": noin kolmannes ajoista on vapaana.
    free = []
    for slot in candidates:
        digest = hashlib.sha256(f"{palvelu}|{paiva.isoformat()}|{slot}".encode()).digest()
        if digest[0] % 3 == 0:
            free.append(slot)
    return free
