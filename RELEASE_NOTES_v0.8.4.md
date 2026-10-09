# PAi Legal v0.8.4 - Case Map + corrected retrieval

Merges the v0.8.0 Precognitive Case Map with five engine corrections. All
v0.8.0 behaviour is retained; `parliament.py` keeps its Klein primitives and
gains a legal-theory layer above them.

## Corrections

1. **Question-aware retrieval.** `context()` took no question, so every answer
   was assembled from whichever documents sorted first alphabetically. A case
   with 72 documents sent the same 4 every time. Terms are now weighted by
   inverse document frequency, filenames are scored (a mold report rarely says
   "mold" in its body), and matched passages are widened into the remaining
   budget.

2. **Context format.** `[(Stamm) Final Settlement and Release (1).txt:3] [{RELEASE}]`
   spent 60 characters to deliver 7. The filename repeated on every line and
   the bracket wrapper was always UNVERIFIED, carrying no information.
   Documents are now grouped under one header with bare numbered lines, and
   extraction bookkeeping is filtered out. Measured: 90% evidence, up from
   roughly one third.

3. **Document precedence (`doctypes.py`).** Ingest sorted by file type, making
   a complaint a peer of an advertisement. Eleven ranked roles now drive
   filing, context ordering, and the evidence tree. Controlling documents
   (pleadings, orders) hold 35% of the context budget so the operative
   pleading is present whatever the question. Classification reads the
   document's first page, not just its name.

4. **Console windows (`procutil.py`).** llama-server, Tesseract, PowerShell
   and nvidia-smi each opened a console window - once per question, once per
   capability refresh, once per OCR'd page.

5. **Docket regex.** `[A-Za-z0-9\-.,/ ]{1,60}` allowed spaces and commas, so
   `No. HO-4291018` ran across two sentences and filed a paragraph as one
   docket observation.

Also: self-recurrence tautologies (`F[STATE:georgia]<->S[STATE=georgia]`) no
longer outrank real relations.

## Parliament: legal theories

`case_posture(case)` resolves each pleaded theory across the three channels.
Deterministic and model-free - identical with or without private AI installed.

- A / k66 matter, B / k90 relation, C / k120 chronology
- A pleading ASSERTS an element and cannot SUPPORT it. A theory standing only
  on its own complaint reports a gap.
- Amounts are typed: MONEY_BENEFIT (what the policy owed) vs MONEY_EXTRA
  (fees, interest, consequential). Bad faith accepts only the latter, so a
  repair estimate cannot resolve it. Ambiguous amounts default to benefit.
- A pattern of adverse events across distinct dates is reported as
  circumstantial support for knowing conduct. It never satisfies the element.
- Relational pressure never promotes or demotes a Trust Lock.

## Verification

32 tests pass. The 33rd requires `pymupdf`.
