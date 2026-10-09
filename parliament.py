"""Klein-channel primitives used by PAi Legal's case parliament.

The parliament is not a vote between model personas.  It applies the V4
closure rule to three legal transition channels:

* A / k66  - matter: amounts, measurements, injury, or physical extent
* B / k90  - relation: parties, duties, courts, authorities, or obligations
* C / k120 - chronology: acts, dates, sequence, or procedural position

Like pairs cancel to the baseline.  Cross pairs leave the excluded channel as
their residue.  Magnitude, provenance, and epistemic status remain separate.
"""
from __future__ import annotations

from enum import Enum


class Channel(Enum):
    """Klein four-group V4 under XOR on a two-bit encoding."""

    ZERO = 0b00
    A = 0b01
    B = 0b10
    C = 0b11

    @property
    def anchor(self) -> int:
        return {
            Channel.ZERO: 0,
            Channel.A: 66,
            Channel.B: 90,
            Channel.C: 120,
        }[self]

    @property
    def label(self) -> str:
        return {
            Channel.ZERO: "unresolved baseline",
            Channel.A: "matter / measurable consequence",
            Channel.B: "relation / duty / authority",
            Channel.C: "chronology / act / procedure",
        }[self]


def compose(left: Channel, right: Channel) -> Channel:
    """Return the V4 residue.  This is XOR, never ordinary addition."""

    return Channel(left.value ^ right.value)


def verify_klein_closure() -> bool:
    if compose(Channel.A, Channel.B) is not Channel.C:
        return False
    if compose(Channel.A, Channel.C) is not Channel.B:
        return False
    if compose(Channel.B, Channel.C) is not Channel.A:
        return False
    for channel in Channel:
        if compose(channel, channel) is not Channel.ZERO:
            return False
        if compose(channel, Channel.ZERO) is not channel:
            return False
    return True


__all__ = ["Channel", "compose", "verify_klein_closure"]


# ---------------------------------------------------------------------------
# Legal theories folded across the three channels.
#
# The channels above are the primitives; a legal theory is the host they are
# assigned within. Its elements sit on the channels - a contract existed (B),
# it was not performed on a date (C), causing loss (A) - so folding two
# supported channels names the third. Where the algebra's prediction is not in
# the record, that gap is the finding.
#
# Nothing here calls a model. Findings are identical with or without private AI
# installed; the model, when present, only phrases them.
# ---------------------------------------------------------------------------
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Element:
    """One element of a legal theory, sitting on one channel.

    ``kinds`` restricts which observations may support the element. Two
    theories can share a channel and still demand different content: the loss
    on a contract claim is the policy benefit, while bad faith requires harm
    the insurer's own conduct caused ON TOP of that benefit. Paying the
    estimate late is a breach; it is not extracontractual damage.
    """
    key: str
    label: str
    channel: Channel
    patterns: Tuple[str, ...]
    # What the user is told when the record does not support this element.
    missing_prompt: str
    kinds: Tuple[str, ...] = ()

    def accepts(self, observation: "Observation") -> bool:
        return not self.kinds or observation.kind in self.kinds


@dataclass(frozen=True)
class Theory:
    key: str
    label: str
    elements: Tuple[Element, ...]
    patterns: Tuple[str, ...]

    def element_on(self, channel: Channel) -> Optional[Element]:
        for element in self.elements:
            if element.channel is channel:
                return element
        return None


def _element(key, label, channel, patterns, missing_prompt, kinds=()) -> Element:
    return Element(key, label, channel, tuple(patterns), missing_prompt, tuple(kinds))


# An amount only counts as extracontractual when the line it sits on says so.
# Anything ambiguous is treated as policy benefit, which is the conservative
# reading: it can never manufacture support for a bad-faith claim.
EXTRACONTRACTUAL_RE = re.compile(
    r"\b(attorney'?s?\s+fees?|counsel fees?|litigation costs?|punitive|exemplary|"
    r"treble|statutory (penalty|damages|interest)|bad[- ]faith damages?|"
    r"emotional distress|mental anguish|aggravation|inconvenience|humiliation|"
    r"consequential|incidental damages?|loss of use beyond|additional living expenses? beyond|"
    r"credit (damage|harm)|prejudgment interest|extracontractual)\b", re.I)
