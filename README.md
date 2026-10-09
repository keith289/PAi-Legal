# PAi Legal

PAi Legal is a separate Microsoft Store product and a complete private legal
workspace. It does not require PAi or PAi LFM.

## What is included

- Custom Windows UI with one active case at a time.
- Untouched originals, organized working copies, and source-traced case records.
- Bundled Tesseract OCR and extraction for native/scanned PDF, images, DOCX,
  ODT, XLSX, PPTX, RTF, EML, MSG, text, HTML, CSV, and structured text.
- A bundled `llama-server` runtime for fully local inference.
- First-run hardware scan covering RAM, available storage, CPU, GPU, and VRAM.
- A vetted Hugging Face GGUF catalog. PAi Legal recommends the strongest model
  that fits conservatively and lets the user choose a smaller compatible model.
- Resumable model download into `%LOCALAPPDATA%\PAiLegal\models`.
- Optional PSi Legal integration for retrieval-only case-law research.
- Canonical Python `BracketFloat`, `mix`, and `stir` primitives carrying the
  four-position epistemic vector, evidence mass, lineage, and causal τ.
- Legal relational-pressure mapping during ingestion: Float observations,
  Mix entity relations, Stir recurrence/cross-carry, pressure, clarity, and a
  deterministic pattern signature for each document.
- Canonical claim brackets in the case record and AI output. Repetition or high
  pressure cannot promote a claim to validated.
- No API key, cloud inference, monthly AI fee, or dependency on another PAi app.

### Version 0.9.6 professional controls

- Operating-system-account roles for owner, lawyer, paralegal, intake, and auditor access.
- Windows DPAPI credential vault for audit keys and authenticated loopback-service tokens.
- Optional strict BitLocker policy that blocks case writes unless workspace-volume encryption is verified.
- HMAC-SHA256 chained audit events with a DPAPI-protected head anchor, detecting edits, replacement, and rollback.
- Retention dates, disposition eligibility, legal holds, and audited hold release.
- Deterministic party-name conflict screening across active and archived matters; results require human clearance.
- Passphrase-encrypted AES-GCM case backups with Scrypt key derivation, a SHA-256 file manifest, safe-path validation, and authenticated restore.
- Federal civil and Georgia Superior Court mechanical filing preflight packs, with official-source dates and an unconditional current-local-rules warning.
- Immutable model revisions and published SHA-256 verification before a downloaded GGUF can be installed.
- Optional MSIX certificate signing, timestamping, and signature verification as a release gate.

## Customer interface

### Version 0.8 Precognitive Case Map

- Adds a first-class Precognitive Case Map between Evidence and PSi Research.
- Uses the Klein A/B/C transition channels as a deterministic structural map:
  matter/measurable consequence at k66, relation/duty/authority at k90, and
  chronology/act/procedure at k120.
- Supports recursive semantic zoom. A document transition opens into its
  Float, Mix, and Stir layers; relational points can open again into the leaf
  components inside that transition.
- Separates semantic zoom from ordinary optical zoom so users can inspect
  structure without losing the whole-case view.
- Records an input signature, deterministic seed, and replay signature for
  exact map reconstruction and audit.
- Adds Clerk, Advocate, Opposition, Precedent Judge, Forecaster, and Recorder
  projections. These are deterministic views of the stored map, not model
  personas voting or fabricating authorities.
- Labels every projection as a structural forecast, not a prediction of a
  judge, jury, settlement, or court outcome.
- Preserves provenance through every transition and carries the weakest Trust
  Lock forward. Relational pressure can focus attention but cannot promote or
  demote epistemic status.
- Prevents generated Float/Mix and Float/Stir relations from recursively
  feeding one another. Intermediate depth now appears as explicit nested maps
  rather than unbounded relation strings.
- Adds amounts and physical measurements to the matter channel during RPM
  indexing, allowing legal loss and extent to occupy the k66 side of the map.
- Includes map signatures and Parliament projections in Markdown and PDF case
  exports.

Version 0.5 replaces the development-style tabbed utility with a branded PAi
Legal workspace using the `#18A7FF` PAi accent:

- Persistent local case storage; any PSi service query or external drafting send is a separate, visible action.
- Sidebar workflow: Case Dashboard, Evidence, PSi Research, Private Analysis,
  and Settings.
- Guided case progression from creation through evidence, authority selection,
  and private analysis.
- Drag-and-drop evidence ingestion in the Windows build.
- Document preview and visible `Preserved → Extracted/OCR → Float/Mix/Stir → Ready`
  processing state.
- Case-level Float, Mix, Stir, total-pressure, and top-relation dashboard.
- Readable authority details with trust lock, topology colors, pressure and RPM
  counts instead of raw JSON.
- Chat-style analysis with bracket colors, visible source markers and a
  permanent epistemic legend.
- Customer actions remain prominent; technical diagnostics are under Settings.

### Version 0.7 unified product interface

