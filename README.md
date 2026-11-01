# Say my name

**Business partner deduplication for SAP S/4HANA migrations: rules first, an LLM only for the grey zone.**

When two legacy ERP systems are merged into S/4HANA, every customer (`KNA1`) and vendor (`LFA1`) has to become one Business Partner. The same company shows up several times, as `DIST. TALVORA SL` in one system and `Distribuciones Talvora, S.L.` with a mistyped tax ID in the other. Its sister company, `Distribuciones Talvora del Sur, S.L.`, sits at the same address and must **not** be merged.

This project finds those duplicates and measures how well it does it.

## Status: v0.1, rule-based baseline

| | |
|---|---|
| Synthetic dataset | ~2,000 `KNA1`/`LFA1` records from two systems, with ground truth |
| Matcher | normalise → block → score pairs → cluster, in plain Python (no dependencies) |
| Evaluation | pairwise and B³ precision/recall/F1, miss rate per noise type, wrong merges per cause |

Results on the held-out seed (2026). Thresholds were tuned on seed 7 only.

| Scenario | Pair precision | Pair recall | Pair F1 |
|---|---:|---:|---:|
| Baseline (AUTO merges only) | 98.4 % | 87.0 % | 92.3 % |
| Accept every grey-zone pair blindly | 94.8 % | 96.1 % | 95.4 % |
| Perfect grey-zone decisions (ceiling for the LLM step) | 98.5 % | 96.1 % | 97.2 % |

The grey zone (REVIEW band) holds 195 of 8,899 candidate pairs. 123 of them are the same company. The rest are sibling companies, namesakes and tax IDs copied from a related company. Deciding these well is the job of the LLM step (phase 3).

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

1. **Normalise**: accents, punctuation, legal form, common abbreviations, street type, house number, city aliases, postcode, and tax ID (validated with the CIF check digit).
2. **Block**: compare only records that share a valid tax ID, a distinctive name prefix or suffix within the province, or postcode plus house number.
3. **Score**: name similarity (Jaro-Winkler on sorted tokens plus a typo-tolerant token Dice), address and location. Two different valid tax IDs never match. The same tax ID with very different names goes to REVIEW.
4. **Cluster**: union-find over AUTO pairs, refusing any merge that would put two different valid tax IDs in one Business Partner.

## Honest caveats

- The common-abbreviation table and the city aliases are reference data shared with the generator. That is realistic, since real projects keep such tables, but it flatters those noise types. The rare abbreviations are deliberately missing from the table.
- The miss-rate table in the report is correlational: a pair usually carries several noise operations.
- Synthetic data is cleaner than real data in some ways and harsher in others. The point is a controlled, repeatable benchmark.

## Roadmap

- **Phase 2**: better rules. The report already names the targets.
- **Phase 3**: an LLM decides the REVIEW pairs, with structured output and cited evidence. The evaluation compares models on accuracy, cost per 1,000 records and latency against the ceiling above.
- **Phase 4**: golden record proposal (survivorship rules, customer and vendor roles on one BP), a review screen for people, and a legacy-key → BP mapping file for the migration.
