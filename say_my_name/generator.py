"""Synthetic SAP customer (KNA1) and vendor (LFA1) master data from two legacy
ERP systems, with known duplicates and hard negatives.

Scenario: a fictional group merges two ECC systems (ERP_A and ERP_B) into one
S/4HANA system. Every customer and vendor becomes a Business Partner, so the
duplicates within and across systems have to be found first.

Everything is generated: invented brand names, generic street names and tax
IDs with a valid check digit. The dataset holds legal entities only, with no
natural persons, phones, e-mails or bank details.
"""

from __future__ import annotations

import csv
import random
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from . import taxid
from .reference import CITIES, City

# Sector word -> (common abbreviations, rare abbreviations). The matcher only
# knows the common ones; the rare ones are the long tail of real data.
SECTORS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "Construcciones": (("Const.", "Constr."), ("Cnes.",)),
    "Distribuciones": (("Dist.", "Distrib."), ("Dtbciones.", "Distribuc.")),
    "Transportes": (("Transp.", "Ttes."), ("Trptes.",)),
    "Suministros": (("Sumin.",), ("Sumtros.",)),
    "Instalaciones": (("Inst.",), ("Instal.",)),
    "Ingeniería": (("Ing.",), ("Ingª",)),
    "Logística": (("Log.",), ("Logíst.",)),
    "Alimentación": (("Alim.",), ("Alimentac.",)),
    "Maquinaria": (("Maq.",), ("Maqria.",)),
    "Servicios": (("Serv.", "Servs."), ("Svcs.",)),
    "Talleres": ((), ("Tlls.",)),
    "Comercial": (("Com.", "Comerc."), ("Cial.",)),
    "Industrias": (("Inds.",), ("Indtrias.",)),
    "Envases": ((), ("Envs.",)),
    "Climatización": ((), ("Climat.",)),
    "Recambios": ((), ("Recamb.",)),
    "Componentes": ((), ("Compon.",)),
    "Electricidad": ((), ("Elec.",)),
}
GEO = ("del Norte", "del Sur", "de Levante", "Canarias", "del Atlántico", "Ibérica", "Centro", "Mediterráneo")
TEMPLATES = (("sector_brand", 40), ("sector_brand_geo", 20), ("brand_sector", 20), ("hermanos", 10), ("grupo", 10))

SYL_START = ("Tal", "Bre", "Cor", "Ami", "Ver", "Sol", "Mar", "Gal", "Ron", "Ves",
             "Lum", "Nor", "Fal", "Que", "Dor", "Pra", "Tem", "Ulm", "Zan", "Oro")
SYL_MID = ("vo", "ni", "re", "ta", "lo", "di", "ca", "se", "mi", "ra", "ber", "lan")
SYL_END = ("ra", "ca", "sa", "nia", "lia", "tex", "dor", "men", "gal", "bis", "vet", "zon")

LEGAL_FORMS = (("SL", 60), ("SA", 20), ("SLU", 12), ("SCOOP", 5), ("SLL", 3))
LEGAL_DISPLAY = {
    "SL": ("S.L.", "SL", "S. L.", "Sociedad Limitada", "S.L"),
    "SA": ("S.A.", "SA", "S. A.", "Sociedad Anónima"),
    "SLU": ("S.L.U.", "SLU", "S.L. Unipersonal", "Sociedad Limitada Unipersonal"),
    "SCOOP": ("S. Coop.", "S.Coop.", "Sociedad Cooperativa", "Coop."),
    "SLL": ("S.L.L.", "SLL", "Sociedad Limitada Laboral"),
}
STREET_TYPES = {
    "Calle": ("Calle", "C/", "C/.", "Cl."),
    "Avenida": ("Avenida", "Avda.", "Av."),
    "Plaza": ("Plaza", "Pza."),
    "Paseo": ("Paseo", "Pº", "Pso."),
    "Carretera": ("Carretera", "Ctra."),
}
STREET_NAMES = ("Mayor", "de la Industria", "del Comercio", "de los Artesanos", "Real",
                "del Puerto", "de la Estación", "San Isidro", "de la Paz", "del Mar",
                "de los Molinos", "de la Constitución", "Nueva", "del Carmen",
                "de la Ciencia", "de las Américas", "del Sol", "de la Ribera",
                "de los Olivos", "de la Fragua")
POLIGONOS = ("El Llano", "Las Arenas", "La Campana", "Los Olivares", "San Roque",
             "La Vega", "El Prado", "Las Huertas")
