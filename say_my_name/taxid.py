"""Spanish company tax IDs (CIF): check digit, validation and normalisation.

Only legal-entity letters are generated. Personal NIF/NIE (natural persons,
e.g. sole traders) are deliberately out of scope: the dataset contains
companies only, never individuals.
"""

from __future__ import annotations

import random
import re

_LETTER_CONTROL = "JABCDEFGHI"
_DIGIT_CONTROL_TYPES = set("ABEH")
_LETTER_CONTROL_TYPES = set("NPQRSW")
_VALID_TYPES = set("ABCDEFGHJNPQRSUVW")
_CIF_RE = re.compile(r"^([A-Z])(\d{7})([0-9A-J])$")

# Entity-type letter per legal form (S.A. -> A, S.L.* -> B, cooperative -> F).
LETTER_FOR_LEGAL_FORM = {"SA": "A", "SL": "B", "SLU": "B", "SLL": "B", "SCOOP": "F"}


def control_value(digits7: str) -> int:
    """Return the 0-9 control value for the 7 central digits of a CIF."""
    total = 0
    for i, ch in enumerate(digits7):
        d = int(ch)
        if i % 2 == 0:  # 1st, 3rd, 5th and 7th digit are doubled
            d *= 2
            total += d // 10 + d % 10
        else:
            total += d
    return (10 - total % 10) % 10


def make_cif(letter: str, rng: random.Random) -> str:
    digits = f"{rng.randrange(10**7):07d}"
    value = control_value(digits)
    control = _LETTER_CONTROL[value] if letter in _LETTER_CONTROL_TYPES else str(value)
    return f"{letter}{digits}{control}"


def normalize(raw: str | None) -> str:
    """Strip separators and an ``ES`` VAT prefix: ``es b-1234567 4`` -> ``B12345674``."""
    s = re.sub(r"[^0-9A-Za-z]", "", raw or "").upper()
    if len(s) == 11 and s.startswith("ES"):
        s = s[2:]
    return s


def is_valid(cif: str) -> bool:
    m = _CIF_RE.match(cif)
    if not m:
        return False
    letter, digits, control = m.groups()
    if letter not in _VALID_TYPES:
        return False
    value = control_value(digits)
    if letter in _DIGIT_CONTROL_TYPES:
        return control == str(value)
    if letter in _LETTER_CONTROL_TYPES:
        return control == _LETTER_CONTROL[value]
    return control in (str(value), _LETTER_CONTROL[value])
