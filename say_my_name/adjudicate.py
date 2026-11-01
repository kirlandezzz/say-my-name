"""Phase 3: an LLM decides the grey zone (the REVIEW pairs).

The rules merge what is safe; only the pairs they could not decide reach the
model. Every answer is stored on disk, so a re-run costs nothing and the
report can be rebuilt without calling the API again.

Live runs need the `anthropic` SDK (``pip install -e ".[llm]"``) and
credentials (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile). The tests
use a fake client and need neither.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import taxid
from .evaluate import _read_csv, _read_pairs, bcubed, pairwise
from .matcher import PairResult, cluster, prepare, read_records

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
# USD per million tokens (input, output), Claude API price table as of 2026-10-06.
# Cache writes cost 1.25x the input price and cache reads 0.1x.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}
MAX_TOKENS = 4096  # both models think by default, and thinking counts toward max_tokens

DECISIONS = ("same_company", "different_companies", "needs_external_check")
PATTERNS = ("formatting_or_typo", "abbreviation", "renamed", "moved", "sibling_company",
            "namesake", "copied_tax_id", "unclear")
FIELDS = ("SYSTEM", "TABLE", "NAME1", "NAME2", "STRAS", "PSTLZ", "ORT01", "REGIO", "STCD1", "STCEG")

SYSTEM_PROMPT = """\
You review possible duplicate business partners before an SAP S/4HANA migration.

Context
- A group is merging two legacy SAP ECC systems, ERP_A and ERP_B, into one S/4HANA system. Every customer (table KNA1) and vendor (table LFA1) becomes a Business Partner. The same company can appear several times: in both systems, as customer and as vendor, or twice in one table.
- All records are Spanish legal entities (S.L., S.A., S.L.U., cooperatives). ERP_B is the older system: it stores text in upper case without accents and more often lacks a tax ID.
- Fields: NAME1/NAME2 (company name; a long name continues in NAME2), STRAS (street and number), PSTLZ (postcode), ORT01 (city), REGIO (province code), STCD1 (tax ID, the CIF), STCEG (EU VAT number: ES + CIF).
- A rules engine has already merged the clear duplicates and discarded the clear non-duplicates. You only see the pairs it could not decide, together with the reason it gives.

Your job
Decide whether the two records are the same legal entity, using only what the records show:
- same_company: you would merge them into one Business Partner.
- different_companies: they are distinct legal entities.
- needs_external_check: the records cannot settle it; a person must check an outside source such as the Registro Mercantil.

A wrong merge is worse than a missed duplicate. Merging two legal entities sends payments and tax data to the wrong company, while a missed duplicate only leaves two records. When the evidence is balanced, answer needs_external_check instead of guessing.

How to read the evidence
- These differences do not change identity: upper or lower case, accents, punctuation, legal-form spelling (S.L., SL, Sociedad Limitada), a legal form missing in one record, abbreviations (Dist., Cial., Hnos.), word order, a name split differently across NAME1 and NAME2, one-letter typos, street-type abbreviations (C/, Avda., Pol. Ind.), city aliases (S/C de Tenerife, La Laguna), a postcode that lost its leading zero.
- These differences do change identity: a different geographic qualifier (del Norte vs del Sur), a different activity word with the same brand (Talvora Logística vs Talvora Envases), a holding versus an operating company (Grupo Talvora S.A. vs Talvora Logística S.L.U.), a different type of legal form (S.A. vs S.L.; S.L. and S.L.U. can still be one company). Companies of one group often share the head-office address, so a shared address does not make them one company.
- Tax ID: one CIF identifies one legal entity, and it does not change when a company moves or is renamed. tax_id_status says whether each CIF passes the check digit. A CIF that fails the check digit contains a typo; if it is one character away from the other record's valid CIF, read it as the same CIF.
- A shared valid CIF is strong but not conclusive: copying the CIF of a related company onto the wrong record is a known data-entry error. If the names show two different companies of one group, do not merge on the CIF alone.
- The same valid CIF and the same address under a completely different brand name usually means the company was renamed.
- The same name in another province, with no CIF that confirms it, can be a company that moved or an unrelated namesake. If nothing else in the records settles it, answer needs_external_check.