POLIGONO_DISPLAY = ("Pol. Ind.", "Polígono Industrial", "P.I.", "Pol. Industrial")
NUMBER_FORMATS = ("{street}, {n}", "{street} {n}", "{street}, nº {n}", "{street} nº {n}")

SLOTS = (("ERP_A", "KNA1"), ("ERP_A", "LFA1"), ("ERP_B", "KNA1"), ("ERP_B", "LFA1"))
FIRST_KEY = {("ERP_A", "KNA1"): 100000, ("ERP_A", "LFA1"): 300000,
             ("ERP_B", "KNA1"): 500000, ("ERP_B", "LFA1"): 700000}
RECORDS_PER_ENTITY = ((1, 55), (2, 25), (3, 12), (4, 6), (5, 2))
TAX_MISSING_RATE = {"ERP_A": 0.04, "ERP_B": 0.12}
VAT_PRESENT_RATE = 0.6
P_GROUP = 0.08  # entity gets 1-2 sibling companies (same brand, other tax ID)
P_HOMONYM = 0.04  # entity gets a namesake in another city
P_TAX_COPY = 0.2  # sibling/homonym record carries the related company's tax ID

# Noise applied to every record after the first one of an entity.
DUPLICATE_OPS = (
    ("upper", 8), ("accents", 8), ("legal_form_variant", 14), ("legal_form_drop", 6),
    ("abbrev_common", 10), ("abbrev_rare", 5), ("typo_name", 10), ("word_order", 4),
    ("name_split", 5), ("street_variant", 14), ("typo_street", 6), ("city_alias", 8),
    ("postcode_lost_zero", 3), ("postcode_missing", 3), ("tax_missing", 10),
    ("tax_format", 10), ("tax_typo", 4), ("moved", 4), ("renamed", 2),
)
ENTITY_OPS = ("moved", "renamed", "typo_name", "typo_street")
CONFLICTS = (
    {"tax_missing", "tax_format", "tax_typo"},
    {"postcode_missing", "postcode_lost_zero"},
    {"legal_form_drop", "legal_form_variant"},
    {"abbrev_common", "abbrev_rare"},
)

FIELDS = ("RECORD_ID", "SYSTEM", "TABLE", "KEY", "NAME1", "NAME2", "SORTL", "STRAS",
          "PSTLZ", "ORT01", "REGIO", "LAND1", "STCD1", "STCEG")
TRUTH_FIELDS = ("RECORD_ID", "ENTITY_ID", "ENTITY_KIND", "GROUP_ID", "RELATED_ID", "OPS")


@dataclass(frozen=True)
class Entity:
    entity_id: str
    sector: str
    brand: str
    geo: str
    template: str
    legal: str
    cif: str
    street_kind: str  # a STREET_TYPES key, or "Poligono"
    street_name: str
    number: str  # "12", or "s/n" (streets only)
    city: City
    postcode: str
    kind: str = "normal"  # normal | sibling | homonym
    group_id: str = ""
    related_id: str = ""


@dataclass
class Style:
    legal_variant: int = 0
    legal_sep: str = ", "
    drop_legal: bool = False
    abbreviate: str = ""  # "", "common" or "rare"
    swap_order: bool = False
    legal_in_name2: bool = False
    street_variant: int = 0
    number_format: int = 0
    city_alias: str = ""


def _weighted(rng: random.Random, options):
    values, weights = zip(*options)
    return rng.choices(values, weights=weights, k=1)[0]


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _new_brand(rng: random.Random, used: set[str]) -> str:
    """Invented brand: start + 0-2 middle syllables + end (~37,000 combinations)."""
    for _ in range(1000):
        mids = "".join(rng.choice(SYL_MID) for _ in range(_weighted(rng, ((0, 35), (1, 45), (2, 20)))))
        brand = (rng.choice(SYL_START) + mids + rng.choice(SYL_END)).capitalize()
        if brand not in used:
            used.add(brand)
            return brand
    raise RuntimeError("ran out of brand names: add syllables or generate fewer companies")


def _postcode(city: City, rng: random.Random) -> str:
    return f"{city.province}{city.postcode_base + rng.randrange(15):03d}"


def _random_address(rng: random.Random, city: City | None = None) -> dict:
    city = city or rng.choice(CITIES)
    if rng.random() < 0.25:
        street = {"street_kind": "Poligono", "street_name": rng.choice(POLIGONOS),
                  "number": str(rng.randint(1, 60))}
    else:
        kind = _weighted(rng, (("Calle", 60), ("Avenida", 20), ("Plaza", 7), ("Paseo", 7), ("Carretera", 6)))
        number = "s/n" if rng.random() < 0.05 else str(rng.randint(1, 180))
        street = {"street_kind": kind, "street_name": rng.choice(STREET_NAMES), "number": number}
    return {**street, "city": city, "postcode": _postcode(city, rng)}


