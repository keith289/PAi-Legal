"""Legal Float/Mix/Stir relational-pressure mapping.

Original text is never rewritten. Float observations do not assign a bracket;
status remains an independent canonical lock.
"""
from __future__ import annotations

import collections
import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Iterator

from .epistemic import BracketType, BracketFloat, mix, stir

STATE_RE = re.compile(r"\b(Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming)\b", re.I)
DATE_RE = re.compile(r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},\s+(?:16|17|18|19|20)\d{2}\b", re.I)
# Docket numbers carry no spaces or commas. Allowing them let the match run
# across sentence boundaries and swallow whole paragraphs as one "docket".
DOCKET_RE = re.compile(r"\bNo[s]?\.\s*([A-Za-z0-9][A-Za-z0-9\-–—:/]{1,40})", re.I)
CITE_RE = re.compile(r"\b\d{1,4}\s+(?:U\.S\.|F\.? ?(?:2d|3d|4th|Supp\.? ?(?:2d|3d)?)|S\.? ?Ct\.?|S\.?E\.? ?(?:2d)?|S\.?W\.? ?(?:2d|3d)?|N\.?E\.? ?(?:2d|3d)?|N\.?W\.? ?(?:2d)?|So\.? ?(?:2d|3d)?|P\.? ?(?:2d|3d)?)\s+\d{1,6}\b", re.I)
STATUTE_RE = re.compile(r"\b(?:\d+\s+U\.S\.C\.?\s*§+\s*[\w.\-()]+|[A-Z][A-Za-z. ]{2,30}\s+Code\s*§+\s*[\w.\-()]+|§+\s*[\w.\-()]+)\b")
COURT_RE = re.compile(r"\b(?:Supreme Court|Court of Appeals|Court of Appeal|District Court|Bankruptcy Court|United States Court of Appeals|United States District Court)\b", re.I)
JUDGE_RE = re.compile(r"\b(?:Judge|Justice|Chief Justice|Magistrate Judge)\s+([A-Z][A-Za-z'’\.\-]+(?:\s+[A-Z][A-Za-z'’\.\-]+){0,3})\b")
PARTY_RE = re.compile(r"(?m)^\s*([A-Z][^\n]{2,120}?)\s+v\.?\s+([A-Z][^\n]{2,120}?)(?:\.|,|\n|$)")
AMOUNT_RE = re.compile(
    r"(?:(?:US)?\$\s?|\bUSD\s+)(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)"
    r"|\b(?:sum|amount|total|value)\s+(?:of\s+)?(?:\$\s*)?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
    re.I,
)
MEASURE_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*"
    r"(?:square feet|sq\.?\s*ft\.?|linear feet|sq\.?\s*m|days?|months?|years?|units?|rooms?)\b",
    re.I,
)
WORD_RE = re.compile(r"[A-Za-z0-9§][A-Za-z0-9§'’.\-]*")
STOP = {"the","and","for","that","this","with","from","was","were","are","not","but","had","has","have","its","which","said","upon","such","any","all","who","been","will","would","shall","may","his","her","their","them","there","when","where","under","into","also","than","then","only"}
MIX_PAIRS = {frozenset(pair) for pair in (
    ("STATE", "COURT"), ("STATE", "DATE"), ("COURT", "DATE"),
    ("COURT", "JUDGE"), ("PARTY_A", "PARTY_B"), ("CITATION", "STATUTE"),
    ("DOCKET", "COURT"), ("YEAR", "COURT"), ("YEAR", "STATE"),
    ("AMOUNT", "DATE"), ("AMOUNT", "PARTY_A"), ("AMOUNT", "PARTY_B"),
    ("MEASURE", "DATE"), ("MEASURE", "PARTY_A"), ("MEASURE", "PARTY_B"),
)}
SAME_STIR = {"STATE", "DATE", "YEAR", "COURT", "JUDGE", "CITATION", "STATUTE",
             "PARTY_A", "PARTY_B", "AMOUNT", "MEASURE", "TOKEN"}


@dataclass
class DataPoint:
    kind: str; value: str; count: int = 0; pressure: float = 0.0; notation: str = ""; last_pos: int = -1
    def hit(self, pos: int, weight: float = 1.0) -> None:
        self.count += 1; self.pressure = weight * math.log1p(self.count); self.last_pos = pos


