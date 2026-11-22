# Evaluation (M4)

M4 measures the whole system (redaction, model and rules together) on labelled
synthetic data, then publishes the numbers with their sample sizes.

## The data

| Set | File | Size | Purpose |
|---|---|---|---|
| Situations | `data/situations.jsonl` | 80 (8 per category) | Hand-written complaints with labels and PII slots. The source of truth. |
| Dev | `data/synthetic/dev.jsonl` | 50 (5 per category) | Tune prompts and rules here only. |
| Held-out | `data/synthetic/heldout.jsonl` | 30 (3 per category) | Report final numbers. Run at milestone ends only. |
| Red-team | `eval/redteam.jsonl` | 20 | Attacks, each with its expected behaviour written in advance. |
| Counterfactual | `eval/counterfactual.jsonl` | 10 pairs | Same complaint with one change: name origin, gender, typos, all caps, no punctuation, second-language English, tone. |

`python tasks.py generate-data` fills the PII slots with seeded fake values and
splits the situations, stratified by category. The same seed reproduces the same
files byte for byte, and a test checks that the files on disk match the generator.
Labels follow [`data/LABELING_GUIDE.md`](../data/LABELING_GUIDE.md), and a test checks
every `needs_review` label against the guide's rule.

Label distribution in the held-out set: 7 LOW, 12 MEDIUM, 9 HIGH, 2 CRITICAL; 55
seeded PII values across both sets. With 30 cases, one mistake moves a rate by 3.3
points, so the report shows counts (27/30) next to every rate.

## What is measured

| Metric | How | Target |
|---|---|---|
| Category accuracy, macro-F1, per class, confusion matrix | final category vs label | macro-F1 >= 0.85 |
| Severity accuracy, off by one, lower than label, HIGH+CRITICAL recall | final severity (model + rules) vs label | HIGH+CRITICAL recall >= 0.95 |
| Needs-review recall and precision | final routing vs label | recall >= 0.95 |
| PII leaks by type | each seeded value checked in **what was sent to the model** (captured at the boundary) and in the **whole database** | 0 |
| Schema validity | first attempt, after retry, still invalid, filtered, call failed | >= 0.95 first attempt |
| Summary groundedness | numbers and proper nouns in the summary that are not in the redacted complaint; read the flagged ones by hand | report |
| Confidence | mean self-reported confidence when right vs wrong | report |
| Red-team pass rate | every expectation of a case must hold | >= 0.90 |
| Counterfactual consistency | same category and severity across the pair | >= 0.95 |
| Latency p50 / p95, tokens, cost per complaint | from the pipeline metrics | report |

Each report records the git commit (with `-dirty` if there are uncommitted changes),
prompt version and SHA, rules version, model deployment, PII provider, and the
SHA-256 of every dataset file. If `eval/reports/baseline_<set>.json` exists, the
report adds a before-and-after table.

## Running it

**Offline (free, no Azure):** checks the harness, the data and Presidio redaction.
The model is a keyword stub, so the report is stamped MOCK and is git-ignored.

```powershell
python tasks.py eval --offline
```

**For real (your steps; costs a few cents):**

```powershell
# 0. Commit the M4 code first, so the report records a clean commit (not "-dirty").
python tasks.py infra-up
python tasks.py env

python tasks.py eval                                   # dev + red-team + counterfactual
python tasks.py eval --set heldout --save-baseline     # the baseline: run once
# 3. Commit eval/reports/<date>_heldout_<commit>.md, .json and baseline_heldout.json

python tasks.py infra-down
```

Estimated cost: one dev run makes about 90 model calls and one held-out run about
70 (each including red-team and counterfactual), at roughly $0.0005 per call, so
under $0.10 for both. Redaction and enrichment use about 3 Language records per
text (about 270 and 210, against the F0 allowance of 5,000 per month). Repeated dev
runs reuse cached redaction and enrichment results (`eval/.cache/`, redacted output
only, invalidated automatically when the redaction or enrichment code changes); use
`--no-cache` for a fully fresh run.

## Definition of done (M4)

| Requirement | Status |
|---|---|
| `make eval` produces the report | `python tasks.py eval` writes Markdown + JSON; tested offline end to end (`tests/test_run_eval.py`) |
| Baseline numbers are committed | **Your step**: the held-out run above |
| You can explain each failure category | The report lists every case that differs from its label, with expected vs got and the rules that fired |

## Findings while building M4 (offline)

1. **Presidio leaked 3 of 32 seeded values on the dev set** (a street address with
   an uncommon suffix, a mortgage number without an "account" context word, and a
   name used as a sign-off). Fixed generically: a structural street-address
   pattern, more context words, and a sign-off/introduction name recogniser. Now
   0 leaks on dev and 0/28 on the M1 samples.
2. **Presidio compiles patterns case-insensitively by default.** That turned
   "capitalised word" patterns into "any word": `$15.95 monthly fee` was redacted
   as an address. Custom recognisers now set case-sensitive flags; regression tests
   added.
3. **The harness catches what it should.** With the keyword stub it flagged
   instruction overrides, spam and a threat that were not sent to review, and two
   counterfactual pairs (typos, second-language English) that changed the
   category. The real model's numbers come from your run.

## Limitations

- All data is synthetic and written by one person; real complaints are messier.
- n = 30 held-out; small differences between runs are noise.
- The labels were drafted with the plan's definitions and should be reviewed by the
  project owner; the guide's consistency check (re-label 20 percent) is still to do.
- Groundedness is a heuristic; it flags candidates for a human to read.
