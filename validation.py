"""Did we read this page correctly.

That is the whole question this module asks.  It runs at ingest, over every
file, and it has exactly two checks:

**Quality** — deterministic signals that OCR failed: character soup, a page
that produced forty characters where its neighbours produced two thousand,
words with no vowels.  No model, always runs, reproducible.

**Fidelity** — a model looks at the page image and the text extracted from it
and reports where they disagree: content missing, a figure or date that
differs, a table that came across scrambled, a stamp or handwritten note the
text does not mention.

## What this deliberately does not do

It does not read for meaning.  Whether a total adds up, whether a date
contradicts another document, whether a referenced exhibit was ever attached —
those are findings about the case, and they belong to the analysis that runs
over the whole record, not to the moment a file is read.  Confusing the two
would put a model's opinion about a case inside the ingest path, which is
exactly the thing this product does not do.

The extractor stays authoritative.  Nothing here rewrites text, changes a
Trust Lock, or resolves its own flag.  A discrepancy becomes an item in a
queue and a person decides.

## Cost

A model pass over every page is not free, so validation runs after ingest
completes, on its own thread, resumable: an ingest is never blocked waiting
for it, and a machine turned off mid-pass picks up where it stopped.  With no
model installed the deterministic half still runs and the queue still fills.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence


class Status(str, Enum):
    OPEN = "open"             # awaiting a person
    CONFIRMED = "confirmed"   # a person accepted the extraction as it stands
    CORRECTED = "corrected"   # a person re-ran or supplied a correction
    EXCLUDED = "excluded"     # a person excluded the page or document


class Kind(str, Enum):
    QUALITY = "quality"       # deterministic signal that OCR failed
    FIDELITY = "fidelity"     # text disagrees with the page image


# --------------------------------------------------------------------------
# Deterministic signals.  Always run, no model, reproducible.
# --------------------------------------------------------------------------

_SANE = re.compile(r"[A-Za-z0-9\s.,;:'\"()\[\]{}/\\@#$%&*+=<>?!_\-—–§¶©†‡°]")
_WORD = re.compile(r"[A-Za-z]{2,}")
_VOWEL = re.compile(r"[aeiouAEIOU]")

NOISE_LIMIT = 0.08
VOWELLESS_LIMIT = 0.28
SHORT_TOKEN_LIMIT = 0.45
RELATIVE_LENGTH_FLOOR = 0.18
MIN_CHARACTERS = 40


@dataclass
class PageQuality:
    source: str
    page: int
    method: str
    characters: int
    noise_ratio: float
    vowelless_ratio: float
    short_token_ratio: float
    relative_length: float
    reasons: List[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.reasons)

    def as_dict(self) -> dict:
        value = asdict(self)
        value["failed"] = self.failed
        return value


def score_page(source: str, page: int, text: str, method: str,
               median_length: float = 0.0) -> PageQuality:
    body = str(text or "")
    characters = len(re.sub(r"\s+", "", body))

    sane = len(_SANE.findall(body))
    noise_ratio = 0.0 if not body else round(1 - (sane / len(body)), 4)

    words = _WORD.findall(body)
    vowelless_ratio = round(
        sum(1 for word in words if not _VOWEL.search(word)) / len(words), 4) if words else 0.0

    tokens = body.split()
    short_token_ratio = round(
        sum(1 for token in tokens if len(token) <= 2) / len(tokens), 4) if tokens else 0.0

    relative = round(characters / median_length, 4) if median_length else 1.0

    quality = PageQuality(source, page, method, characters, noise_ratio,
                          vowelless_ratio, short_token_ratio, relative)
    if characters < MIN_CHARACTERS:
        quality.reasons.append("page produced almost no text")
    if noise_ratio > NOISE_LIMIT:
        quality.reasons.append(f"{noise_ratio:.0%} of characters fall outside the expected set")
    if vowelless_ratio > VOWELLESS_LIMIT:
        quality.reasons.append(f"{vowelless_ratio:.0%} of words contain no vowel")
    if short_token_ratio > SHORT_TOKEN_LIMIT:
        quality.reasons.append(f"{short_token_ratio:.0%} of tokens are one or two characters")
    if median_length and relative < RELATIVE_LENGTH_FLOOR:
        quality.reasons.append(
            f"page is {relative:.0%} the length of a typical page in this document")
    return quality


def score_document(source: str, pages: Sequence[str], method: str) -> List[PageQuality]:
    """Score every page against the document's own median.

    A four-word cover page is normal in a document of four-word pages and
    suspicious in a document of dense ones, so the comparison is internal.
    """
    lengths = [len(re.sub(r"\s+", "", str(page or ""))) for page in pages]
    median = statistics.median(lengths) if lengths else 0.0
    return [score_page(source, number, text, method, median)
            for number, text in enumerate(pages, 1)]


# --------------------------------------------------------------------------
# The two model checks.  Both return findings; neither returns text.
# --------------------------------------------------------------------------

FIDELITY_PROMPT = """You are comparing text extracted by OCR against the page image it came from.

