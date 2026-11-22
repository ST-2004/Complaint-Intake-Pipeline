# Data

**Everything in this folder is synthetic.** "Maple Harbour Bank" is fictional. Names
are invented, phone numbers use the 555-01xx range reserved for fiction, email
addresses use the reserved `example.*` domains, and card, SIN and IBAN values are
publicly documented test numbers that pass checksum validation but belong to no one.
No customer, employer or real-institution data is used.

| File | Purpose |
|---|---|
| `samples/pii_samples.jsonl` | 10 hand-written complaints with seeded PII (M1). Each line lists its `seeded` values so the leak check is mechanical. Includes deliberate hard cases: an all-lowercase name, two people in one complaint, and one complaint with no PII. |

| `samples/classify_samples.jsonl` | 10 complaints with a drafted label (category, severity, needs-review) for the M2 sanity check. One is a prompt-injection attempt. |

| `situations.jsonl` | 80 hand-written labelled complaints (8 per category) with PII slots. Labels follow `LABELING_GUIDE.md`. |
| `synthetic/dev.jsonl`, `synthetic/heldout.jsonl` | Generated from the situations with seeded fake PII (`python tasks.py generate-data`); 50 dev, 30 held-out, stratified. Every planted value is listed in `seeded`. |
| `synthetic/manifest.json` | Seed and SHA-256 of each generated file. |

Red-team and counterfactual sets live in `eval/`. See `docs/evaluation.md`.
