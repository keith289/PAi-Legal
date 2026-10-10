"""Separate the distinct legal matters inside one case folder.

A person's legal trouble rarely arrives as one lawsuit. An insurance claim gets
denied, then the lawyer hired to fight the denial mishandles it: two matters,
different defendants, different theories, one underlying event. Filed into a
single case folder they look like one dispute, and everything downstream
inherits the confusion - retrieval pulls bad-faith authorities for a
malpractice question, and a drafter hands you a filing that merges two suits.

So matters are detected and kept apart. They are NOT severed into separate
folders: the malpractice matter exists because of the insurance claim, and its
proof lives in the insurance documents. Separate folders could not share that.
Matters are distinct within one case, and the connections between them are
recorded rather than discarded.

Identity comes from the caption first (a "X v. Y" line is the strongest signal
a document belongs to a particular suit), then a docket number, then a claim
number. A document with none of those is unassigned - it belongs to the case
but to no particular matter, which is honest and common for correspondence.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

CAPTION_RE = re.compile(
    r"(?m)^\s*([A-Z][A-Za-z.,'&\- ]{2,70}?)\s+v\.?s?\.?\s+([A-Z][A-Za-z.,'&\- ]{2,70}?)"
    r"(?:\s*[,.]|\s*$)")
# Docket formats vary wildly by court: 24-A-01234-5, 7:26-cv-00075-WLS,
# 2024CV001234. Anything with digits and at least one separator qualifies.
DOCKET_RE = re.compile(r"\b(?:case|civil action|docket)\s*(?:no\.?|number)?\s*[:#]?\s*"
                       r"([0-9][0-9A-Za-z]*(?:[:\-][0-9A-Za-z]+){1,4})", re.I)
# A matter is FILED when a court has taken it in: a clerk-assigned docket, a
# file stamp, a summons, service, or an order. Everything else is BUILDING -
# drafted but not yet before a court. The difference decides whether deadlines
# are running, which is the single most consequential thing a self-represented
# person can be wrong about.
FILED_RE = re.compile(
    r"\b(filed\s+in\s+office|e-?filed|clerk of (the )?(superior|state|district|magistrate) court|"
    r"file\s*stamp|received\s+and\s+filed|summons|sheriff'?s? entry of service|"
    r"proof of service|certificate of service|it is (hereby )?ordered|"
    r"comes? before the court)\b", re.I)
DRAFT_RE = re.compile(r"\b(draft|proposed|unfiled|not yet filed|for review|working copy)\b", re.I)

CLAIM_RE = re.compile(r"\b(?:claim|policy)\s*(?:no\.?|number|#)?\s*[:#]?\s*"
                      r"([A-Z]{1,4}[\-–]?[0-9]{4,12})\b", re.I)

# Words that ride along in a caption but say nothing about who the party is.
_NOISE = re.compile(r"\b(inc|llc|pllc|corp|corporation|company|co|ltd|lp|llp|"
                    r"exchange|interinsurance|nexus|the|and|of)\b", re.I)


def _normalize_party(value: str) -> str:
    cleaned = _NOISE.sub(" ", str(value))
    cleaned = re.sub(r"[^A-Za-z ]+", " ", cleaned)
    words = [word.lower() for word in cleaned.split() if len(word) > 2]
    return " ".join(sorted(set(words)))


def _surnames(value: str) -> Set[str]:
    return {word for word in _normalize_party(value).split() if len(word) > 2}


@dataclass
class MatterSignals:
    """What one document says about which suit it belongs to."""
    source: str
    plaintiff: str = ""
    defendant: str = ""
    docket: str = ""
    claim: str = ""
    filed_marker: str = ""
    draft_marker: str = ""

    @property
    def caption_key(self) -> str:
        if not (self.plaintiff and self.defendant):
            return ""
        return f"{_normalize_party(self.plaintiff)}|{_normalize_party(self.defendant)}"


def read_signals(source: str, text: str) -> MatterSignals:
    """Read matter identity from a document's opening.

    Only the first stretch is used: a caption appears at the top of a filing,
    while a party name mentioned in passing on page nine says nothing about
    which suit the document belongs to.
    """
    head = text[:3000]
    signals = MatterSignals(source=source)
    caption = CAPTION_RE.search(head)
    if caption:
        signals.plaintiff = caption.group(1).strip()
        signals.defendant = caption.group(2).strip()
    docket = DOCKET_RE.search(head)
    if docket:
        signals.docket = docket.group(1).strip()
    claim = CLAIM_RE.search(head)
    if claim:
        signals.claim = claim.group(1).strip().upper()
    filed = FILED_RE.search(head)
    if filed:
        signals.filed_marker = filed.group(0).strip()
    draft = DRAFT_RE.search(source) or DRAFT_RE.search(head)
    if draft:
        signals.draft_marker = draft.group(0).strip()
    return signals


@dataclass
class Matter:
    matter_id: str
    label: str
    plaintiff: str = ""
    defendant: str = ""
    dockets: Set[str] = field(default_factory=set)
    claims: Set[str] = field(default_factory=set)
    sources: List[str] = field(default_factory=list)
    filed_evidence: List[str] = field(default_factory=list)
    draft_evidence: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """FILED once a court has taken it in; BUILDING until then.

        A docket number is the strongest signal - clerks assign them, parties
        do not. A draft marker never overrides one, because a file-stamped
        complaint sitting in a folder named "draft" is still filed.
        """
        if self.dockets or self.filed_evidence:
            return "filed"
        return "building"

    @property
    def status_label(self) -> str:
        return ("Filed — this case is before a court"
                if self.status == "filed"
                else "Not filed yet — you are still building this one")

    @property
    def status_detail(self) -> str:
        if self.status == "filed":
            reason = (f"docket {sorted(self.dockets)[0]}" if self.dockets
                      else f"court record found ({self.filed_evidence[0]})")
            return (f"A court record appears to show this was filed ({reason}). "
                    "Filing-related deadlines may be running. Verify the live docket, "
                    "service status, local rules, and every due date.")
        return ("Nothing in these documents shows a court has taken this in - no docket "
                "number, no file stamp, no service. Do not assume that means no deadline "
                "is running: limitation, notice, preservation, or pre-suit time limits "
                "may still apply. Verify them independently.")

    def as_dict(self) -> dict:
        return {
            "matter_id": self.matter_id,
            "label": self.label,
            "status": self.status,
            "status_label": self.status_label,
            "status_detail": self.status_detail,
            "filed_evidence": list(dict.fromkeys(self.filed_evidence))[:4],
            "plaintiff": self.plaintiff,
            "defendant": self.defendant,
            "dockets": sorted(self.dockets),
            "claims": sorted(self.claims),
            "documents": list(self.sources),
            "document_count": len(self.sources),
        }


def _label(plaintiff: str, defendant: str) -> str:
    """Name a matter the way its parties would: surname v. entity.

    "ELIZABETH STAMM and KEITH LUTON" is Stamm - the surname, not the given
    name - and a defendant needs enough words to be recognizable, since the
    first one is often generic ("Your Insurance Attorney").
    """
    drop = {"the", "and", "of", "inc", "inc.", "llc", "pllc", "corp", "corporation",
            "company", "co", "ltd", "lp", "llp"}

    def first_party(value: str) -> str:
        return re.split(r"\s+and\s+|\s*,\s*", str(value).strip(), maxsplit=1)[0]

    def words_of(value: str) -> List[str]:
        return [w for w in re.split(r"[\s,.]+", first_party(value))
                if w and w.lower() not in drop]

    left_words = words_of(plaintiff)
    # A natural person's surname is the last word; an entity's name is not.
    left = left_words[-1].title() if left_words else ""
    right_words = words_of(defendant)
    right = " ".join(word.title() for word in right_words[:3])
    return f"{left} v. {right}" if left and right else (left or right or "Unassigned")


def detect_matters(documents: Iterable[Tuple[str, str]]) -> dict:
    """Group documents into matters and record how the matters connect.

    ``documents`` is (source, text) pairs.
    """
    signals = [read_signals(source, text) for source, text in documents]

    # A caption defines a matter. Everything else is attached to one.
    by_caption: Dict[str, Matter] = {}
    order = 0
    for signal in signals:
        key = signal.caption_key
        if not key:
            continue
        if key not in by_caption:
            order += 1
            by_caption[key] = Matter(
                matter_id=f"MATTER-{order:02d}",
                label=_label(signal.plaintiff, signal.defendant),
                plaintiff=signal.plaintiff,
                defendant=signal.defendant,
            )
        matter = by_caption[key]
        if signal.docket:
            matter.dockets.add(signal.docket)
        if signal.claim:
            matter.claims.add(signal.claim)
        if signal.filed_marker:
            matter.filed_evidence.append(f"{signal.source}: {signal.filed_marker}")
        if signal.draft_marker:
            matter.draft_evidence.append(f"{signal.source}: {signal.draft_marker}")

    # An identifier only assigns when it points at exactly one matter. Both
    # complaints here cite the same claim number - the malpractice suit is
    # ABOUT that claim - so using it to assign would sweep the policy and the
    # denial letter into the malpractice matter.
    def unambiguous(getter) -> Dict[str, Matter]:
        counts: Counter = Counter()
        for matter in by_caption.values():
            for value in getter(matter):
                counts[value] += 1
        return {value: matter for matter in by_caption.values()
                for value in getter(matter) if counts[value] == 1}

    docket_index = unambiguous(lambda matter: matter.dockets)
    claim_index = unambiguous(lambda matter: matter.claims)
    surname_index: List[Tuple[Set[str], Matter]] = [
        (_surnames(matter.plaintiff) | _surnames(matter.defendant), matter)
        for matter in by_caption.values()
    ]

    matters_in_order = sorted(by_caption.values(), key=lambda item: item.matter_id)
    assignment: Dict[str, str] = {}
    unassigned: List[str] = []
    inferred: List[dict] = []
    for signal in signals:
        matter: Optional[Matter] = None
        if signal.caption_key:
            matter = by_caption.get(signal.caption_key)
        if matter is None and signal.docket:
            matter = docket_index.get(signal.docket)
        if matter is None and signal.claim:
            matter = claim_index.get(signal.claim)
        if matter is None and signal.claim:
            # An ambiguous claim number still narrows: where a later matter is
            # ABOUT an earlier one, the shared identifier originates with the
            # earlier. A policy and a denial letter citing the claim are the
            # insurer's evidence, even though the malpractice suit names the
            # same number. Attribute to the first matter that claimed it, and
            # record that the attribution was inferred.
            owners = [candidate for candidate in matters_in_order
                      if signal.claim in candidate.claims]
            if owners:
                matter = owners[0]
                inferred.append({"source": signal.source, "matter": matter.matter_id,
                                 "why": f"cites claim {signal.claim}, first raised by this matter"})
        if matter is None:
            # No caption, docket or claim number. Leave it unassigned rather
            # than guessing - a letter that names both parties is exactly the
            # document most likely to belong to either suit.
            unassigned.append(signal.source)
            continue
        matter.sources.append(signal.source)
        if signal.filed_marker and not signal.caption_key:
            matter.filed_evidence.append(f"{signal.source}: {signal.filed_marker}")
        assignment[signal.source] = matter.matter_id

    matters = sorted(by_caption.values(), key=lambda item: item.matter_id)
    return {
        "matters": [matter.as_dict() for matter in matters],
        "assignment": assignment,
        "unassigned": unassigned,
        "inferred": inferred,
        "connections": _connections(matters),
        "note": ("Matters are kept distinct but not severed: a related suit often "
                 "depends on the first one's evidence."),
    }


def _connections(matters: List[Matter]) -> List[dict]:
    """Record why two matters are related, so the link is inspectable."""
    links: List[dict] = []
    for index, left in enumerate(matters):
        for right in matters[index + 1:]:
            reasons: List[str] = []
            shared_claim = left.claims & right.claims
            if shared_claim:
                reasons.append(f"same claim number ({', '.join(sorted(shared_claim))})")
            shared_party = ((_surnames(left.plaintiff) | _surnames(left.defendant)) &
                            (_surnames(right.plaintiff) | _surnames(right.defendant)))
            if shared_party:
                reasons.append(f"shared party ({', '.join(sorted(shared_party))})")
            if reasons:
                links.append({
                    "from": left.matter_id,
                    "to": right.matter_id,
                    "why": "; ".join(reasons),
                })
    return links