BENEFIT_RE = re.compile(
    r"\b(estimate|repair|replacement|remediation|scope of (loss|work)|invoice|"
    r"actual cash value|acv\b|rcv\b|covered loss|policy limit|deductible)\b", re.I)

MALICE_RE = re.compile(
    r"\b(knowing\w*|intentional\w*|willful\w*|wilful\w*|reckless\w*|malic\w*|"
    r"deliberate\w*|bad faith|without (any )?reasonable basis|fraudulent\w*|"
    r"concealed|misrepresent\w*)\b", re.I)
MALICE_PATTERN = MALICE_RE.pattern

# Keyword presence is not support when the clause denies the proposition.
# Keep this deliberately conservative: uncertainty or an express denial leaves
# the element open for human review instead of letting a regex close it.
NEGATION_RE = re.compile(
    r"\b(no|not|never|neither|without|"
    r"dismiss(?:ed|es|al)?|insufficient|unproven|unsupported|fails? to establish|"
    r"no evidence|no proof|zero)\b",
    re.I,
)


def pattern_is_affirmed(text: str, patterns: Sequence[str]) -> bool:
    """Return true only for a pattern in a clause that does not negate it."""
    value = str(text or "")
    for pattern in patterns:
        for match in re.finditer(pattern, value, re.I):
            start = max(0, value.rfind("\n", 0, match.start()) + 1)
            for separator in ".;:":
                start = max(start, value.rfind(separator, 0, match.start()) + 1)
            ends = [position for separator in ".;:\n"
                    if (position := value.find(separator, match.end())) >= 0]
            end = min(ends) if ends else len(value)
            clause = value[start:end]
            # "not only" is an intensifier, not a denial.
            clause = re.sub(r"\bnot\s+only\b", "", clause, flags=re.I)
            relative = max(0, match.start() - start)
            prefix = clause[:relative]
            denial_of_match = re.search(
                r"\b(?:den(?:y|ies|ied)|disput(?:e|es|ed))\b(?:\s+that)?[^.;:\n]{0,32}$",
                prefix, re.I)
            if not NEGATION_RE.search(clause) and not denial_of_match:
                return True
    return False


def classify_amount(line: str) -> str:
    """Type an amount by the line it appears on."""
    if EXTRACONTRACTUAL_RE.search(line):
        return "MONEY_EXTRA"
    if BENEFIT_RE.search(line):
        return "MONEY_BENEFIT"
    return "MONEY_BENEFIT"


