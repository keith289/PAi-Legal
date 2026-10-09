"""Canonical Python epistemic Float, Mix, and Stir primitives.

The numeric value, four-position bracket vector, evidence mass, lineage, and
causal clock travel together.  Arithmetic can never promote its own status.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Iterable, Sequence


class BracketType(IntEnum):
    UNVERIFIED = 0
    SPECULATIVE = 1
    EXPLAINED = 2
    VALIDATED = 3


BRACKET_POS = {
    BracketType.UNVERIFIED: (1.0, 0.0, 0.0, 0.0),
    BracketType.SPECULATIVE: (0.0, 1.0, 0.0, 0.0),
    BracketType.EXPLAINED: (0.0, 0.0, 1.0, 0.0),
    BracketType.VALIDATED: (0.0, 0.0, 0.0, 1.0),
}
BRACKET_MARKS = {
    BracketType.UNVERIFIED: ("[{", "}]"),
    BracketType.SPECULATIVE: ("[[", "]]"),
    BracketType.EXPLAINED: ("{[", "]}"),
    BracketType.VALIDATED: ("[[[", "]]]"),
}


def bracket_name(value: BracketType | int | str) -> BracketType:
    if isinstance(value, BracketType):
        return value
    if isinstance(value, int):
        return BracketType(value)
    normalized = str(value).strip().upper()
    compact = normalized.replace(" ", "")
    aliases = {"[{}]": "UNVERIFIED", "[[]]": "SPECULATIVE",
               "{[]}": "EXPLAINED", "[[[]]]": "VALIDATED"}
    return BracketType[aliases.get(compact, normalized.replace(" ", "_"))]


def wrap_claim(text: str, status: BracketType | int | str) -> str:
    opening, closing = BRACKET_MARKS[bracket_name(status)]
    return f"{opening}{text}{closing}"


@dataclass(frozen=True)
class IndexRow:
    key: str
    value: float
    unit: str
    pos: tuple[float, float, float, float]
    mass: float
    lineage: tuple[str, ...]
    tau: int = 0
    caution: str = ""
    contradicted: bool = False
    superseded: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


class BracketFloat(float):
    def __new__(cls, value: float, bracket_type: BracketType = BracketType.UNVERIFIED, *,
                key: str = "", unit: str = "", pos: Sequence[float] | None = None,
                mass: float = 1.0, lineage: Sequence[str] = (), tau: int = 0,
                caution: str = "", contradicted: bool = False,
                superseded: bool = False) -> "BracketFloat":
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("BracketFloat value must be finite")
        obj = float.__new__(cls, numeric)
        obj.bracket_type = BracketType(bracket_type)
        obj.key = str(key); obj.unit = str(unit)
        obj.pos = tuple(float(x) for x in (pos or BRACKET_POS[obj.bracket_type]))
        if len(obj.pos) != 4:
            raise ValueError("pos must contain four components")
        obj.mass = float(mass)
        obj.lineage = tuple(dict.fromkeys(str(x) for x in lineage if str(x)))
        obj.tau = int(tau); obj.caution = str(caution)
        obj.contradicted = bool(contradicted); obj.superseded = bool(superseded)
        return obj

    def row(self, key: str | None = None) -> IndexRow:
        return IndexRow(self.key if key is None else str(key), float(self), self.unit,
                        self.pos, self.mass, self.lineage, self.tau, self.caution,
                        self.contradicted, self.superseded)

    def wrap(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        return wrap_claim(f"{float(self):g}{unit}", self.bracket_type)

    def __repr__(self) -> str:
        return self.wrap()


def _as_float(value: float | BracketFloat) -> BracketFloat:
    # Raw numbers enter as unverified unit-mass inputs.
    return value if isinstance(value, BracketFloat) else BracketFloat(float(value))


def _weighted_pos(values: Sequence[BracketFloat], weights: Sequence[float]) -> tuple[float, ...]:
    total = sum(weights)
    return tuple(sum(value.pos[i] * weight for value, weight in zip(values, weights)) / total for i in range(4))


def _dominant(pos: Sequence[float]) -> BracketType:
    # Ties resolve downward, never upward.
    return BracketType(max(range(4), key=lambda i: (pos[i], -i)))


def mix(left: float | BracketFloat, right: float | BracketFloat, *,
        left_weight: float = 1.0, right_weight: float = 1.0, key: str = "",
        unit: str | None = None, lineage: Sequence[str] = (), caution: str = "") -> BracketFloat:
    a, b = _as_float(left), _as_float(right)
    weights = (float(left_weight), float(right_weight))
    if any(not math.isfinite(weight) or weight < 0 for weight in weights) or sum(weights) <= 0:
        raise ValueError("weights must be finite, nonnegative, and have a positive sum")
    total = sum(weights); pos = _weighted_pos((a, b), weights)
    return BracketFloat((float(a) * weights[0] + float(b) * weights[1]) / total,
        _dominant(pos), key=key, unit=a.unit if unit is None else unit, pos=pos,
        mass=a.mass + b.mass, lineage=tuple(dict.fromkeys((*a.lineage, *b.lineage, *lineage))),
        tau=max(a.tau, b.tau) + 1, caution=caution or a.caution or b.caution,
        contradicted=a.contradicted or b.contradicted, superseded=a.superseded and b.superseded)


def stir(values: Iterable[float | BracketFloat], *, weights: Sequence[float] | None = None,
         key: str = "", unit: str | None = None, lineage: Sequence[str] = (),
         caution: str = "") -> BracketFloat:
    items = tuple(_as_float(value) for value in values)
    if not items:
        raise ValueError("stir requires at least one value")
    ws = tuple(float(weight) for weight in (weights or (1.0,) * len(items)))
    if len(ws) != len(items) or any(not math.isfinite(weight) or weight < 0 for weight in ws) or sum(ws) <= 0:
        raise ValueError("weights must match inputs, be finite and nonnegative, with positive sum")
    total = sum(ws); pos = _weighted_pos(items, ws)
    return BracketFloat(sum(float(value) * weight for value, weight in zip(items, ws)) / total,
        _dominant(pos), key=key, unit=items[0].unit if unit is None else unit, pos=pos,
        mass=sum(value.mass for value in items),
        lineage=tuple(dict.fromkeys((*(source for value in items for source in value.lineage), *lineage))),
        tau=max(value.tau for value in items) + 1,
        caution=caution or next((value.caution for value in items if value.caution), ""),
        contradicted=any(value.contradicted for value in items),
        superseded=all(value.superseded for value in items))
