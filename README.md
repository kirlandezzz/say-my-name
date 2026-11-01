# Say my name

**Business partner deduplication for SAP S/4HANA migrations: rules first, an LLM only for the grey zone.**

When two legacy ERP systems are merged into S/4HANA, every customer (`KNA1`) and vendor (`LFA1`) has to become one Business Partner. The same company shows up several times, as `DIST. TALVORA SL` in one system and `Distribuciones Talvora, S.L.` with a mistyped tax ID in the other. Its sister company, `Distribuciones Talvora del Sur, S.L.`, sits at the same address and must **not** be merged.

This project finds those duplicates and measures how well it does it.

## Status: v0.2, rule-based matcher

| | |
|---|---|
| Synthetic dataset | `KNA1`/`LFA1` records from two systems with ground truth (dev: 5,000 companies, test: 1,000) |
| Matcher | normalise → block → score pairs → cluster, in plain Python (no dependencies) |
| Evaluation | pairwise and B³ precision/recall/F1, miss rate per noise type, wrong merges per cause |

Results on the held-out seed (2026). Rules and thresholds were tuned on seed 7 only, and every change is logged with its hypothesis and cost in [`DECISIONES.md`](DECISIONES.md).

| Scenario | Pair precision | Pair recall | Pair F1 |
|---|---:|---:|---:|
| Rules only (AUTO merges) | 99.9 % | 92.0 % | 95.8 % |
| Accept every grey-zone pair blindly | | | 97.4 % |
| Perfect grey-zone decisions (ceiling for the LLM step) | | | 99.4 % |

Phase 2 cut wrong merges on the test seed from 16 to 1 and raised recall from 90.0 % to 92.0 %.

The grey zone (REVIEW band) holds 162 of 8,343 candidate pairs, of which 90 are the same company. Each pair carries a reason, and the reasons need different handling. Some can be argued from the record ("Norte" vs "Sur" means another company). Others cannot be settled from the data at all, such as the same tax ID in another province (a move, or an ID copied onto a namesake). For those, the right answer is "check the company register". Teaching the LLM step to say that instead of guessing is the core of phase 3.

## Quick start

```bash
make test   # unit tests
make dev    # generate seed 7, match, evaluate -> out/dev/report.md
make eval   # same for the held-out seed 2026 -> out/test/report.md
```

Python 3.11 or newer, standard library only. Outputs per run in `out/<name>/`:

- `pairs.csv`: every candidate pair with its band (AUTO / REVIEW / NO), score and reason.
- `clusters.csv`: proposed Business Partner groups.
- `review.csv`: grey-zone pairs side by side, the input for the LLM and for human review.
- `report.md` and `metrics.json`: the evaluation.

## The dataset

`say_my_name/generator.py` simulates a group merging two ECC systems. `ERP_B` is the older system: upper case, no accents, more missing tax IDs. Fields follow SAP: `NAME1`/`NAME2` (35 characters), `SORTL`, `STRAS`, `PSTLZ`, `ORT01`, `REGIO`, `STCD1`, `STCEG`.

Duplicates are created with recorded noise operations: typos, common and rare abbreviations (`Com.`, `Cial.`), legal-form variants (`S.L.`, `SL`, `Sociedad Limitada`), names split across `NAME1`/`NAME2`, street and city variants (`C/`, `S/C de Tenerife`), lost leading zeros in postcodes, missing, reformatted or mistyped tax IDs, companies that moved, and companies that were renamed.

Hard negatives are generated on purpose:

- **Sibling companies**: same brand, different legal entity, often the same HQ address.
- **Namesakes**: same name, unrelated company in another city.
- **Copied tax IDs**: a record carries the tax ID of a related company, a classic data-entry error.

All data is synthetic: invented brand names, generic street names, and tax IDs with a valid check digit. Only legal entities appear, with no natural persons, phones, e-mails or bank details.

## How the matcher works

1. **Normalise**:
   - accents, punctuation and legal form;
   - abbreviations, from a table of common ones plus any token that is an unambiguous subsequence of one activity word (`CIAL` → `COMERCIAL`);
   - street type, house number, city aliases and postcode;
   - tax ID, validated with the CIF check digit.
2. **Block**: compare only records that share a valid tax ID, a distinctive name prefix or suffix within the province, a whole brand token anywhere, or postcode plus house number.
3. **Score**: name similarity (Jaro-Winkler on sorted tokens plus a typo-tolerant token Dice), address and location. Then these rules apply:
   - Two different valid tax IDs never match.
   - The same tax ID counts only with a similar name in the same province; otherwise the pair goes to REVIEW.
   - A valid and an invalid tax ID one typo apart count as the same tax ID.
   - The same name in another province with no tax ID to confirm it goes to REVIEW.
4. **Cluster**: union-find over AUTO pairs, refusing any merge that would put two different valid tax IDs in one Business Partner.

## Honest caveats

- The common-abbreviation table and the city aliases are reference data shared with the generator. That is realistic, since real projects keep such tables, but it flatters those noise types. Rare abbreviations are not in the table and are caught by the subsequence rule instead. That rule wrongly expanded one invented brand in the dev data (logged in `DECISIONES.md`).
- The miss-rate table in the report is correlational: a pair usually carries several noise operations.
- Synthetic data is cleaner than real data in some ways and harsher in others. The point is a controlled, repeatable benchmark.

## Roadmap

- **Phase 2** (done): rules that cut wrong merges and route undecidable cases to review. See `DECISIONES.md`.
- **Phase 3** (code ready, live runs pending): an LLM decides the REVIEW pairs. It answers `same_company`, `different_companies` or `needs_external_check`, in a JSON schema with confidence, pattern and cited evidence; anything it cannot settle goes to a person. Claude Haiku 5.5 and Claude Sonnet 5.5 are compared on wrong merges, hand-offs, end-to-end F1, cost per 1,000 records and latency. Run it with `pip install -e ".[llm]"`, an API key, and `make llm-sample` / `make llm-dev` / `make llm-test` (see `PLAN.md`). Design decisions D5–D10 are in `DECISIONES.md`.
- **Phase 4**: golden record proposal (survivorship rules, customer and vendor roles on one BP), a review screen for people, and a legacy-key → BP mapping file for the migration.