# Civil / insurance theories. Every theory carries the same shape: a relation
# that created the obligation (B), an act or failure located in time (C), and
# a loss (A). Extending to other practice areas means adding entries here, not
# changing the algebra.
THEORIES: Tuple[Theory, ...] = (
    Theory(
        "breach_of_contract", "Breach of contract",
        (
            _element("duty", "A contract or policy bound the parties", Channel.B,
                     (r"\b(policy|contract|agreement|insur\w+|premium|coverage|endorsement)\b",),
                     "No document in the record establishes the contract or policy that was breached."),
            _element("breach", "Performance failed, on a date", Channel.C,
                     (r"\b(fail\w*|refus\w*|den\w*|breach\w*|did not (pay|perform|repair)|non-?payment)\b",),
                     "The record does not fix a date on which performance failed."),
            _element("damages", "The failure caused a measurable loss", Channel.A,
                     (r"\b(damage\w*|loss|cost|repair|replace\w*|estimate|invoice|out of pocket)\b",),
                     "No amount in the record quantifies the loss caused by the breach.",
                     ("MONEY_BENEFIT", "MONEY_EXTRA", "MEASURE")),
        ),
        (r"\bbreach of (the )?(contract|policy|agreement)\b", r"\bbreach\b.{0,40}\bcontract\b"),
    ),
    Theory(
        "bad_faith", "Bad faith / unfair claims practice",
        (
            _element("duty", "An insurer owed a duty of good faith", Channel.B,
                     (r"\b(insur\w+|carrier|adjuster|claim\s*no|policy)\b",),
                     "The record does not establish the insurer relationship the duty arises from."),
            _element("conduct", "Knowing or reckless denial, delay or failure to investigate", Channel.C,
                     (MALICE_PATTERN,),
                     "The record shows no knowing, reckless or malicious conduct - only that "
                     "the claim was handled. Delay alone is a breach, not bad faith."),
            _element("harm", "Harm beyond the policy benefit", Channel.A,
                     (r"\b(attorney|fees|interest|punitive|distress|anguish|consequential|extracontractual)\b",),
                     "Every amount in the record is the policy benefit itself. Bad faith needs "
                     "harm the carrier's conduct caused ON TOP of what the policy owed - fees, "
                     "interest, consequential loss. Paying the estimate late is a breach, not bad faith.",
                     ("MONEY_EXTRA",)),
        ),
        (r"\bbad faith\b", r"\bunfair claims?\b", r"\bfailure to (settle|investigate)\b"),
    ),
    Theory(
        "negligence", "Negligence",
        (
            _element("duty", "A duty of care ran to the plaintiff", Channel.B,
                     (r"\b(duty|owed|standard of care|reasonable care|responsib\w+)\b",),
                     "The record does not establish the relationship creating a duty of care."),
            _element("breach", "That duty was breached, on a date", Channel.C,
                     (r"\b(negligen\w*|fail\w* to|breach\w*|careless\w*|should have)\b",),
                     "The record does not fix when the negligent act or omission occurred."),
            _element("damages", "The breach caused measurable injury", Channel.A,
                     (r"\b(injur\w*|damage\w*|loss|cost|medical|repair)\b",),
                     "No amount in the record quantifies the injury."),
        ),
        (r"\bnegligen\w*\b",),
    ),
    Theory(
        "legal_malpractice", "Legal malpractice",
        (
            _element("duty", "An attorney-client relationship existed", Channel.B,
                     (r"\b(attorney|counsel|represent\w+|retainer|engagement|law firm|pllc)\b",),
                     "The record does not establish the attorney-client relationship."),
            _element("breach", "Counsel failed below the standard, on a date", Channel.C,
                     (r"\b(missed|deadline|statute of limitations|fail\w* to file|withdrew|abandon\w*|malpractice)\b",),
                     "The record does not fix when counsel's failure occurred."),
            _element("damages", "The failure cost the client a measurable amount", Channel.A,
                     (r"\b(lost|forfeit\w*|damage\w*|value of the claim|settlement|recovery)\b",),
                     "No amount in the record quantifies what the failure cost."),
        ),
        (r"\blegal malpractice\b", r"\bprofessional negligence\b"),
    ),
    Theory(
        "fraud", "Fraud or misrepresentation",
        (
            _element("duty", "A representation was made by a party", Channel.B,
                     (r"\b(represent\w+|stated|told|assur\w+|promis\w+|warrant\w+)\b",),
                     "The record does not identify who made the representation."),
            _element("falsity", "The representation was false when made", Channel.C,
                     (r"\b(false|misrepresent\w+|conceal\w+|omit\w+|knew|misle\w+)\b",),
                     "The record does not fix when the false representation was made."),
            _element("damages", "Reliance caused a measurable loss", Channel.A,
                     (r"\b(reli\w+|damage\w*|loss|paid|cost)\b",),
                     "No amount in the record quantifies the loss from reliance."),
        ),
        (r"\bfraud\w*\b", r"\bmisrepresentat\w+\b"),
    ),
)

THEORY_BY_KEY = {theory.key: theory for theory in THEORIES}

# --- Channel A extraction -----------------------------------------------
# The matter channel had no extractor: rpm_legal reads dates, parties, courts
# and citations, but nothing that carries an amount. Without it the A channel
# is empty and no theory can fold.

MONEY_RE = re.compile(
    r"(?:(?:US)?\$\s?|\bUSD\s)(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)"
    r"|\b(\d{1,3}(?:,\d{3})+(?:\.\d{2})?)\s*(?:dollars|USD)\b"
    r"|\b(?:sum|amount|total|value)\s+of\s+(?:\$\s?)?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
    re.I,
)
WRITTEN_MONEY_RE = re.compile(
    r"\b((?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|FIFTEEN|TWENTY|THIRTY|"
    r"FORTY|FIFTY|SIXTY|SEVENTY|EIGHTY|NINETY|HUNDRED|THOUSAND|MILLION)[\sA-Z-]{0,60}?"
    r"(?:THOUSAND|MILLION|HUNDRED)(?:\s+(?:AND\s+)?[A-Z\s-]{0,40}?)?)\s+DOLLARS\b"
)
MEASURE_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(square feet|sq\.?\s?ft\.?|linear feet|sq\.?\s?m|units?|rooms?|days?|months?|years?|"
    r"spores? per cubic meter|cubic meters?)\b",
    re.I,
)