class PointStore:
    def __init__(self, name: str): self.name = name; self.points: dict[tuple[str, str], DataPoint] = {}
    def touch(self, kind: str, value: str, pos: int, weight: float = 1.0, notation: str = "") -> DataPoint:
        point = self.points.setdefault((kind, value), DataPoint(kind, value, notation=notation))
        point.hit(pos, weight)
        if notation: point.notation = notation
        return point
    def __len__(self) -> int: return len(self.points)
    def pressure_sum(self) -> float: return sum(point.pressure for point in self.points.values())
    def top(self, n: int = 20) -> list[DataPoint]: return sorted(self.points.values(), key=lambda point: (point.pressure, point.count), reverse=True)[:n]


@dataclass
class RPMState:
    float: PointStore = field(default_factory=lambda: PointStore("float"))
    mix: PointStore = field(default_factory=lambda: PointStore("mix"))
    stir: PointStore = field(default_factory=lambda: PointStore("stir"))
    pass_number: int = 1
    meta: dict = field(default_factory=dict)
    def total_points(self) -> int: return len(self.float) + len(self.mix) + len(self.stir)
    def total_pressure(self) -> float: return self.float.pressure_sum() + self.mix.pressure_sum() + self.stir.pressure_sum()


def norm(value: str) -> str: return " ".join(value.lower().split())


def float_triggers(text: str, meta: dict) -> Iterator[tuple[str, str, int, float]]:
    for field_name, kind, weight in (("year","YEAR",1.25),("jurisdiction","STATE",1.35),("court","COURT",1.35),("docket","DOCKET",1.15),("decision_date","DATE",1.20),("court_level","COURT_LEVEL",1.10),("reporter","REPORTER",1.05),("source","SOURCE",1.30)):
        value = meta.get(field_name)
        if value is not None and str(value).strip() not in ("", "0", "None"):
            yield kind, str(value).strip(), -1, weight
    for kind, expression, weight in (("STATE",STATE_RE,1.30),("DATE",DATE_RE,1.25),("DOCKET",DOCKET_RE,1.10),("CITATION",CITE_RE,1.35),("STATUTE",STATUTE_RE,1.40),("COURT",COURT_RE,1.25),("JUDGE",JUDGE_RE,1.20)):
        for match in expression.finditer(text):
            captured = match.group(1) if kind in ("JUDGE", "DOCKET") else match.group(0)
            yield kind, captured.strip().rstrip(".,;:"), match.start(), weight
    for match in PARTY_RE.finditer(text[:2500]):
        yield "PARTY_A", match.group(1).strip(), match.start(1), 1.25
        yield "PARTY_B", match.group(2).strip(), match.start(2), 1.25
    for match in AMOUNT_RE.finditer(text):
        value = next((item for item in match.groups() if item), match.group(0))
        yield "AMOUNT", "$" + value.replace(",", ""), match.start(), 1.30
    for match in MEASURE_RE.finditer(text):
        yield "MEASURE", match.group(0).strip(), match.start(), 1.15
    counts = collections.Counter(word.lower() for word in WORD_RE.findall(text) if len(word) > 3 and word.lower() not in STOP)
    for word, count in counts.most_common(128):
        if count >= 2:
            for index in range(min(count, 16)): yield "TOKEN", word, index, 0.55


def _maybe_mix(state: RPMState, a: DataPoint, b: DataPoint, pos: int) -> None:
    if frozenset((a.kind, b.kind)) not in MIX_PAIRS or a.pressure < .65 or b.pressure < .65: return
    left, right = sorted(((a.kind, norm(a.value)), (b.kind, norm(b.value))))
    relation = mix(BracketFloat(a.pressure, lineage=(f"F:{a.kind}:{a.value}",)), BracketFloat(b.pressure, lineage=(f"F:{b.kind}:{b.value}",)))
    state.mix.touch("REL", f"{left[0]}={left[1]}|{right[0]}={right[1]}", pos, min(1.75, float(relation)), "mix")


