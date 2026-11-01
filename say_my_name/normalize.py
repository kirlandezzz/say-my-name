"""Normalisation of names, legal forms, addresses and cities (matcher side).

The abbreviation table holds the *common* abbreviations only. The generator
also produces rarer ones on purpose ("Cial.", "Dtbciones."), the kind a
hand-made table misses in real migrations.
"""

from __future__ import annotations

import re
import unicodedata

from .reference import CITIES

STOPWORDS = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "E"}

ABBREVIATIONS = {
    "CONST": "CONSTRUCCIONES",
    "CONSTR": "CONSTRUCCIONES",
    "DIST": "DISTRIBUCIONES",
    "DISTRIB": "DISTRIBUCIONES",
    "TRANSP": "TRANSPORTES",
    "TTES": "TRANSPORTES",
    "SUMIN": "SUMINISTROS",
    "INST": "INSTALACIONES",
    "ING": "INGENIERIA",
    "LOG": "LOGISTICA",
    "ALIM": "ALIMENTACION",
    "MAQ": "MAQUINARIA",
    "SERV": "SERVICIOS",
    "SERVS": "SERVICIOS",
    "COM": "COMERCIAL",
    "COMERC": "COMERCIAL",
    "INDS": "INDUSTRIAS",
    "HNOS": "HERMANOS",
    "CIA": "COMPANIA",
    "GRAL": "GENERAL",
}

# Words too common to identify a company; excluded from blocking keys.
GENERIC_WORDS = {
    "CONSTRUCCIONES", "DISTRIBUCIONES", "TRANSPORTES", "SUMINISTROS",
    "INSTALACIONES", "INGENIERIA", "LOGISTICA", "ALIMENTACION", "MAQUINARIA",
    "SERVICIOS", "TALLERES", "COMERCIAL", "INDUSTRIAS", "ENVASES",
    "CLIMATIZACION", "RECAMBIOS", "COMPONENTES", "ELECTRICIDAD", "HERMANOS",
    "GRUPO", "NORTE", "SUR", "LEVANTE", "CANARIAS", "ATLANTICO", "IBERICA",
    "CENTRO", "MEDITERRANEO", "COMPANIA", "GENERAL",
}

_LEGAL_FORMS = (
    ("SLU", r"S L U|SLU|S L UNIPERSONAL|SOCIEDAD LIMITADA UNIPERSONAL"),
    ("SLL", r"S L L|SLL|SOCIEDAD LIMITADA LABORAL"),
    ("SL", r"S L|SL|SOCIEDAD LIMITADA|SDAD LTDA|SOC LTDA|S R L|SRL"),
    ("SA", r"S A|SA|SOCIEDAD ANONIMA|SDAD ANONIMA"),
    ("SCOOP", r"S COOP|SCOOP|SOCIEDAD COOPERATIVA|COOP"),
)
_LEGAL_RES = tuple((form, re.compile(rf"(?:^|\s)(?:{pat})$")) for form, pat in _LEGAL_FORMS)

_STREET_TYPES = (
    ("POLIGONO INDUSTRIAL", r"POL IND|POL INDUSTRIAL|POLIGONO IND|POLIGONO INDUSTRIAL|P I|PI"),
    ("AVENIDA", r"AVDA|AVD|AV|AVENIDA"),
    ("CALLE", r"CALLE|CL|C"),
    ("PLAZA", r"PZA|PLZA|PL|PLAZA"),
    ("PASEO", r"PASEO|PSO|PS|PO"),
    ("CARRETERA", r"CTRA|CRTA|CARRETERA"),
)
_STREET_RES = tuple((kind, re.compile(rf"^(?:{pat})\s")) for kind, pat in _STREET_TYPES)
_ADDRESS_NOISE = {"NO", "NUM", "N", "NAVE", "PARCELA", "KM"}

_CITY_INDEX: dict[str, str] = {}
CITY_PROVINCE: dict[str, str] = {}


def basic(text: str | None) -> str:
    """Upper case, no accents (Ñ -> N, like old systems), no punctuation."""
    s = (text or "").replace("º", "O").replace("ª", "A")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"[^0-9A-Z]+", " ", s)
    return " ".join(s.split())


for _city in CITIES:
    _canonical = basic(_city.name)
    CITY_PROVINCE[_canonical] = _city.province
    for _alias in (_city.name, *_city.aliases):
        _CITY_INDEX[basic(_alias)] = _canonical


def split_legal_form(name: str) -> tuple[str, str]:
    """``'TALVORA SOCIEDAD LIMITADA'`` -> ``('TALVORA', 'SL')``."""
    for form, regex in _LEGAL_RES:
        m = regex.search(name)
        if m:
            return name[: m.start()].strip(), form
    return name, ""


def name_tokens(core: str) -> list[str]:
    tokens = [ABBREVIATIONS.get(t, t) for t in core.split()]
    return [t for t in tokens if t not in STOPWORDS]


def parse_name(name1: str, name2: str) -> tuple[list[str], str]:
    core, legal = split_legal_form(basic(f"{name1} {name2}"))
    return name_tokens(core), legal


def parse_street(street: str) -> tuple[list[str], str]:
    """Return (street-name tokens, house number). ``s/n`` gives number ``SN``."""
    s = basic(street)
    s = re.sub(r"\bS N\b", " SN ", s)
    for kind, regex in _STREET_RES:
        if regex.match(s + " "):
            s = regex.sub("", s + " ", count=1).strip()
            break
    number = ""
    tokens: list[str] = []
    for tok in s.split():
        if tok.isdigit() or tok == "SN":
            number = number or tok.lstrip("0") or "0"
        elif tok not in _ADDRESS_NOISE and tok not in STOPWORDS:
            tokens.append(tok)
    return tokens, number


def canonical_city(city: str) -> str:
    b = basic(city)
    return _CITY_INDEX.get(b, b)


def normalize_postcode(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 4:  # leading zero lost in a numeric field (08012 -> 8012)
        digits = "0" + digits
    return digits if len(digits) == 5 else ""