- Keeps the customer-friendly Dashboard → Evidence → Research → Analysis → Settings workflow.
- Adds a native application menu and keyboard-first access to case, work-product, view, and Trust Lock help commands.
- Shows Private AI, PSi Legal, and OCR readiness in the product header.
- Uses one canonical bracket parser for inline colors, audit counts, tension checks, pinned claims, and exports.
- Presents selected and case-attached authorities as compact Trust Lock + Float/Mix/Stir chips in Analysis.
- Expands exports with each document's RPM contribution and pattern signature, authority metadata, and an epistemic answer summary.
- When PSi Legal is not installed, the Research page presents a full product placeholder describing local stored-authority search, returned metadata, RPM/Trust Lock behavior, persistent case hand-off, privacy, and the separate Microsoft Store installation path.
- The placeholder states that PSi Legal includes more than 5 million indexed case-law records and includes database updates.
- It states that searching, indexing and case hand-off operate completely offline and privately, with no case files, search terms, prompts or results transmitted.

### Version 0.6 case-work foundation

- Document-level RPM inspection with Float/Mix/Stir points, signature, pressure,
  and percentage contribution to the case total.
- Continuous intensity bars on the Evidence RPM cards.
- Append-only epistemic event log for analysis, pinned claims, reprocessing,
  attached authorities and exports.
- Pin a bracketed analysis claim or add a free case note; the original Trust
  Lock, source markers and timestamp are preserved.
- Right-click a preserved/filed document to re-extract, re-OCR and re-index
  only that document without duplicating evidence.
- Export a bracket-preserving Markdown or PDF work-product package containing
  RPM summary, authorities, pinned claims, analysis and audit events.
- Permanently attach selected PSi authorities—including their Trust Locks and
  Float/Mix/Stir fields—to the active case.
- Exact-claim tension detection surfaces conflicting Trust Locks without
  deciding which claim is correct.
- Archive and restore cases, search extracted text/RPM indexes, and inspect the
  installed GGUF model with recorded memory/GPU headroom.
- Keyboard actions: `Ctrl+N`, `Ctrl+O`, `Ctrl+F`, `Ctrl+Enter`, and `F5`.

The automatic catalog currently uses official, ungated Apache-2.0 Qwen3 GGUF
releases (1.7B at Q8_0; 4B, 8B, and 14B at Q4_K_M). This makes unattended setup honest
and repeatable. Gated or license-click-through families should be added only
with an explicit user sign-in and license-acceptance flow.

## Private-AI setup

Open **Integrations → Set up private AI**. PAi Legal scans the device, shows
compatible choices, resolves the current official file on Hugging Face,
downloads it with resume support, and test-starts the bundled runtime. Models
are not bundled in the MSIX, keeping the Store package practical.
Every selected binary is resolved to an immutable repository revision and must
match its repository-published SHA-256 digest before installation.

Application data:

- Models: `%LOCALAPPDATA%\PAiLegal\models`
- Installation record: `%LOCALAPPDATA%\PAiLegal\config\ai_installation.json`
- Local service: `127.0.0.1:8081` while analysis is running

## PSi Legal compatibility

PAi Legal sends the query's Float/Mix/Stir counts and pattern signature to the
PSi Legal search service. It reads the existing PSi fields `float_points`,
`mix_points`, `stir_points`, `total_pressure`, and the three topology colors,
plus optional `bracket` and `pattern_signature` fields. Selected authorities
carry those values unchanged into private analysis.

Bracket meaning remains independent from pressure:

- `[{claim}]` — unverified
- `[[claim]]` — speculative
- `{[claim]}` — explained
- `[[[claim]]]` — independently validated

## Run and test

```powershell
py -3.12 run_pai_legal.py
py -3.12 -m unittest discover -s tests -v
```

## Windows Store build

Reserve **PAi Legal** as its own Partner Center product. Add `StoreLogo.png`,
`Square150x150Logo.png`, and `Square44x44Logo.png` under `Assets`, then run:

```powershell
$env:PAI_LEGAL_IDENTITY_NAME = "<PAi Legal identity from Partner Center>"
$env:PAI_LEGAL_PUBLISHER = "CN=<exact Partner Center publisher>"
.\build_windows.ps1 -Version 1.0.0.0 `
  -TesseractDir "C:\Program Files\Tesseract-OCR" `
  -LlamaCppDir "C:\runtimes\llama.cpp"
```

For a signed sideload/release gate, install the signing certificate in the
current user's certificate store and use its thumbprint:

```powershell
$env:PAI_LEGAL_SIGNING_THUMBPRINT = "<40-character certificate thumbprint>"
.\build_windows.ps1 -RequireSignedPackage
```

The llama.cpp directory must contain `llama-server.exe`, its companion DLLs,
and license. The build runs tests, bundles both runtimes, and creates a separate
PAi Legal MSIX. Run the Windows App Certification Kit before submission.

PAi Legal assists with legal information and work product; it does not provide
legal advice. Users must verify citations and current law.