def _to_amount(text: str) -> Optional[float]:
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


@dataclass
class Observation:
    """One channel-tagged observation, bound to where it came from."""
    channel: Channel
    kind: str
    value: str
    source: str
    line: int
    amount: Optional[float] = None
    text: str = ""

    def cite(self) -> str:
        return f"{self.source}:{self.line}"


def extract_matter(text: str, source: str, line: int) -> List[Observation]:
    """Pull amounts and measures - the A channel."""
    found: List[Observation] = []
    for match in MONEY_RE.finditer(text):
        raw = next((group for group in match.groups() if group), None)
        if raw is None:
            continue
        amount = _to_amount(raw)
        if amount is None or amount <= 0 or not pattern_is_affirmed(text, (re.escape(match.group(0)),)):
            continue
        found.append(Observation(Channel.A, classify_amount(text), match.group(0).strip(),
                                 source, line, amount, text))
    for match in WRITTEN_MONEY_RE.finditer(text):
        if pattern_is_affirmed(text, (re.escape(match.group(0)),)):
            found.append(Observation(Channel.A, classify_amount(text), match.group(1).strip().title(),
                                     source, line, None, text))
    for match in MEASURE_RE.finditer(text):
        amount = _to_amount(match.group(1))
        if amount is None or amount <= 0 or not pattern_is_affirmed(text, (re.escape(match.group(0)),)):
            continue
        found.append(Observation(Channel.A, "MEASURE", match.group(0).strip(),
                                 source, line, amount, text))
    return found


# A denial is an event; a pattern of them across distinct dates is how knowing
# conduct gets proved, since nobody writes "we denied in bad faith". The
# pattern is EVIDENCE TOWARD the conduct element and never satisfies it -
# recurrence past k=120 carries no resolvable local information, so it cannot
# promote a status on its own.
BREACH_EVENT_RE = re.compile(
    r"\b(deni\w+|refus\w+|reject\w+|declin\w+|underpa\w+|short[- ]?pa\w+|"
    r"clos\w+ the claim|withdrew|non-?renew\w+|fail\w+ to (pay|respond|investigate))\b", re.I)

PATTERN_MINIMUM = 3


@dataclass
class PatternSignal:
    """Circumstantial support from repetition. Supports; never satisfies."""
    events: int
    dates: Tuple[str, ...]
    citations: Tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        return self.events >= PATTERN_MINIMUM

    def narrative(self) -> str:
        if not self.sufficient:
            return ""
        span = ""
        if len(self.dates) >= 2:
            span = f" between {self.dates[0]} and {self.dates[-1]}"
        return (f"{self.events} separate adverse claim events{span}. A pattern this "
                f"dense is how knowing conduct is usually proved, but nothing in the "
                f"record states it directly - the strongest thing here is the timeline. "
                f"Circumstantial only; it does not establish the element.")


def detect_pattern(lines: Sequence[Tuple[str, str, int]]) -> PatternSignal:
    """Count distinct adverse events on the chronology channel.

    Distinct means a different document or a different date - five mentions of
    one denial is one denial.
    """
    seen: Dict[str, Tuple[str, int]] = {}
    dates: List[str] = []
    for text, source, line in lines:
        if not BREACH_EVENT_RE.search(text):
            continue
        found = DATE_IN_LINE_RE.search(text)
        key = found.group(0) if found else source
        if key not in seen:
            seen[key] = (source, line)
            if found:
                dates.append(found.group(0))
    citations = tuple(f"{source}:{line}" for source, line in seen.values())
    return PatternSignal(len(seen), tuple(dates), citations)


DATE_IN_LINE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},\s+\d{4}\b",
    re.I)


def detect_theories(text: str) -> List[Theory]:
    """Find the legal theories a pleading actually asserts."""
    found: List[Theory] = []
    for theory in THEORIES:
        if pattern_is_affirmed(text, theory.patterns):
            found.append(theory)
    return found