def _cross_carry(state: RPMState, pos: int) -> None:
    floats = sorted((point for point in state.float.points.values() if point.pressure >= .65), key=lambda point: point.pressure, reverse=True)[:24]
    # Only base relations participate in cross-carry.  Feeding a generated
    # FLOAT_MIX back into FLOAT_STIR (and then back again) created ever-growing
    # strings that looked like depth but were only recursive bookkeeping.  The
    # real intermediate structure is now represented explicitly by the nested
    # transition map, so one pass here is both sufficient and auditable.
    mixes = sorted((point for point in state.mix.points.values()
                    if point.kind == "REL" and point.pressure >= .75),
                   key=lambda point: point.pressure, reverse=True)[:24]
    stirs = sorted((point for point in state.stir.points.values()
                    if point.kind == "RECURRENCE" and point.pressure >= .75),
                   key=lambda point: point.pressure, reverse=True)[:24]
    for floating in floats:
        needle = norm(floating.value)
        if len(needle) < 3: continue
        for mixed in mixes:
            if needle in mixed.value:
                pressure = stir((BracketFloat(floating.pressure, lineage=(f"F:{needle}",)), BracketFloat(mixed.pressure, lineage=(f"M:{mixed.value}",))))
                state.stir.touch("FLOAT_MIX", f"F[{floating.kind}:{needle}]<->M[{mixed.value}]", pos, min(2, float(pressure)), "stir")
        for stirred in stirs:
            # A float carried into its own recurrence is a tautology
            # ("Georgia relates to Georgia repeating") and outranks every real
            # relation, because both legs carry that float's own pressure.
            if stirred.value == f"{floating.kind}={needle}":
                continue
            if needle in stirred.value:
                pressure = mix(BracketFloat(floating.pressure, lineage=(f"F:{needle}",)), BracketFloat(stirred.pressure, lineage=(f"S:{stirred.value}",)))
                state.mix.touch("FLOAT_STIR", f"F[{floating.kind}:{needle}]<->S[{stirred.value}]", pos, min(2, float(pressure)), "mix")


def update(state: RPMState, kind: str, value: str, pos: int, weight: float) -> None:
    point = state.float.touch(kind, value, pos, weight, "float")
    if point.kind in SAME_STIR and point.count >= 2:
        state.stir.touch("RECURRENCE", f"{point.kind}={norm(point.value)}", pos, min(1.75, .5 + point.pressure / 2), "stir")
    for other in list(state.float.points.values()):
        if other is not point: _maybe_mix(state, point, other, pos)
    _cross_carry(state, pos)


def clarity(state: RPMState) -> float:
    nf, nm, ns = len(state.float), len(state.mix), len(state.stir); total = max(1, nf + nm + ns)
    coverage = min(1.0, math.log1p(total) / math.log(81.0)); relation = min(1.0, (nm + ns) / max(1.0, nf * .75))
    pressures = sorted((point.pressure for store in (state.float, state.mix, state.stir) for point in store.points.values()), reverse=True)
    concentration = sum(pressures[:min(12, len(pressures))]) / sum(pressures) if pressures and sum(pressures) else 0.0
    return max(0.0, min(1.0, .45 * coverage + .35 * relation + .20 * concentration))


def process(text: str, meta: dict | None = None, *, min_points: int = 12) -> tuple[RPMState, dict]:
    state = RPMState(meta=dict(meta or {}))
    for kind, value, pos, weight in float_triggers(text, state.meta): update(state, kind, value, pos, weight)
    stale = False
    year = int(state.meta.get("year") or 0)
    if year: stale = __import__("datetime").datetime.now().year - year > 15
    if stale or state.total_points() < min_points:
        state.pass_number = 2
        for kind, value, pos, weight in float_triggers(text, state.meta): update(state, kind, value, pos, weight)
    digest = hashlib.blake2b(digest_size=16)
    for tag, store in (("F", state.float), ("M", state.mix), ("S", state.stir)):
        for point in sorted(store.points.values(), key=lambda item: (item.kind, item.value)):
            digest.update(f"{tag}\0{point.kind}\0{point.value}\0{point.count}\0{point.pressure:.8f}\n".encode("utf-8", "replace"))
    # Pattern clarity never upgrades truth. New case material starts unverified.
    return state, {"bracket": BracketType.UNVERIFIED.name, "clarity": clarity(state), "pass": state.pass_number, "signature": digest.hexdigest(), "stale": stale}


def state_record(state: RPMState, lock: dict, *, source: str, text: str = "") -> dict:
    def top(store: PointStore) -> list[dict]: return [asdict(point) for point in store.top()]
    return {"schema_version": 1, "source": source, "bracket": lock["bracket"], "clarity": round(lock["clarity"], 8),
            "pass": lock["pass"], "pattern_signature": lock["signature"], "float_points": len(state.float),
            "mix_points": len(state.mix), "stir_points": len(state.stir), "total_pressure": round(state.total_pressure(), 8),
            "top_float": top(state.float), "top_mix": top(state.mix), "top_stir": top(state.stir), "text": text}