You are NOT transcribing, correcting, summarizing or interpreting this page.
Your only job is to report where the text and the image DISAGREE.

Report every disagreement you can see, of any kind:
- content on the page that is missing from the text
- content in the text that is not on the page
- a number, amount, date, name, docket or citation that differs between them
- a table, column or signature block that came across scrambled
- handwriting, a stamp, a seal or a marginal note the text does not mention
- a page that is rotated, cut off, or too poor to read

Answer with a single JSON object and nothing else:
{"agrees": true|false,
 "confidence": 0.0-1.0,
 "findings": [{"type": "missing|extra|figure|date|name|table|annotation|illegible",
               "detail": "<one short sentence>",
               "severity": "high|medium|low"}]}

If the text is a faithful reading, return agrees true and an empty findings list.
If you cannot tell, return agrees false with one finding of type illegible.
Never output replacement text. Never guess at a value you cannot read."""


@dataclass
class Finding:
    type: str
    detail: str
    severity: str = "medium"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Check:
    source: str
    page: int
    kind: str              # a Kind value
    agrees: bool
    confidence: float
    findings: List[Finding] = field(default_factory=list)
    model: str = ""
    available: bool = True

    def as_dict(self) -> dict:
        value = asdict(self)
        value["findings"] = [item.as_dict() for item in self.findings]
        return value


_ALLOWED_TYPES = {"missing", "extra", "figure", "date", "name", "table",
                  "annotation", "illegible"}


def _parse(source: str, page: int, raw: str, model: str) -> Check:
    """Read the model's answer defensively.

    Anything malformed becomes a low-confidence disagreement rather than a
    pass: a model that could not answer is not evidence that the document is
    fine.
    """
    text = str(raw or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return Check(source, page, Kind.FIDELITY.value, False, 0.0,
                     [Finding("illegible", "the model did not answer in the required form", "low")],
                     model)
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return Check(source, page, Kind.FIDELITY.value, False, 0.0,
                     [Finding("illegible", "the model answer was not valid JSON", "low")], model)

    agrees = bool(payload.get("agrees"))
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0

    findings: List[Finding] = []
    for item in payload.get("findings") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("type") or "").strip().lower()
        if name not in _ALLOWED_TYPES:
            name = "illegible"
        detail = " ".join(str(item.get("detail") or "").split())[:280]
        severity = str(item.get("severity") or "medium").strip().lower()
        if severity not in {"high", "medium", "low"}:
            severity = "medium"
        if detail:
            findings.append(Finding(name, detail, severity))
    if findings:
        agrees = False
    return Check(source, page, Kind.FIDELITY.value, agrees, confidence, findings, model)


def check_fidelity(client, image: Path, text: str, source: str, page: int) -> Check:
    """Compare one page image against its extracted text."""
    if client is None:
        return Check(source, page, Kind.FIDELITY.value, False, 0.0,
                     [Finding("illegible", "no vision model installed", "low")],
                     available=False)
    try:
        raw = client.look(Path(image), FIDELITY_PROMPT, str(text or ""))
    except Exception as exc:  # noqa: BLE001 - advisory path must never raise
        return Check(source, page, Kind.FIDELITY.value, False, 0.0,
                     [Finding("illegible", f"second read unavailable: {type(exc).__name__}", "low")],
                     getattr(client, "model_label", ""), available=False)
    return _parse(source, page, raw, getattr(client, "model_label", ""))


# --------------------------------------------------------------------------
# Review queue.  Everything flagged, by anything, waits here for a person.
# --------------------------------------------------------------------------

@dataclass
class ReviewItem:
    source: str
    page: int
    kind: str
    status: str = Status.OPEN.value
    reasons: List[str] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)
    quality: Optional[dict] = None
    confidence: float = 0.0
    model: str = ""
    image: str = ""
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def build_queue(qualities: Iterable[PageQuality] = (),
                checks: Iterable[Check] = (),
                images: Optional[dict] = None) -> List[ReviewItem]:
    """Every deterministic failure and every model disagreement becomes an item.

    A model that calls a page fine does not remove an item the gate raised, and
    a gate that passes a page does not suppress a discrepancy the model found.
    The two are independent signals and both are shown.
    """
    lookup = dict(images or {})
    items: List[ReviewItem] = []

    for quality in qualities:
        if not quality.failed:
            continue
        items.append(ReviewItem(
            source=quality.source, page=quality.page, kind=Kind.QUALITY.value,
            reasons=list(quality.reasons), quality=quality.as_dict(),
            image=str(lookup.get((quality.source, quality.page), "")),
        ))

    for check in checks:
        if check.agrees and not check.findings:
            continue
        items.append(ReviewItem(
            source=check.source, page=check.page, kind=check.kind,
            reasons=[f"{item.severity}: {item.detail}" for item in check.findings],
            findings=[item.as_dict() for item in check.findings],
            confidence=check.confidence, model=check.model,
            image=str(lookup.get((check.source, check.page), "")),
        ))
    return items


def queue_path(case_dir: Path) -> Path:
    return Path(case_dir) / "trace" / "validation_review.json"


def save_queue(case_dir: Path, items: Sequence[ReviewItem]) -> Path:
    path = queue_path(case_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": ("Flagged items await a human decision. The extracted record is unchanged "
                 "until a person decides. Model findings are advisory: they never alter "
                 "text, never change a Trust Lock, and never resolve their own flag."),
        "open": sum(1 for item in items if item.status == Status.OPEN.value),
        "items": [item.as_dict() for item in items],
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return path


def load_queue(case_dir: Path) -> List[ReviewItem]:
    path = queue_path(case_dir)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [ReviewItem(**item) for item in payload.get("items", [])]


def open_items(case_dir: Path) -> List[ReviewItem]:
    return [item for item in load_queue(case_dir) if item.status == Status.OPEN.value]


def decide(case_dir: Path, source: str, page: int, kind: str, status: Status,
           decided_by: str, note: str = "") -> Optional[ReviewItem]:
    """Record a person's decision on one flagged item.

    The decision is what changes, not the extraction.  Correcting or excluding
    a document is a separate action taken by the caller; this records that a
    person made the call, so the audit chain has something to seal.
    """
    items = load_queue(case_dir)
    hit: Optional[ReviewItem] = None
    for item in items:
        if item.source == source and item.page == page and item.kind == kind:
            item.status = Status(status).value
            item.decided_by = str(decided_by)
            item.decided_at = datetime.now(timezone.utc).isoformat()
            item.note = " ".join(str(note).split())[:400]
            hit = item
            break
    if hit is not None:
        save_queue(case_dir, items)
    return hit


# --------------------------------------------------------------------------
# The pass itself.  Resumable, interruptible, never blocks an ingest.
# --------------------------------------------------------------------------

def _state_path(case_dir: Path) -> Path:
    return Path(case_dir) / "trace" / "validation_state.json"


def _completed(case_dir: Path) -> set:
    path = _state_path(case_dir)
    if not path.is_file():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get("done", []))
    except (OSError, ValueError):
        return set()


def _mark_done(case_dir: Path, done: set) -> None:
    path = _state_path(case_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"done": sorted(done)}, indent=2), encoding="utf-8")
    temporary.replace(path)


def validate_case(case_dir: Path,
                  documents: Iterable[dict],
                  client=None,
                  progress: Optional[Callable[[int, int, str], None]] = None,
                  resume: bool = True) -> Path:
    """Run both checks over every document and write the queue.

    ``documents`` yields, per file:
        {"source": str, "method": str, "pages": [str, ...],
         "images": {page_number: path, ...}}

    ``client`` is optional.  Without it the deterministic gate still runs and
    its flags still reach the queue.
    """
    case_dir = Path(case_dir)
    docs = list(documents)
    done = _completed(case_dir) if resume else set()
    existing = {(item.source, item.page, item.kind): item
                for item in (load_queue(case_dir) if resume else [])}

    qualities: List[PageQuality] = []
    checks: List[Check] = []
    images: dict = {}

    for index, document in enumerate(docs, 1):
        source = str(document.get("source") or "")
        if progress:
            progress(index, len(docs), source)
        if resume and source in done:
            continue

        method = str(document.get("method") or "")
        pages = list(document.get("pages") or [])
        page_images = dict(document.get("images") or {})

        qualities.extend(score_document(source, pages, method))

        for number, image in page_images.items():
            number = int(number)
            images[(source, number)] = image
            page_text = pages[number - 1] if 0 < number <= len(pages) else ""
            checks.append(check_fidelity(client, Path(image), page_text, source, number))

        done.add(source)
        _mark_done(case_dir, done)

    fresh = build_queue(qualities, checks, images)
    # Decisions already made are preserved; a re-run never reopens a resolved item.
    merged = list(existing.values())
    seen = set(existing)
    for item in fresh:
        key = (item.source, item.page, item.kind)
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return save_queue(case_dir, merged)


# --------------------------------------------------------------------------
# Running it in the background
# --------------------------------------------------------------------------

def document_record(source: str, result) -> dict:
    """One ingested file, in the shape ``validate_case`` consumes.

    ``result`` is an ``ingestion.ExtractionResult``.
    """
    return {
        "source": str(source),
        "method": result.method,
        "pages": list(result.page_text) or [result.text],
        "images": {int(number): str(path) for number, path in result.page_images.items()},
    }


def start_background(case_dir: Path, documents: Iterable[dict],
                     on_finish: Optional[Callable[[int, str], None]] = None):
    """Check an ingest in the background and return the thread.

    Fire and forget: the caller does not wait, does not handle errors, and does
    not need a screen.  Findings land in ``trace/validation_review.json`` and
    progress is written per file, so an interrupted run resumes.

    ``on_finish(open_count, error)`` is called on the worker thread when the
    pass ends, if supplied.  ``error`` is an empty string on success.
    """
    import threading

    docs = list(documents)

    def work() -> None:
        client = None
        error = ""
        try:
            from . import vision
            client = vision.available_client()
            validate_case(Path(case_dir), docs, client=client)
        except Exception as exc:  # noqa: BLE001 - background work never raises at the caller
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
        if on_finish:
            try:
                on_finish(len(open_items(Path(case_dir))), error)
            except Exception:
                pass

    thread = threading.Thread(target=work, name="pai-legal-validation", daemon=True)
    thread.start()
    return thread


def summary(case_dir: Path) -> dict:
    """Counts for a status line, if the host wants to show one."""
    items = load_queue(case_dir)
    return {
        "flagged": len(items),
        "open": sum(1 for item in items if item.status == Status.OPEN.value),
        "high": sum(1 for item in items
                    if any(finding.get("severity") == "high" for finding in item.findings)),
        "documents": len({item.source for item in items}),
    }