@dataclass
class ChannelSupport:
    """What the record offers on one channel for one theory.

    Assertions and support are kept apart on purpose. The operative pleading
    ASSERTS elements; it cannot support them. A complaint alleging a breach is
    not evidence of the breach, and a theory standing only on its own pleading
    is the exact weakness this tool exists to surface.
    """
    channel: Channel
    element: Element
    observations: List[Observation] = field(default_factory=list)
    assertions: List[Observation] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return bool(self.observations)

    @property
    def asserted_only(self) -> bool:
        return bool(self.assertions) and not self.observations

    def citations(self, limit: int = 4) -> List[str]:
        seen: List[str] = []
        for observation in self.observations:
            cite = observation.cite()
            if cite not in seen:
                seen.append(cite)
            if len(seen) >= limit:
                break
        return seen

    def assertion_citations(self, limit: int = 3) -> List[str]:
        seen: List[str] = []
        for observation in self.assertions:
            cite = observation.cite()
            if cite not in seen:
                seen.append(cite)
            if len(seen) >= limit:
                break
        return seen


@dataclass
class Finding:
    theory: Theory
    supports: Dict[Channel, ChannelSupport]
    folded: Tuple[Channel, ...]
    predicted: Channel
    resolved: bool
    headline: str
    detail: str
    pressure: float = 0.0
    pattern: Optional["PatternSignal"] = None

    @property
    def held_out_element(self) -> Optional[Element]:
        return self.theory.element_on(self.predicted)


def _fold(supported: Sequence[Channel]) -> Tuple[Tuple[Channel, ...], Channel]:
    """Fold the supported cross-pair; the excluded channel carries the residue."""
    distinct = [channel for channel in (Channel.A, Channel.B, Channel.C) if channel in supported]
    if len(distinct) < 2:
        return tuple(distinct), Channel.ZERO
    left, right = distinct[0], distinct[1]
    return (left, right), compose(left, right)


def resolve_theory(theory: Theory, supports: Dict[Channel, ChannelSupport],
                   pressure: float = 0.0, pattern: Optional[PatternSignal] = None) -> Finding:
    """Fold two supported channels and test the algebra's prediction.

    The held-out channel is what the other two determine. If the record also
    supports it, the theory closes. If it does not, the gap is named - and the
    gap is the finding, because it is the element that has to be proved and
    currently is not.
    """
    supported = [channel for channel, support in supports.items() if support.supported]
    folded, predicted = _fold(supported)
    pattern_note = ""
    if pattern is not None and pattern.sufficient:
        unmet = supports.get(Channel.C)
        if unmet is not None and not unmet.supported:
            pattern_note = " " + pattern.narrative()

    if len(supported) == 0:
        return Finding(theory, supports, (), Channel.ZERO, False,
                       f"{theory.label}: nothing in the record supports this theory.",
                       "No element of this theory is supported by any document in the case." + pattern_note,
                       pressure, pattern)
    if len(supported) == 1:
        only = supported[0]
        missing = [theory.element_on(channel) for channel in (Channel.A, Channel.B, Channel.C)
                   if channel is not only]
        return Finding(theory, supports, tuple(supported), Channel.ZERO, False,
                       f"{theory.label}: only one element is supported - the theory cannot close.",
                       " ".join(element.missing_prompt for element in missing if element) + pattern_note,
                       pressure, pattern)

    predicted_support = supports.get(predicted)
    resolved = bool(predicted_support and predicted_support.supported)
    element = theory.element_on(predicted)
    folded_names = " + ".join(channel.label for channel in folded)

    if resolved:
        detail = (f"{folded_names} are both in the record, which fixes "
                  f"{predicted.label}. The record independently supports it at "
                  f"{', '.join(predicted_support.citations())}.")
        headline = f"{theory.label}: all three elements are supported."
    else:
        pleaded = ""
        if predicted_support is not None and predicted_support.asserted_only:
            pleaded = (" It is pleaded at "
                       f"{', '.join(predicted_support.assertion_citations())}, but a pleading "
                       "asserts an element - it cannot support it.")
        detail = (f"{folded_names} are in the record, which fixes {predicted.label} - "
                  f"but no supporting document establishes it.{pleaded} "
                  f"{element.missing_prompt if element else ''}")
        headline = f"{theory.label}: {element.label if element else predicted.label} is unsupported."

    return Finding(theory, supports, folded, predicted, resolved,
                   headline, detail + pattern_note, pressure, pattern)