def _new_entity(entity_id: str, rng: random.Random, used_brands: set[str]) -> Entity:
    legal = _weighted(rng, LEGAL_FORMS)
    template = _weighted(rng, TEMPLATES)
    return Entity(
        entity_id=entity_id,
        sector=rng.choice(tuple(SECTORS)),
        brand=_new_brand(rng, used_brands),
        geo=rng.choice(GEO) if template == "sector_brand_geo" else "",
        template=template,
        legal=legal,
        cif=taxid.make_cif(taxid.LETTER_FOR_LEGAL_FORM[legal], rng),
        **_random_address(rng),
    )


def _sibling(parent: Entity, entity_id: str, rng: random.Random) -> Entity:
    """Same brand, different legal entity: the classic false-merge trap."""
    variants = ["geo", "sector"] + ([] if parent.template == "grupo" else ["holding"])
    variant = rng.choice(variants)
    if variant == "geo":
        e = replace(parent, template="sector_brand_geo", geo=rng.choice([g for g in GEO if g != parent.geo]))
    elif variant == "sector":
        e = replace(parent, template=rng.choice(("sector_brand", "brand_sector")),
                    sector=rng.choice([s for s in SECTORS if s != parent.sector]), geo="")
    else:
        e = replace(parent, template="grupo", geo="")
    legal = "SA" if variant == "holding" else rng.choice((parent.legal, "SLU"))
    address = {} if rng.random() < 0.5 else _random_address(rng)  # half share the group HQ
    return replace(e, entity_id=entity_id, legal=legal,
                   cif=taxid.make_cif(taxid.LETTER_FOR_LEGAL_FORM[legal], rng),
                   kind="sibling", group_id=f"G{parent.entity_id}", related_id=parent.entity_id,
                   **address)


def _homonym(parent: Entity, entity_id: str, rng: random.Random) -> Entity:
    """Same name, unrelated company in another city."""
    city = rng.choice([c for c in CITIES if c.province != parent.city.province])
    return replace(parent, entity_id=entity_id, kind="homonym", group_id="", related_id=parent.entity_id,
                   cif=taxid.make_cif(taxid.LETTER_FOR_LEGAL_FORM[parent.legal], rng),
                   **_random_address(rng, city))


def _typo(word: str, rng: random.Random) -> str:
    positions = [i for i, c in enumerate(word) if c.isalpha()][1:]  # keep the first letter
    if len(positions) < 3:
        return word
    for _ in range(10):
        chars = list(word)
        i = rng.choice(positions)
        kind = rng.choice(("swap", "drop", "double", "replace"))
        if kind == "swap" and i + 1 < len(chars) and chars[i + 1].isalpha():
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif kind == "drop":
            del chars[i]
        elif kind == "double":
            chars.insert(i, chars[i])
        else:
            new = rng.choice([c for c in "aeiourlnst" if c != chars[i].lower()])
            chars[i] = new.upper() if chars[i].isupper() else new
        result = "".join(chars)
        if result != word:
            return result
    return word


def _typo_longest_word(text: str, rng: random.Random) -> str:
    words = text.split(" ")
    i = max(range(len(words)), key=lambda k: len(words[k]))
    words[i] = _typo(words[i], rng)
    return " ".join(words)


def _applicable(op: str, e: Entity) -> bool:
    common, rare = SECTORS[e.sector]
    shows_sector = e.template not in ("hermanos", "grupo")
    if op == "abbrev_common":
        return e.template == "hermanos" or (shows_sector and bool(common))
    if op == "abbrev_rare":
        return e.template == "hermanos" or (shows_sector and bool(rare))
    if op == "word_order":
        return e.template != "grupo"
    if op == "city_alias":
        return bool(e.city.aliases)
    if op == "postcode_lost_zero":
        return e.postcode.startswith("0")
    return True


def _choose_ops(e: Entity, rng: random.Random) -> list[str]:
    wanted = _weighted(rng, ((1, 45), (2, 35), (3, 20)))
    pool = [(op, w) for op, w in DUPLICATE_OPS if _applicable(op, e)]
    chosen: list[str] = []
    while pool and len(chosen) < wanted:
        op = _weighted(rng, pool)
        pool = [(o, w) for o, w in pool if o != op]
        if any(op in group and chosen_op in group for group in CONFLICTS for chosen_op in chosen):
            continue
        chosen.append(op)
    return chosen


