# PAi Legal v0.8.0 - Precognitive Case Map

## What changed

- Added a native Precognitive Case Map between Evidence and PSi Research.
- Added recursive semantic zoom from a case transition to document Float/Mix/Stir
  layers, then to relational points and their leaf components.
- Added deterministic input, seed, and replay signatures.
- Added structural Clerk, Advocate, Opposition, Precedent Judge, Forecaster,
  and Recorder projections.
- Added causal-depth and provenance-mass inspection.
- Added amount and measurement observations to the matter/k66 channel.
- Bounded Float/Mix/Stir cross-carry so generated relations cannot feed back
  into unbounded nested strings.
- Added map data and Parliament projections to Markdown and PDF exports.
- Corrected document pressure percentages to use unrounded case totals.

## Epistemic and legal guards

- Relational pressure never promotes or demotes a Trust Lock.
- Parliament output is a deterministic view of stored structure, not a vote
  between models.
- The Case Map is labeled as a structural forecast, not a prediction of a
  judge, jury, settlement, or court outcome.
- Attached PSi authorities remain distinguishable from case evidence.

## Existing cases

Existing case folders remain compatible. Old RPM indexes can be displayed and
mapped immediately. To receive the bounded cross-carry behavior and new amount
and measurement observations for an older document, right-click that document
in Evidence and choose **Re-process this document**.

## Verification

- 24 unit and integration tests pass.
- End-to-end verification covered two-document ingestion, source-traced case
  record creation, three levels of semantic zoom, deterministic replay,
  Parliament projections, and Markdown/PDF export.

## Windows build

Use the same Store identity and build process as v0.7.3. Choose the Microsoft
Store package version separately when invoking `build_windows.ps1`.

```powershell
py -3.12 -m unittest discover -s tests -v

.\build_windows.ps1 -Version 1.0.1.0 `
  -TesseractDir "C:\Program Files\Tesseract-OCR" `
  -LlamaCppDir "C:\runtimes\llama.cpp"
```

Run the Windows App Certification Kit against the resulting MSIX before the
next Store submission.
