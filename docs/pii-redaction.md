# PII redaction and enrichment (M1)

Only the redactor sees raw complaint text. Everything downstream, from enrichment
to the model and the audit log, gets the redacted text and a list of categories,
never the detected values.

## Design

| Decision | Why |
|---|---|
| One `Redactor` interface; `AzureLanguageRedactor` (primary) and `PresidioRedactor` (local fallback), chosen by `PII_PROVIDER` | Swappable seam (P12): if Language is blocked in a subscription, set `PII_PROVIDER=presidio` and nothing else changes. |
| Spans become tags: `[PERSON]`, `[PHONE_NUMBER]`, `[EMAIL]`, `[ADDRESS]`, `[CARD_NUMBER]`, `[ACCOUNT_NUMBER]`, `[GOVERNMENT_ID]`, `[IP_ADDRESS]`, `[PII]` | The classifier prompt expects tags, and one vocabulary for both providers keeps the audit log the same when the provider changes. |
| Category filter: **not** redacted are Organization, Date, Age, Quantity, URL | Triage needs the bank and merchant names, dates and amounts. A date of birth will therefore survive (a documented limitation). |
| Fail closed: any exception, timeout, per-document error or result mismatch raises `RedactionError`; messages carry only an error type or code; exceptions are not chained | P2: if redaction is in doubt, the model is never called (enforced in the M3 pipeline). |
| Long text is split into chunks of 5,000 characters or fewer at paragraph, sentence, then word boundaries, sent 5 per request | Service limits. Cutting at boundaries makes it unlikely that an entity is split across two chunks. |
| Belt and braces: any run the service masked with `*` is redacted even if the entity offsets disagree | Guards against offset bugs. |
| Name propagation: words of a detected name are redacted everywhere, plus a capitalised word directly before a repeated surname | spaCy missed "(Helena Becker)" after finding "Tobias Becker". This errs towards over-redaction, the safe direction. |
| `disable_service_logs=True` on every Language call | Azure does not keep the text for troubleshooting. |
| Enrichment (sentiment, key phrases) runs on redacted text and never raises: a failure returns `Signals(available=False)` | Signals only ever add scrutiny; M3 rules treat "unavailable" as a reason to look harder. Key phrases that are redaction tags are dropped. |

Presidio additions (it has no Canadian recognizers): SIN with Luhn check, postal
code, street address, and account numbers boosted by context words. It uses the
spaCy `en_core_web_sm` model (`PRESIDIO_MODEL` to change it).

## Results on `data/samples/pii_samples.jsonl` (10 complaints, 28 seeded values)

`python tasks.py pii-check [--provider presidio] [--show] [--enrich]`

| Provider | Values that survived | Notes |
|---|---|---|
| Azure AI Language (westus3, 2026-11-11) | **0 / 28** | Account and mortgage numbers were tagged `PHONE_NUMBER` (redacted, but the category is wrong). |
| Presidio + `en_core_web_sm` (local) | **0 / 28** | Before name propagation: 1 value leaked ("Helena Becker" in brackets). A mortgage number was tagged `GOVERNMENT_ID`. |

n = 28 seeded values is small. These numbers show the mechanism works; they do
not show that redaction is perfect. M4 measures the leak rate on the full
synthetic dataset.

## Known limitations

- Dates (including dates of birth), ages and organisation names are kept on purpose.
- Detection is statistical. Unusual or lowercase names, or names written like ordinary words, can be missed. The leak rate is measured, not assumed.
- Category labels for numbers are not always right (an account number reported as a phone number). The value is still removed, but `pii_categories_found` can be imprecise.
- An entity split across a chunk boundary could escape detection. Cuts at sentence boundaries make this unlikely, but it is not impossible.
- The leak check matches seeded values exactly (names word by word, numbers without separators). A value that was rewritten, rather than removed, would not be counted.