def _render_name(e: Entity, style: Style, rng: random.Random) -> tuple[str, str]:
    """Return (name without legal form, legal form text)."""
    sector = e.sector
    if style.abbreviate and e.template not in ("hermanos", "grupo"):
        common, rare = SECTORS[e.sector]
        options = common if style.abbreviate == "common" else rare
        sector = rng.choice(options) if options else sector
    if e.template == "hermanos":
        word = {"common": "Hnos.", "rare": "Hrmnos."}.get(style.abbreviate, "Hermanos")
        parts = [e.brand, word] if style.swap_order else [word, e.brand]
    elif e.template == "grupo":
        parts = ["Grupo", e.brand]
    elif e.template == "sector_brand_geo":
        parts = [e.brand, sector, e.geo] if style.swap_order else [sector, e.brand, e.geo]
    else:
        brand_first = (e.template == "brand_sector") != style.swap_order
        parts = [e.brand, sector] if brand_first else [sector, e.brand]
    variants = LEGAL_DISPLAY[e.legal]
    legal = "" if style.drop_legal else variants[style.legal_variant % len(variants)]
    return " ".join(parts), legal


def _split_name(base: str, legal: str, style: Style) -> tuple[str, str]:
    """Spread the name over NAME1/NAME2 (35 characters each, like SAP)."""
    if style.legal_in_name2:
        if legal:
            return base[:35], legal[:35]
        words = base.split(" ")
        cut = max(1, len(words) // 2)
        return " ".join(words[:cut])[:35], " ".join(words[cut:])[:35]
    full = f"{base}{style.legal_sep}{legal}" if legal else base
    if len(full) <= 35:
        return full, ""
    cut = full.rfind(" ", 0, 36)
    return full[:cut], full[cut + 1 :][:35]


def _render_street(e: Entity, style: Style) -> str:
    if e.street_kind == "Poligono":
        display = POLIGONO_DISPLAY[style.street_variant % len(POLIGONO_DISPLAY)]
        return f"{display} {e.street_name}, nave {e.number}"[:35]
    kinds = STREET_TYPES[e.street_kind]
    head = f"{kinds[style.street_variant % len(kinds)]} {e.street_name}"
    if e.number == "s/n":
        return f"{head}, s/n"[:35]
    return NUMBER_FORMATS[style.number_format].format(street=head, n=e.number)[:35]


def _tax_variant(cif: str, rng: random.Random) -> str:
    return rng.choice((f"{cif[0]}-{cif[1:]}", cif.lower(), f"ES{cif}",
                       f"{cif[0]} {cif[1:8]} {cif[8]}", f"{cif[0]}-{cif[1:8]}-{cif[8]}"))


def _tax_typo(cif: str, rng: random.Random) -> str:
    i = rng.randrange(1, 8)  # any single-digit change breaks the check digit
    digit = rng.choice([d for d in "0123456789" if d != cif[i]])
    return cif[:i] + digit + cif[i + 1 :]


class _Keys:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.next = dict(FIRST_KEY)

    def take(self, slot: tuple[str, str]) -> str:
        value = self.next[slot]
        self.next[slot] = value + self.rng.randint(1, 3)
        return f"{value:010d}"


def _build_record(e: Entity, slot: tuple[str, str], ops: list[str], rng: random.Random,
                  keys: _Keys, used_brands: set[str]) -> tuple[dict, list[str]]:
    system, table = slot
    style = Style()
    applied: list[str] = []
    for op in ops:  # first change the company itself...
        if op not in ENTITY_OPS:
            continue
        applied.append(op)
        if op == "moved":
            same_city = rng.random() < 0.5
            e = replace(e, **_random_address(rng, e.city if same_city else None))
        elif op == "renamed":
            e = replace(e, brand=_new_brand(rng, used_brands))
        elif op == "typo_name":
            e = replace(e, brand=_typo(e.brand, rng))
        elif op == "typo_street":
            e = replace(e, street_name=_typo_longest_word(e.street_name, rng))
    for op in ops:  # ...then how this record writes it
        if op in ENTITY_OPS or not _applicable(op, e):
            continue
        applied.append(op)
        if op == "legal_form_variant":
            style.legal_variant = rng.randrange(1, len(LEGAL_DISPLAY[e.legal]))
            style.legal_sep = rng.choice((", ", " "))
        elif op == "legal_form_drop":
            style.drop_legal = True
        elif op in ("abbrev_common", "abbrev_rare"):
            style.abbreviate = op.removeprefix("abbrev_")
        elif op == "word_order":
            style.swap_order = True
        elif op == "name_split":
            style.legal_in_name2 = True
        elif op == "street_variant":
            style.street_variant = rng.randrange(1, 4)
            style.number_format = rng.randrange(1, len(NUMBER_FORMATS))
        elif op == "city_alias":
            style.city_alias = rng.choice(e.city.aliases)

    base, legal = _render_name(e, style, rng)
    name1, name2 = _split_name(base, legal, style)
    cif = e.cif
    record = {
        "SYSTEM": system, "TABLE": table, "KEY": keys.take(slot),
        "NAME1": name1, "NAME2": name2,
        "SORTL": _strip_accents(e.brand).upper()[:10],
        "STRAS": _render_street(e, style),
        "PSTLZ": e.postcode,
        "ORT01": style.city_alias or e.city.name,
        "REGIO": e.city.province,
        "LAND1": "ES",
        "STCD1": cif,
        "STCEG": f"ES{cif}" if rng.random() < VAT_PRESENT_RATE else "",
    }
    record["RECORD_ID"] = f"{system}/{table}/{record['KEY']}"

    text_fields = ("NAME1", "NAME2", "STRAS", "ORT01")
    for op in applied:
        if op == "upper":
            for f in text_fields:
                record[f] = record[f].upper()
        elif op == "accents":
            for f in text_fields:
                record[f] = _strip_accents(record[f])
        elif op == "postcode_lost_zero":
            record["PSTLZ"] = record["PSTLZ"][1:]
        elif op == "postcode_missing":
            record["PSTLZ"] = ""
        elif op == "tax_format":
            record["STCD1"] = _tax_variant(cif, rng)
        elif op == "tax_typo":
            wrong = _tax_typo(cif, rng)
            record["STCD1"] = wrong
            record["STCEG"] = f"ES{wrong}" if record["STCEG"] else ""
    if "tax_missing" in applied:
        record["STCD1"] = record["STCEG"] = ""
    if system == "ERP_B":  # the older system: upper case, no accents
        for f in text_fields:
            record[f] = _strip_accents(record[f]).upper()
        applied.append("sys_b_style")
    return record, applied


def generate(seed: int, n_entities: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    used_brands: set[str] = set()
    entities = [_new_entity(f"E{i + 1:05d}", rng, used_brands) for i in range(n_entities)]

    extra: list[Entity] = []
    next_id = n_entities + 1
    for i, parent in enumerate(entities):
        if rng.random() < P_GROUP:
            entities[i] = parent = replace(parent, group_id=f"G{parent.entity_id}")
            for _ in range(rng.choice((1, 1, 2))):
                extra.append(_sibling(parent, f"E{next_id:05d}", rng))
                next_id += 1
        if rng.random() < P_HOMONYM:
            extra.append(_homonym(parent, f"E{next_id:05d}", rng))
            next_id += 1
    entities += extra
    by_id = {e.entity_id: e for e in entities}

    keys = _Keys(rng)
    records: list[dict] = []
    truth: list[dict] = []
    for e in entities:
        own: list[tuple[dict, list[str]]] = []
        for idx in range(_weighted(rng, RECORDS_PER_ENTITY)):
            slot = rng.choice(SLOTS)
            ops = [] if idx == 0 else _choose_ops(e, rng)
            if "tax_missing" not in ops and rng.random() < TAX_MISSING_RATE[slot[0]]:
                ops = [o for o in ops if o not in ("tax_format", "tax_typo")] + ["tax_missing"]
            own.append(_build_record(e, slot, ops, rng, keys, used_brands))
        if e.kind != "normal" and rng.random() < P_TAX_COPY:
            record, ops = rng.choice(own)
            wrong = by_id[e.related_id].cif
            record["STCD1"] = wrong
            record["STCEG"] = f"ES{wrong}" if record["STCEG"] else ""
            ops.append("tax_copy_error")
        for record, ops in own:
            records.append(record)
            truth.append({"RECORD_ID": record["RECORD_ID"], "ENTITY_ID": e.entity_id,
                          "ENTITY_KIND": e.kind, "GROUP_ID": e.group_id,
                          "RELATED_ID": e.related_id, "OPS": "|".join(ops)})

    order = list(range(len(records)))
    rng.shuffle(order)
    return [records[i] for i in order], [truth[i] for i in order]


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_dataset(out_dir: Path, seed: int, n_entities: int) -> tuple[Path, Path]:
    records, truth = generate(seed, n_entities)
    records_path, truth_path = out_dir / "records.csv", out_dir / "truth.csv"
    write_csv(records_path, records, FIELDS)
    write_csv(truth_path, truth, TRUTH_FIELDS)
    return records_path, truth_path