Also report
- confidence: high, medium or low.
- pattern: the situation that best describes the pair.
- evidence: up to four short facts from the records that drove the decision, quoting field values.
- explanation: one sentence for the person who reviews your decision.
"""

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "pattern": {"type": "string", "enum": list(PATTERNS)},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["decision", "confidence", "pattern", "evidence", "explanation"],
    "additionalProperties": False,
}


@dataclass
class Decision:
    pair_id: str
    a: str
    b: str
    reason: str
    decision: str  # one of DECISIONS, or "failed" (refusal, cut-off, unreadable answer, API error)
    confidence: str = ""
    pattern: str = ""
    evidence: list[str] = field(default_factory=list)
    explanation: str = ""
    model: str = ""  # the model that served the answer (differs from the request after a fallback)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    prompt_hash: str = ""


def tax_id_status(record: dict) -> dict[str, str]:
    status = {}
    for f in ("STCD1", "STCEG"):
        value = taxid.normalize(record.get(f))
        if value:
            status[f] = "passes check digit" if taxid.is_valid(value) else "fails check digit"
    return status or {"STCD1": "missing"}


def pair_prompt(pair: PairResult, a: dict, b: dict) -> str:
    payload = {
        "rules_engine_reason": pair.reason,
        "record_a": {**{f: a.get(f, "") for f in FIELDS}, "tax_id_status": tax_id_status(a)},
        "record_b": {**{f: b.get(f, "") for f in FIELDS}, "tax_id_status": tax_id_status(b)},
    }
    return "Are these two records the same legal entity?\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def build_request(model_id: str, effort: str, user_text: str) -> dict:
    request = {
        "model": model_id,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_text}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
    }
    if model_id == MODELS["sonnet"]:
        # Server-side retry on another model if a safety classifier declines.
        # Claude Haiku 5.5 has no server-side fallback, so it gets no such parameter.
        request["betas"] = ["server-side-fallback-2026-07-01"]
        request["fallbacks"] = "default"
    return request


def prompt_hash(model_id: str, effort: str, user_text: str) -> str:
    material = json.dumps([SYSTEM_PROMPT, DECISION_SCHEMA, model_id, effort, MAX_TOKENS, user_text], sort_keys=True)
    return hashlib.sha1(material.encode()).hexdigest()[:16]


def cost_usd(model_id: str, usage) -> float:
    price_in, price_out = PRICES[model_id]
    return (usage.input_tokens * price_in
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * price_in * 1.25
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) * price_in * 0.1
            + usage.output_tokens * price_out) / 1_000_000


def parse_response(response, base: Decision, requested_model: str) -> Decision:
    """Turn an API response into a Decision. Anything unusable becomes "failed" and goes to a person."""
    usage = response.usage
    base.model = response.model
    base.stop_reason = response.stop_reason or ""
    base.input_tokens = usage.input_tokens
    base.output_tokens = usage.output_tokens
    base.cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
    base.cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
    # After a fallback the serving model may have no entry in PRICES: price it as the requested one.
    base.cost_usd = cost_usd(base.model if base.model in PRICES else requested_model, usage)
    if response.stop_reason == "refusal":
        base.decision, base.explanation = "failed", "the model declined the request"
        return base
    if response.stop_reason == "max_tokens":
        base.decision, base.explanation = "failed", "the answer was cut off at max_tokens"
        return base
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        base.decision, base.explanation = "failed", "the answer was not valid JSON"
        return base
    if data.get("decision") not in DECISIONS:
        base.decision, base.explanation = "failed", f"unknown decision {data.get('decision')!r}"
        return base
    base.decision = data["decision"]
    base.confidence = data.get("confidence", "")
    base.pattern = data.get("pattern", "")
    base.evidence = list(data.get("evidence", []))[:4]
    base.explanation = data.get("explanation", "")
    return base


def decide(client, model_id: str, effort: str, pair: PairResult, a: dict, b: dict,
           api_errors: tuple = ()) -> Decision:
    user_text = pair_prompt(pair, a, b)
    base = Decision(pair_id=f"{pair.a}|{pair.b}", a=pair.a, b=pair.b, reason=pair.reason,
                    decision="failed", prompt_hash=prompt_hash(model_id, effort, user_text))
    request = build_request(model_id, effort, user_text)
    api = client.beta.messages if "betas" in request else client.messages
    started = time.monotonic()
    try:
        response = api.create(**request)
    except api_errors as exc:  # the SDK has already retried 408/409/429/5xx and connection errors
        base.explanation = f"API error: {type(exc).__name__}"
        base.seconds = time.monotonic() - started
        return base
    base.seconds = round(time.monotonic() - started, 3)
    return parse_response(response, base, model_id)


def make_client():
    import anthropic  # imported here so the rest of the project needs only the standard library

    return anthropic.Anthropic(), (anthropic.APIConnectionError, anthropic.APIStatusError)


def _sample(pairs: list[PairResult], limit: int | None) -> list[PairResult]:
    if not limit:
        return pairs
    return sorted(pairs, key=lambda p: hashlib.sha1(f"{p.a}|{p.b}".encode()).hexdigest())[:limit]


def _load(path: Path) -> dict[str, Decision]:
    if not path.exists():
        return {}
    decisions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = Decision(**json.loads(line))
            decisions[d.pair_id] = d
    return decisions


def run(name: str, model: str = "haiku", effort: str = "medium", limit: int | None = None,
        workers: int = 8, dry_run: bool = False, client=None, api_errors: tuple = (),
        root: Path = Path(".")) -> dict:
    model_id = MODELS[model]
    run_dir = root / "out" / name
    records = {r["RECORD_ID"]: r for r in read_records(root / "data" / name / "records.csv")}
    review = _sample([p for p in _read_pairs(run_dir / "pairs.csv") if p.band == "REVIEW"], limit)
    out_dir = run_dir / f"llm-{model}-{effort}"
    store = out_dir / "decisions.jsonl"

    if dry_run:
        return _dry_run(model_id, effort, review, records)

    known = {k: d for k, d in _load(store).items() if d.decision != "failed"}
    todo = [p for p in review
            if (known.get(f"{p.a}|{p.b}") is None
                or known[f"{p.a}|{p.b}"].prompt_hash != prompt_hash(model_id, effort, pair_prompt(p, records[p.a], records[p.b])))]
    if todo:
        if client is None:
            client, api_errors = make_client()
        out_dir.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool, store.open("a", encoding="utf-8") as fh:
            futures = [pool.submit(decide, client, model_id, effort, p, records[p.a], records[p.b], api_errors)
                       for p in todo]
            for future in as_completed(futures):
                d = future.result()
                with lock:
                    fh.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")
                    fh.flush()
                    known[d.pair_id] = d
                    done += 1
                    if done % 25 == 0 or done == len(todo):
                        print(f"  {done}/{len(todo)} pairs decided", flush=True)

    decisions = [known[f"{p.a}|{p.b}"] for p in review if f"{p.a}|{p.b}" in known]
    truth_path = root / "data" / name / "truth.csv"
    metrics = evaluate_llm(name, model_id, effort, decisions, review, records, truth_path, run_dir,
                           out_dir, sample=bool(limit))
    return metrics


def _dry_run(model_id: str, effort: str, review: list[PairResult], records: dict) -> dict:
    """Show one prompt and a rough cost estimate without calling the API."""
    texts = [pair_prompt(p, records[p.a], records[p.b]) for p in review]
    approx = lambda s: len(s) / 3.5  # rough characters-per-token for this mixed Spanish/JSON text
    system_tokens = approx(SYSTEM_PROMPT) + approx(json.dumps(DECISION_SCHEMA))
    user_tokens = sum(approx(t) for t in texts)
    assumed_output = 600  # answer plus thinking at low/medium effort; measure it on a sample first
    estimates = {}
    for mid, (p_in, p_out) in PRICES.items():
        total = (system_tokens * p_in * 1.25 + system_tokens * p_in * 0.1 * max(len(texts) - 1, 0)
                 + user_tokens * p_in + assumed_output * len(texts) * p_out) / 1_000_000
        estimates[mid] = round(total, 2)
    if texts:
        print(f"System prompt ≈ {system_tokens:.0f} tokens (cached). First of {len(texts)} pair prompts:\n")
        print(texts[0])
    print(f"\nRough cost for {len(texts)} pairs, assuming {assumed_output} output tokens each: "
          + ", ".join(f"{m} ≈ ${c}" for m, c in estimates.items()))
    return {"pairs": len(texts), "estimated_usd": estimates}


def evaluate_llm(name: str, model_id: str, effort: str, decisions: list[Decision], review: list[PairResult],
                 records: dict, truth_path: Path, run_dir: Path, out_dir: Path, sample: bool) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    truth = {t["RECORD_ID"]: t["ENTITY_ID"] for t in _read_csv(truth_path)} if truth_path.exists() else {}
    by_pair = {d.pair_id: d for d in decisions}
    same = lambda p: truth.get(p.a) is not None and truth[p.a] == truth[p.b]

    confusion = Counter((("same" if same(p) else "different"), by_pair[f"{p.a}|{p.b}"].decision)
                        for p in review if f"{p.a}|{p.b}" in by_pair) if truth else Counter()
    by_reason = Counter((p.reason, ("same" if same(p) else "different"), by_pair[f"{p.a}|{p.b}"].decision)
                        for p in review if f"{p.a}|{p.b}" in by_pair) if truth else Counter()
    merged = confusion[("same", "same_company")] + confusion[("different", "same_company")]
    true_same = sum(v for (t, _), v in confusion.items() if t == "same")
    handed_off = sum(v for (t, d), v in confusion.items() if d in ("needs_external_check", "failed"))

    cost = sum(d.cost_usd for d in decisions)
    seconds = sorted(d.seconds for d in decisions if d.seconds)
    n_records = len(records)
    metrics: dict = {
        "run": name, "model": model_id, "effort": effort, "sample": sample,
        "review_pairs": len(review), "decided": len(decisions),
        "decisions": dict(Counter(d.decision for d in decisions)),
        "served_by": dict(Counter(d.model for d in decisions)),
        "confusion": {f"{t}->{d}": v for (t, d), v in sorted(confusion.items())},
        "llm_merge_precision": confusion[("same", "same_company")] / merged if merged else None,
        "llm_merge_recall": confusion[("same", "same_company")] / true_same if true_same else None,
        "wrong_merges": confusion[("different", "same_company")],
        "handed_to_people": handed_off,
        "cost_usd": round(cost, 4),
        "cost_per_review_pair_usd": round(cost / len(decisions), 6) if decisions else None,
        "cost_per_1000_records_usd": (round(cost / len(decisions) * len(review) / n_records * 1000, 4)
                                      if decisions and n_records else None),
        "tokens": {k: sum(getattr(d, k) for d in decisions) for k in
                   ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")},
        "latency_s": ({"p50": round(statistics.median(seconds), 2),
                       "p95": round(statistics.quantiles(seconds, n=20)[-1], 2) if len(seconds) >= 20 else None}
                      if seconds else None),
        "by_reason": {f"{r} | {t} -> {d}": v for (r, t, d), v in sorted(by_reason.items())},
    }

    if truth and not sample and len(decisions) == len(review):
        prepared = [prepare(r) for r in records.values()]
        all_pairs = _read_pairs(run_dir / "pairs.csv")
        auto = [p for p in all_pairs if p.band == "AUTO"]
        llm_same = [p for p in review if by_pair[f"{p.a}|{p.b}"].decision == "same_company"]
        people = [p for p in review if by_pair[f"{p.a}|{p.b}"].decision in ("needs_external_check", "failed") and same(p)]
        perfect = [p for p in review if same(p)]
        scenarios = {}
        for label, merges in (("rules only", auto),
                              ("rules + LLM (hand-offs left unmerged)", auto + llm_same),
                              ("rules + LLM + people decide the hand-offs perfectly", auto + llm_same + people),
                              ("ceiling: every REVIEW pair decided perfectly", auto + perfect)):
            clusters, _ = cluster(prepared, merges)
            scenarios[label] = {"pairwise": pairwise(clusters, truth), "bcubed": bcubed(clusters, truth)}
        metrics["scenarios"] = scenarios

    wrong = [d for p in review if (d := by_pair.get(f"{p.a}|{p.b}")) and truth and not same(p)
             and d.decision == "same_company"]
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(_report(metrics, wrong[:8], records), encoding="utf-8")
    return metrics


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def _report(m: dict, wrong: list[Decision], records: dict) -> str:
    lines = [f"# Say my name: LLM on the grey zone ({m['model']}, effort {m['effort']})", ""]
    if m["sample"]:
        lines += [f"**Sample run:** {m['decided']} of the REVIEW pairs. Pipeline scores need a full run.", ""]
    lines += [
        f"- Pairs decided: {m['decided']} · decisions: "
        + ", ".join(f"{k} {v}" for k, v in sorted(m["decisions"].items())),
        f"- Served by: {', '.join(f'{k} {v}' for k, v in m['served_by'].items())}",
        f"- Precision of the LLM's merges: {_pct(m['llm_merge_precision'])} · wrong merges: {m['wrong_merges']}",
        f"- Share of true duplicates the LLM merged: {_pct(m['llm_merge_recall'])}",
        f"- Handed to people: {m['handed_to_people']} of {m['decided']}",
        f"- Cost: ${m['cost_usd']} · per REVIEW pair ${m['cost_per_review_pair_usd']}"
        f" · per 1,000 records ${m['cost_per_1000_records_usd']}",
        f"- Latency per pair: {m['latency_s']}",
        f"- Tokens: {m['tokens']}",
        "",
    ]
    if "scenarios" in m:
        lines += ["## Pipeline scores", "", "| Scenario | Pair precision | Pair recall | Pair F1 | B³ F1 |",
                  "|---|---:|---:|---:|---:|"]
        for label, s in m["scenarios"].items():
            pw, b3 = s["pairwise"], s["bcubed"]
            lines.append(f"| {label} | {_pct(pw['precision'])} | {_pct(pw['recall'])} | {_pct(pw['f1'])} | {_pct(b3['f1'])} |")
        lines.append("")
    if m["confusion"]:
        lines += ["## Truth vs decision", "", "| Truth → decision | Pairs |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in m["confusion"].items()]
        lines += ["", "## By rules-engine reason", "", "| Reason · truth → decision | Pairs |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in m["by_reason"].items()]
        lines.append("")
    lines += ["## Wrong merges", ""]
    if not wrong:
        lines.append("None.")
    for d in wrong:
        a, b = records[d.a], records[d.b]
        lines += [f"- **{d.confidence}**, {d.pattern} ({d.reason}): {d.explanation}",
                  f"  - A: {a['NAME1']} {a['NAME2']} · {a['STRAS']} · {a['PSTLZ']} {a['ORT01']} · {a['STCD1'] or '—'}",
                  f"  - B: {b['NAME1']} {b['NAME2']} · {b['STRAS']} · {b['PSTLZ']} {b['ORT01']} · {b['STCD1'] or '—'}"]
    return "\n".join(lines) + "\n"
