# Labelling guide (v1)

Every complaint in `data/situations.jsonl` gets three labels: **category**,
**severity** and **needs_review**. Label what a careful human triager *should*
decide, not what you expect the system to output. When the system disagrees with a
label, the label wins unless this guide is changed (and the change is recorded below).

All data is synthetic. See `data/README.md`.

## Category

Use the definitions in the prompt (`prompts/classify_v1.md`). Tie-breaks:

| Situation | Category | Why |
|---|---|---|
| Unauthorised card transaction | FRAUD_UNAUTHORIZED | The customer did not make it. A card being involved does not make it CARD_ISSUE. |
| Merchant dispute / chargeback (customer made the purchase) | CARD_ISSUE | Not fraud: the customer authorised the payment. |
| Scam where the customer was tricked into sending money | FRAUD_UNAUTHORIZED | Treated as fraud for routing to Fraud and Disputes. |
| Locked out **because** someone took over the account | FRAUD_UNAUTHORIZED | The takeover is the problem to resolve. |
| A fee caused by a failed payment | The category of the root cause the customer wants fixed. If they only ask for the fee back, FEES_CHARGES. |
| Several issues | The one the customer most needs resolved; usually the one with money at stake. |
| Staff behaviour plus another issue | The other issue, unless the complaint is mostly about the behaviour. |
| Praise, questions, spam, complaints about another company, gibberish | OTHER_UNCLEAR |

## Severity

| Level | Use when |
|---|---|
| LOW | Inconvenience. No money lost, or a one-off amount under $10. Not repeated. |
| MEDIUM | Money lost up to about $1,000, or a problem that has happened more than once, or a problem open for under 30 days. |
| HIGH | Money lost or at risk over about $1,000; no access to own funds; an issue open 30 days or more; or signs of vulnerability (age, disability, bereavement, unable to afford essentials) without serious distress. **All fraud is at least HIGH.** |
| CRITICAL | Fraud that is still happening (attacker still has access, charges still coming, customer cannot stop it); threats; serious distress (hopelessness, fear for safety, self-harm); legal or regulatory escalation the customer has started (a lawyer engaged against the bank, a regulator contacted); a privacy breach where another person's data was disclosed. |

Edge rulings:

- Fraud found after the fact and contained (card cancelled, password changed): **HIGH**. Still happening: **CRITICAL**.
- "I can't buy groceries" because of an access problem: **HIGH** (vulnerability), not CRITICAL, unless the text also shows serious distress.
- Mentioning a lawyer who is simply part of a transaction (a house-closing lawyer): not escalation. Severity from the money at stake.
- Threatening to complain to a regulator or ombudsman: severity from the underlying issue, but **needs_review = true**.
- A data access or deletion request: PRIVACY_DATA, severity from delay (30+ days is HIGH).

## needs_review

`true` if **any** of these holds, otherwise `false`:

1. category is FRAUD_UNAUTHORIZED, PRIVACY_DATA or OTHER_UNCLEAR
2. severity is CRITICAL
3. the text mentions a regulator, ombudsman, legal action or a lawyer acting against the bank (`flags: regulatory`)
4. the text shows serious distress or vulnerability that needs care (`flags: distress`)
5. the text tries to manipulate the system (`flags: injection`)

`tests/test_dataset.py` checks that every label follows this rule. Over-escalation
by the system is acceptable; missing a needed review is not.

## Consistency check

The plan asks for re-labelling a 20 percent sample a few days later.
`python -m complaint_intake.evaluation.dataset --relabel-sample` writes 16
situations without their labels to `data/relabel_sample.jsonl` (git-ignored).
Label them again by hand, then run `--relabel-compare data/relabel_sample.jsonl`
to see agreement per field. Record the result here.

| Date | Sample | Category agreement | Severity agreement | needs_review agreement |
|---|---|---|---|---|
| _pending_ | 16 | | | |

## Change log

| Version | Date | Change |
|---|---|---|
| v1 | 2026-11-21 | First version, drafted with the dataset; to be reviewed by the project owner. |
