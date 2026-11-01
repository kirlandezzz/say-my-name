"""Baseline matcher: normalise -> block -> score pairs -> cluster.

Every candidate pair lands in one of three bands:
  AUTO    merge without asking
  REVIEW  grey zone: phase 3 sends these to an LLM, and then to a person
  NO      different companies
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from . import normalize as nz
from . import taxid
from .similarity import edit_distance, jaro_winkler, token_similarity

AUTO_THRESHOLD = 0.92
REVIEW_THRESHOLD = 0.75
TAX_NAME_THRESHOLD = 0.75  # same tax ID but names this different -> REVIEW
SAME_NAME_THRESHOLD = 0.95  # same name in another province -> REVIEW (moved, or a namesake)
MAX_BLOCK = 300
WEIGHTS = {"name": 0.6, "address": 0.25, "location": 0.15}
COMPATIBLE_LEGAL = {frozenset({"SL", "SLU"}), frozenset({"SL", "SLL"})}


@dataclass
class Prepared:
    rid: str
    tokens: list[str]
    legal: str
    cif: str  # valid, normalised tax ID or ""
    bad_cif: str  # tax ID that fails the check digit (only when there is no valid one)
    street: list[str]
    number: str
    postcode: str
    city: str
    province: str


@dataclass
class PairResult:
    a: str
    b: str
    band: str
    score: float
    reason: str
    name_sim: float
    address_sim: float
    location_sim: float


def prepare(row: dict) -> Prepared:
    tokens, legal = nz.parse_name(row["NAME1"], row["NAME2"])
    cif = bad_cif = ""
    for raw in (row.get("STCD1"), row.get("STCEG")):
        candidate = taxid.normalize(raw)
        if taxid.is_valid(candidate):
            cif, bad_cif = candidate, ""
            break
        bad_cif = bad_cif or candidate
    street, number = nz.parse_street(row["STRAS"])
    postcode = nz.normalize_postcode(row["PSTLZ"])
    city = nz.canonical_city(row["ORT01"])
    regio = (row.get("REGIO") or "").strip()
    province = regio.zfill(2) if regio else (postcode[:2] or nz.CITY_PROVINCE.get(city, ""))
    return Prepared(row["RECORD_ID"], tokens, legal, cif, bad_cif, street, number, postcode, city, province)


def block_keys(p: Prepared) -> set[str]:
    keys = set()
    if p.cif:
        keys.add(f"T:{p.cif}")
    province = p.province or "??"
    for tok in p.tokens:
        if len(tok) >= 4 and tok not in nz.GENERIC_WORDS:
            keys.add(f"P:{tok[:4]}:{province}")
            keys.add(f"S:{tok[-3:]}:{province}")
            keys.add(f"N:{tok}")  # whole brand, any province: finds companies that moved
    if p.postcode and p.number:
        keys.add(f"A:{p.postcode}:{p.number}")
    return keys


def candidate_pairs(prepared: list[Prepared]) -> tuple[set[tuple[int, int]], dict]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(prepared):
        for key in block_keys(p):
            blocks[key].append(i)
    pairs: set[tuple[int, int]] = set()
    skipped = 0
    for members in blocks.values():
        if len(members) > MAX_BLOCK:
            skipped += 1
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                pairs.add((members[x], members[y]))
    return pairs, {"blocks": len(blocks), "blocks_skipped": skipped}


def location_similarity(a: Prepared, b: Prepared) -> float:
    if a.postcode and b.postcode and a.postcode == b.postcode:
        return 1.0
    if a.city and b.city and a.city == b.city:
        return 0.8
    if a.province and b.province:
        return 0.4 if a.province == b.province else 0.0
    return 0.5


def address_similarity(a: Prepared, b: Prepared) -> float:
    if not a.street or not b.street:
        return 0.5
    street = jaro_winkler(" ".join(a.street), " ".join(b.street))
    number = (1.0 if a.number == b.number else 0.0) if a.number and b.number else 0.5
    return 0.8 * street + 0.2 * number


def tax_typo_apart(a: Prepared, b: Prepared) -> bool:
    """One valid tax ID and one invalid one, a single typo apart (B12345674 / B12845674)."""
    for good, bad in ((a.cif, b.bad_cif), (b.cif, a.bad_cif)):
        if good and len(bad) == len(good) and bad[0] == good[0] and edit_distance(good, bad) == 1:
            return True
    return False


def score_pair(a: Prepared, b: Prepared) -> PairResult:
    name = token_similarity(a.tokens, b.tokens)
    address = address_similarity(a, b)
    location = location_similarity(a, b)
    score = WEIGHTS["name"] * name + WEIGHTS["address"] * address + WEIGHTS["location"] * location
    if a.legal and b.legal and a.legal != b.legal and frozenset({a.legal, b.legal}) not in COMPATIBLE_LEGAL:
        score -= 0.05

    def result(band: str, reason: str, value: float = score) -> PairResult:
        return PairResult(a.rid, b.rid, band, round(value, 4), reason,
                          round(name, 4), round(address, 4), round(location, 4))

    if a.cif and b.cif and a.cif != b.cif:
        return result("NO", "different valid tax IDs")
    same_tax = bool(a.cif) and a.cif == b.cif
    if same_tax or tax_typo_apart(a, b):
        label = "same tax ID" if same_tax else "tax ID one typo apart"
        if name < TAX_NAME_THRESHOLD:
            return result("REVIEW", f"{label}, different name")
        if a.province and b.province and a.province != b.province:
            # A move or a tax ID copied onto a namesake: the data cannot tell them apart.
            return result("REVIEW", f"{label}, different province")
        return result("AUTO", label, 1.0)
    if score >= AUTO_THRESHOLD:
        return result("AUTO", "name + address")
    if score >= REVIEW_THRESHOLD:
        return result("REVIEW", "name + address, grey zone")
    if name >= SAME_NAME_THRESHOLD and a.province and b.province and a.province != b.province:
        return result("REVIEW", "same name, another province")
    return result("NO", "low similarity")


def cluster(prepared: list[Prepared], merges: list[PairResult]) -> tuple[dict[str, str], int]:
    """Union-find over the merge pairs, refusing to join two different valid tax IDs."""
    parent = {p.rid: p.rid for p in prepared}
    cifs = {p.rid: ({p.cif} if p.cif else set()) for p in prepared}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    refused = 0
    for pair in sorted(merges, key=lambda r: -r.score):
        ra, rb = find(pair.a), find(pair.b)
        if ra == rb:
            continue
        if cifs[ra] and cifs[rb] and cifs[ra] != cifs[rb]:
            refused += 1
            continue
        parent[rb] = ra
        cifs[ra] |= cifs[rb]

    roots = sorted({find(p.rid) for p in prepared})
    names = {root: f"C{i + 1:05d}" for i, root in enumerate(roots)}
    return {p.rid: names[find(p.rid)] for p in prepared}, refused


def read_records(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def match(records_path: Path, out_dir: Path) -> dict:
    rows = read_records(records_path)
    prepared = [prepare(r) for r in rows]
    index_pairs, block_stats = candidate_pairs(prepared)
    results = [score_pair(prepared[i], prepared[j]) for i, j in sorted(index_pairs)]
    clusters, refused = cluster(prepared, [r for r in results if r.band == "AUTO"])

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(results[0])) if results else ["a", "b"])
        writer.writeheader()
        writer.writerows(asdict(r) for r in results)
    with (out_dir / "clusters.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["RECORD_ID", "CLUSTER_ID"])
        writer.writerows(sorted(clusters.items()))
    _write_review(out_dir / "review.csv", rows, [r for r in results if r.band == "REVIEW"])

    bands = defaultdict(int)
    for r in results:
        bands[r.band] += 1
    stats = {"records": len(rows), **block_stats, "candidate_pairs": len(results),
             "bands": dict(bands), "clusters": len(set(clusters.values())),
             "merges_refused_by_tax_id": refused}
    (out_dir / "match_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def _write_review(path: Path, rows: list[dict], review: list[PairResult]) -> None:
    """Side-by-side view of the grey zone: the input for the LLM and for people."""
    by_id = {r["RECORD_ID"]: r for r in rows}
    shown = ("NAME1", "NAME2", "STRAS", "PSTLZ", "ORT01", "STCD1", "STCEG")
    fields = ["A", "B", "SCORE", "REASON"] + [f"{side}_{f}" for f in shown for side in ("A", "B")]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in sorted(review, key=lambda x: -x.score):
            row = {"A": r.a, "B": r.b, "SCORE": r.score, "REASON": r.reason}
            for f in shown:
                row[f"A_{f}"] = by_id[r.a][f]
                row[f"B_{f}"] = by_id[r.b][f]
            writer.writerow(row)
