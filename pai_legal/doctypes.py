"""Legal document roles and the order a lawyer reads them in.

Sorting evidence by file type alone treats a complaint and an advertisement as
peers. They are not: the operative pleading defines the claims, the responsive
pleading defines what is contested, and orders control both. Everything else is
support. Each role therefore carries a rank, and analysis reads in rank order
rather than alphabetically.

Rank 1 is the most authoritative. Classification uses the filename first, then
the opening text when it is available, because scanned filings are often named
"scan_0142.pdf" while the first page says COMPLAINT FOR DAMAGES.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class DocumentRole:
    key: str
    label: str
    folder: str
    rank: int
    # Lower rank wins. Roles at rank 1-3 are controlling documents and are
    # always offered to analysis even when the question does not match them.


ROLES: Tuple[DocumentRole, ...] = (
    DocumentRole("operative_pleading", "Operative pleading", "court_papers", 1),
    DocumentRole("responsive_pleading", "Responsive pleading", "court_papers", 2),
    DocumentRole("order", "Court order or judgment", "court_papers", 3),
    DocumentRole("instrument", "Governing instrument", "court_papers", 4),
    DocumentRole("motion", "Motion or brief", "court_papers", 5),
    DocumentRole("deposition", "Deposition or transcript", "depositions", 6),
    DocumentRole("expert", "Expert report or estimate", "exhibits", 7),
    DocumentRole("discovery", "Discovery", "discovery", 8),
    DocumentRole("correspondence", "Correspondence", "correspondence", 9),
    DocumentRole("exhibit", "Exhibit", "exhibits", 10),
    DocumentRole("unclassified", "Unclassified", "00_inbox", 99),
)

BY_KEY = {role.key: role for role in ROLES}
UNCLASSIFIED = BY_KEY["unclassified"]

CONTROLLING_RANK = 3

# Filename signals. Order matters: the first match wins, so the more specific
# pattern is listed first ("amended complaint" before "motion").
_NAME_RULES: Tuple[Tuple[str, str], ...] = (
    (r"\b(complaint|petition|statement of claim)\b", "operative_pleading"),
    (r"\b(answer|counterclaim|crossclaim|response to complaint)\b", "responsive_pleading"),
    (r"\b(order|judgment|judgement|ruling|opinion|decree|verdict)\b", "order"),
    (r"\b(policy|contract|agreement|lease|release|settlement|deed|note)\b", "instrument"),
    (r"\b(motion|brief|memorandum|memo in support|opposition|reply)\b", "motion"),
    (r"\b(depo|deposition|transcript|affidavit|declaration)\b", "deposition"),
    (r"\b(estimate|appraisal|report|assessment|invoice|inspection)\b", "expert"),
    (r"\b(interrog|rfp|rfa|discovery|subpoena|request for)\b", "discovery"),
    (r"\b(email|e-mail|letter|corresp\w*|outlook|gmail|notice|memo|fw|fwd|re)\b|\.(eml|msg)\b", "correspondence"),
    (r"\b(exhibit|exh[_-]|ex[_-]\d)\b", "exhibit"),
)

# Opening-text signals, for filings whose names say nothing useful.
_TEXT_RULES: Tuple[Tuple[str, str], ...] = (
    (r"\b(complaint for|verified complaint|comes now.{0,80}plaintiff|plaintiff.{0,40}complains)\b", "operative_pleading"),
    (r"\b(answer (and )?(affirmative )?defenses|defendant.{0,40}answers|admits and denies)\b", "responsive_pleading"),
    (r"\b(it is (hereby )?ordered|ordered adjudged|final judgment|the court (finds|rules))\b", "order"),
    (r"\b(this (policy|agreement|contract)|in consideration of|release of all claims)\b", "instrument"),
    (r"\b(motion to|moves this court|memorandum in (support|opposition))\b", "motion"),
    (r"\b(deposition of|sworn testimony|being duly sworn|q\.\s|a\.\s)\b", "deposition"),
    (r"\b(scope of (work|loss)|estimate total|replacement cost value|laboratory (results|report))\b", "expert"),
    (r"\b(interrogator|request for production|request for admission)\b", "discovery"),
    (r"^(from|to|sent|subject):", "correspondence"),
)

_NAME_PATTERNS = tuple((re.compile(pattern, re.I), key) for pattern, key in _NAME_RULES)
_TEXT_PATTERNS = tuple((re.compile(pattern, re.I | re.M), key) for pattern, key in _TEXT_RULES)

TEXT_HEAD_CHARACTERS = 4000


def classify(name: str, text: str = "") -> DocumentRole:
    """Resolve a document's role from its filename, refined by its opening text.

    The text wins when it disagrees: a file named "Exhibit C.pdf" whose first
    page reads COMPLAINT FOR DAMAGES is the pleading, whatever the label on the
    folder tab said.
    """
    # Underscores, hyphens and dots are word characters to \b, so a rule like
    # \bcomplaint\b never fires on "Complaint_Stamm_v_Kin.txt". Separators are
    # normalized to spaces once here rather than complicating every pattern.
    spaced = re.sub(r"[_\-.]+", " ", name)
    from_name: Optional[str] = None
    for pattern, key in _NAME_PATTERNS:
        if pattern.search(spaced) or pattern.search(name):
            from_name = key
            break

    from_text: Optional[str] = None
    if text:
        head = text[:TEXT_HEAD_CHARACTERS]
        for pattern, key in _TEXT_PATTERNS:
            if pattern.search(head):
                from_text = key
                break

    if from_text and from_name:
        # Both spoke: take whichever is more authoritative.
        return min((BY_KEY[from_text], BY_KEY[from_name]), key=lambda role: role.rank)
    chosen = from_text or from_name
    return BY_KEY[chosen] if chosen else UNCLASSIFIED


def rank_of(key: str) -> int:
    return BY_KEY.get(str(key), UNCLASSIFIED).rank


def label_of(key: str) -> str:
    return BY_KEY.get(str(key), UNCLASSIFIED).label


def is_controlling(key: str) -> bool:
    return rank_of(key) <= CONTROLLING_RANK


def defines_claims(key: str) -> bool:
    """Whether this role can define the claimant's pleaded legal theories.

    Responsive pleadings and orders are controlling for reading order, but an
    answer that denies fraud and an order that dismisses bad faith must not
    create those claims in the claimant's posture.
    """
    return str(key) == "operative_pleading"


def is_party_assertion(key: str) -> bool:
    """Whether statements in this role are allegations rather than evidence."""
    return str(key) in {"operative_pleading", "responsive_pleading", "motion"}


# Plain-English names for the roles. The internal labels are for a lawyer or a
# model; a self-represented person needs to know what the document IS.
PLAIN_LABELS = {
    "operative_pleading": "Your main court filing that starts the case",
    "responsive_pleading": "The other side's written answer",
    "order": "Something the judge decided",
    "instrument": "The contract or policy the dispute is about",
    "motion": "A request asking the judge to do something",
    "deposition": "Sworn testimony or a signed statement",
    "expert": "A report or estimate from a professional",
    "discovery": "Requests for information between the parties",
    "correspondence": "Letters and emails",
    "exhibit": "Supporting attachment",
    "unclassified": "Not yet sorted",
}


def plain_label(key: str) -> str:
    return PLAIN_LABELS.get(str(key), PLAIN_LABELS["unclassified"])
