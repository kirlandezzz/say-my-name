"""Scores the matcher against the ground truth and writes a Markdown report."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from .matcher import PairResult, cluster, prepare, read_records


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


def pairwise(pred: dict[str, str], truth: dict[str, str]) -> dict:
    joint = Counter((pred[r], truth[r]) for r in truth)
    tp = sum(_pairs(n) for n in joint.values())
    predicted = sum(_pairs(n) for n in Counter(pred[r] for r in truth).values())
    actual = sum(_pairs(n) for n in Counter(truth.values()).values())
    p = tp / predicted if predicted else 1.0
    r = tp / actual if actual else 1.0
    return {"precision": p, "recall": r, "f1": _f1(p, r), "true_pairs": actual,
            "predicted_pairs": predicted, "correct_pairs": tp}


def bcubed(pred: dict[str, str], truth: dict[str, str]) -> dict:
    joint = Counter((pred[r], truth[r]) for r in truth)
    pred_size = Counter(pred[r] for r in truth)
    truth_size = Counter(truth.values())
    p = sum(joint[(pred[r], truth[r])] / pred_size[pred[r]] for r in truth) / len(truth)
    r = sum(joint[(pred[r], truth[r])] / truth_size[truth[r]] for r in truth) / len(truth)
    return {"precision": p, "recall": r, "f1": _f1(p, r)}


def _read_pairs(path: Path) -> list[PairResult]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [PairResult(r["a"], r["b"], r["band"], float(r["score"]), r["reason"],
                           float(r["name_sim"]), float(r["address_sim"]), float(r["location_sim"]))
                for r in csv.DictReader(fh)]


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _relation(a: dict, b: dict) -> str:
    """Why two records of different companies could be confused."""
    if "tax_copy_error" in a["OPS"] or "tax_copy_error" in b["OPS"]:
        if a["ENTITY_ID"] in (b["RELATED_ID"],) or b["ENTITY_ID"] in (a["RELATED_ID"],):
            return "tax ID copied from a related company"
    if a["GROUP_ID"] and a["GROUP_ID"] == b["GROUP_ID"]:
        return "sibling company (same group)"
    if a["RELATED_ID"] == b["ENTITY_ID"] or b["RELATED_ID"] == a["ENTITY_ID"]:
        return "namesake in another city"
    return "unrelated"


def evaluate(records_path: Path, truth_path: Path, out_dir: Path) -> dict:
    rows = read_records(records_path)
    by_id = {r["RECORD_ID"]: r for r in rows}
    truth_rows = {t["RECORD_ID"]: t for t in _read_csv(truth_path)}
    truth = {rid: t["ENTITY_ID"] for rid, t in truth_rows.items()}
    prepared = [prepare(r) for r in rows]
    pairs = _read_pairs(out_dir / "pairs.csv")
    pair_index = {frozenset((p.a, p.b)): p for p in pairs}

    auto = [p for p in pairs if p.band == "AUTO"]
    review = [p for p in pairs if p.band == "REVIEW"]
    review_true = [p for p in review if truth[p.a] == truth[p.b]]

    scenarios = {}
    for name, merges in (
        ("baseline: AUTO only", auto),
        ("accept every REVIEW pair blindly", auto + review),
        ("perfect REVIEW decisions (ceiling for phase 3)", auto + review_true),
    ):
        clusters, refused = cluster(prepared, merges)
        scenarios[name] = {"pairwise": pairwise(clusters, truth), "bcubed": bcubed(clusters, truth),
                           "refused_by_tax_id": refused, "_clusters": clusters}
    baseline = scenarios["baseline: AUTO only"]["_clusters"]

    # Missed duplicates (false negatives), by stage and by noise operation.
    members: dict[str, list[str]] = defaultdict(list)
    for rid, eid in truth.items():
        members[eid].append(rid)
    fn_stage: Counter = Counter()
    op_total: Counter = Counter()
    op_missed: Counter = Counter()
    fn_examples = []
    for rids in members.values():
        for a, b in combinations(sorted(rids), 2):
            ops = (set(truth_rows[a]["OPS"].split("|")) | set(truth_rows[b]["OPS"].split("|"))) - {"", "sys_b_style"}
            for op in ops or {"(clean copy)"}:
                op_total[op] += 1
            if baseline[a] == baseline[b]:
                continue
            pair = pair_index.get(frozenset((a, b)))
            stage = "never compared (blocking)" if pair is None else f"scored {pair.band}"
            fn_stage[stage] += 1
            for op in ops or {"(clean copy)"}:
                op_missed[op] += 1
            if len(fn_examples) < 8 and pair is not None:
                fn_examples.append((a, b, pair, sorted(ops)))

    # Wrong merges (false positives), by why the companies looked alike.
    fp_relation: Counter = Counter()
    fp_examples = []
    clusters_members: dict[str, list[str]] = defaultdict(list)
    for rid, cid in baseline.items():
        clusters_members[cid].append(rid)
    for rids in clusters_members.values():
        for a, b in combinations(sorted(rids), 2):
            if truth[a] != truth[b]:
                relation = _relation(truth_rows[a], truth_rows[b])
                fp_relation[relation] += 1
                pair = pair_index.get(frozenset((a, b)))
                if len(fp_examples) < 8 and pair is not None:
                    fp_examples.append((a, b, pair, relation))

    review_relation = Counter(
        "same company" if truth[p.a] == truth[p.b] else _relation(truth_rows[p.a], truth_rows[p.b])
        for p in review)

    metrics = {
        "records": len(rows), "companies": len(members),
        "candidate_pairs": len(pairs),
        "bands": dict(Counter(p.band for p in pairs)),
        "review_pairs": len(review), "review_true_matches": len(review_true),
        "scenarios": {k: {m: v for m, v in s.items() if m != "_clusters"} for k, s in scenarios.items()},
        "missed_by_stage": dict(fn_stage),
        "miss_rate_by_op": {op: {"pairs": op_total[op], "missed": op_missed[op]} for op in sorted(op_total)},
        "wrong_merges_by_relation": dict(fp_relation),
        "review_by_relation": dict(review_relation),
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(
        _report(metrics, by_id, fn_examples, fp_examples), encoding="utf-8")
    return metrics


def _pct(x: float) -> str:
    return f"{100 * x:.1f} %"


def _show(rec: dict) -> str:
    name = " ".join(x for x in (rec["NAME1"], rec["NAME2"]) if x)
    tax = rec["STCD1"] or rec["STCEG"] or "—"
    return f"{name} · {rec['STRAS']} · {rec['PSTLZ'] or '—'} {rec['ORT01']} · {tax}"


def _report(m: dict, by_id: dict, fn_examples, fp_examples) -> str:
    lines = [
        "# Say my name: baseline report",
        "",
        f"{m['records']} records from {m['companies']} companies · {m['candidate_pairs']} candidate pairs "
        f"· bands: {', '.join(f'{k} {v}' for k, v in sorted(m['bands'].items()))}",
        "",
        "## Scores",
        "",
        "| Scenario | Pair precision | Pair recall | Pair F1 | B³ F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, s in m["scenarios"].items():
        pw, b3 = s["pairwise"], s["bcubed"]
        lines.append(f"| {name} | {_pct(pw['precision'])} | {_pct(pw['recall'])} | {_pct(pw['f1'])} | {_pct(b3['f1'])} |")
    lines += [
        "",
        f"The REVIEW band holds {m['review_pairs']} pairs, of which {m['review_true_matches']} are the same company.",
        "",
        "| What the REVIEW pairs really are | Pairs |",
        "|---|---:|",
        *(f"| {k} | {v} |" for k, v in sorted(m["review_by_relation"].items(), key=lambda kv: -kv[1])),
        "",
        "## Missed duplicates",
        "",
        "| Stage where the pair was lost | Pairs |",
        "|---|---:|",
        *(f"| {k} | {v} |" for k, v in sorted(m["missed_by_stage"].items(), key=lambda kv: -kv[1])),
        "",
        "| Noise in the pair | True pairs | Missed | Miss rate |",
        "|---|---:|---:|---:|",
    ]
    rates = sorted(m["miss_rate_by_op"].items(), key=lambda kv: -kv[1]["missed"] / kv[1]["pairs"])
    for op, v in rates:
        lines.append(f"| {op} | {v['pairs']} | {v['missed']} | {_pct(v['missed'] / v['pairs'])} |")
    lines += ["", "## Wrong merges", "", "| Why they looked alike | Pairs |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(m["wrong_merges_by_relation"].items(), key=lambda kv: -kv[1])] or ["| none | 0 |"]

    def examples(title: str, items, extra) -> list[str]:
        out = ["", f"## {title}", ""]
        for a, b, pair, info in items:
            out += [f"- **{pair.band} {pair.score:.2f}** ({pair.reason}; {extra(info)})",
                    f"  - A: {_show(by_id[a])}", f"  - B: {_show(by_id[b])}"]
        return out if items else out + ["None."]

    lines += examples("Examples of missed duplicates", fn_examples, lambda ops: "noise: " + (", ".join(ops) or "none"))
    lines += examples("Examples of wrong merges", fp_examples, lambda rel: rel)
    return "\n".join(lines) + "\n"
