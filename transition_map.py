"""Deterministic, recursively zoomable legal transition maps.

The map is derived entirely from stored RPM records and attached PSi records.
It does not call an LLM and does not alter source text or Trust Locks.  A map
can be rebuilt byte-for-byte from the same inputs, which makes every projected
path replayable during review.

Semantic zoom is represented as nested ``MapView`` objects.  At the root a
document appears as a transition between observed LFM channels.  Opening that
transition reveals Float, Mix, and Stir.  Opening a layer reveals its points;
opening a relational point reveals the leaf components inside the transition.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .epistemic import BracketType, bracket_name
from .parliament import Channel, compose


BRACKET_RANK = {
    BracketType.UNVERIFIED.name: 0,
    BracketType.SPECULATIVE.name: 1,
    BracketType.EXPLAINED.name: 2,
    BracketType.VALIDATED.name: 3,
}

_MATTER_KINDS = {
    "AMOUNT", "MONEY", "MONEY_BENEFIT", "MONEY_EXTRA", "MEASURE",
    "INJURY", "DAMAGE", "PROPERTY", "QUANTITY",
}
_RELATION_KINDS = {
    "PARTY_A", "PARTY_B", "PERSON", "JUDGE", "COURT", "COURT_LEVEL",
    "STATE", "JURISDICTION", "CITATION", "STATUTE", "REPORTER", "SOURCE",
    "DUTY", "AUTHORITY",
}
_CHRONOLOGY_KINDS = {
    "DATE", "YEAR", "DOCKET", "DEADLINE", "ACT", "PROCEDURE", "EVENT",
}


def _clean(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "..."


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.blake2b(digest_size=8)
    for part in parts:
        digest.update(str(part).encode("utf-8", "replace"))
        digest.update(b"\0")
    return f"{prefix}-{digest.hexdigest()}"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def floor_bracket(values: Iterable[str]) -> str:
    """Return the weakest supplied lock.  Empty input is unverified."""

    names: List[str] = []
    for value in values:
        try:
            names.append(bracket_name(value).name)
        except (KeyError, ValueError):
            names.append(BracketType.UNVERIFIED.name)
    return min(names, key=lambda name: BRACKET_RANK[name]) if names else BracketType.UNVERIFIED.name


def channel_for_kind(kind: str, value: str = "") -> Channel:
    """Assign a legal observation to a channel without using pressure."""

    normalized = str(kind or "").strip().upper()
    if normalized in _MATTER_KINDS or any(token in normalized for token in ("MONEY", "AMOUNT", "MEASURE", "DAMAGE")):
        return Channel.A
    if normalized in _RELATION_KINDS or any(token in normalized for token in ("PARTY", "COURT", "CITE", "STATUTE", "AUTHORITY")):
        return Channel.B
    if normalized in _CHRONOLOGY_KINDS or any(token in normalized for token in ("DATE", "YEAR", "DOCKET", "TIME", "EVENT")):
        return Channel.C
    # Tokens are retained for inspection but do not invent a legal channel.
    return Channel.ZERO


@dataclass(frozen=True)
class MapNode:
    id: str
    label: str
    kind: str
    channel: str = "ZERO"
    anchor: int = 0
    pressure: float = 0.0
    bracket: str = "UNVERIFIED"
    provenance: Tuple[str, ...] = ()
    focus_view: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        value = asdict(self)
        value["provenance"] = list(self.provenance)
        value["metadata"] = dict(self.metadata)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MapNode":
        return cls(
            id=str(value["id"]), label=str(value.get("label") or ""),
            kind=str(value.get("kind") or "point"),
            channel=str(value.get("channel") or "ZERO"),
            anchor=int(value.get("anchor") or 0),
            pressure=float(value.get("pressure") or 0.0),
            bracket=str(value.get("bracket") or "UNVERIFIED"),
            provenance=tuple(str(item) for item in value.get("provenance") or ()),
            focus_view=str(value.get("focus_view") or ""),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MapEdge:
    id: str
    source: str
    target: str
    label: str
    residue: str = "ZERO"
    pressure: float = 0.0
    bracket: str = "UNVERIFIED"
    provenance: Tuple[str, ...] = ()
    focus_view: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        value = asdict(self)
        value["provenance"] = list(self.provenance)
        value["metadata"] = dict(self.metadata)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MapEdge":
        return cls(
            id=str(value["id"]), source=str(value["source"]), target=str(value["target"]),
            label=str(value.get("label") or "transition"),
            residue=str(value.get("residue") or "ZERO"),
            pressure=float(value.get("pressure") or 0.0),
            bracket=str(value.get("bracket") or "UNVERIFIED"),
            provenance=tuple(str(item) for item in value.get("provenance") or ()),
            focus_view=str(value.get("focus_view") or ""),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MapView:
    id: str
    label: str
    parent: str
    nodes: Tuple[MapNode, ...]
    edges: Tuple[MapEdge, ...]
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "parent": self.parent,
            "description": self.description,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MapView":
        return cls(
            id=str(value["id"]), label=str(value.get("label") or ""),
            parent=str(value.get("parent") or ""),
            description=str(value.get("description") or ""),
            nodes=tuple(MapNode.from_dict(item) for item in value.get("nodes") or ()),
            edges=tuple(MapEdge.from_dict(item) for item in value.get("edges") or ()),
        )


@dataclass(frozen=True)
class Projection:
    role: str
    headline: str
    detail: str
    channel: str
    bracket: str
    pressure: float
    provenance: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        value = asdict(self)
        value["provenance"] = list(self.provenance)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Projection":
        return cls(
            role=str(value.get("role") or "Recorder"),
            headline=str(value.get("headline") or ""), detail=str(value.get("detail") or ""),
            channel=str(value.get("channel") or "ZERO"),
            bracket=str(value.get("bracket") or "UNVERIFIED"),
            pressure=float(value.get("pressure") or 0.0),
            provenance=tuple(str(item) for item in value.get("provenance") or ()),
        )


@dataclass(frozen=True)
class CaseTransitionMap:
    schema_version: int
    case_id: str
    case_name: str
    input_signature: str
    replay_signature: str
    deterministic_seed: int
    root_view: str
    views: Mapping[str, MapView]
    projections: Tuple[Projection, ...]

    def view(self, view_id: str | None = None) -> MapView:
        return self.views.get(view_id or self.root_view, self.views[self.root_view])

    def breadcrumbs(self, view_id: str | None = None) -> List[MapView]:
        current = self.view(view_id)
        values = [current]
        seen = {current.id}
        while current.parent and current.parent in self.views and current.parent not in seen:
            current = self.views[current.parent]
            values.append(current)
            seen.add(current.id)
        return list(reversed(values))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "case_id": self.case_id,
            "case_name": self.case_name, "input_signature": self.input_signature,
            "replay_signature": self.replay_signature,
            "deterministic_seed": self.deterministic_seed,
            "root_view": self.root_view,
            "views": {key: value.to_dict() for key, value in sorted(self.views.items())},
            "projections": [item.to_dict() for item in self.projections],
            "guard": "Relational pressure cannot promote a Trust Lock.",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CaseTransitionMap":
        return cls(
            schema_version=int(value.get("schema_version") or 1),
            case_id=str(value.get("case_id") or ""), case_name=str(value.get("case_name") or ""),
            input_signature=str(value.get("input_signature") or ""),
            replay_signature=str(value.get("replay_signature") or ""),
            deterministic_seed=int(value.get("deterministic_seed") or 0),
            root_view=str(value.get("root_view") or "root"),
            views={str(key): MapView.from_dict(item) for key, item in (value.get("views") or {}).items()},
            projections=tuple(Projection.from_dict(item) for item in value.get("projections") or ()),
        )


def input_signature(records: Sequence[Mapping[str, Any]], authorities: Sequence[Mapping[str, Any]] = ()) -> str:
    inputs = {
        "records": [
            {
                "source": item.get("source"), "bracket": item.get("bracket"),
                "pattern_signature": item.get("pattern_signature"),
                "float_points": item.get("float_points"), "mix_points": item.get("mix_points"),
                "stir_points": item.get("stir_points"), "total_pressure": item.get("total_pressure"),
            }
            for item in sorted(records, key=lambda row: str(row.get("source") or ""))
        ],
        "authorities": [
            {
                "id": item.get("source_id") or item.get("id"), "bracket": item.get("bracket"),
                "title": item.get("title"), "citation": item.get("citation"),
                "signature": item.get("pattern_signature"), "pressure": item.get("total_pressure"),
                "float_points": item.get("float_points"), "mix_points": item.get("mix_points"),
                "stir_points": item.get("stir_points"),
            }
            for item in sorted(authorities, key=lambda row: str(row.get("source_id") or row.get("id") or ""))
        ],
    }
    return hashlib.blake2b(_canonical(inputs).encode("utf-8"), digest_size=16).hexdigest()


def _relation_components(value: str) -> List[Tuple[str, str]]:
    leaves: List[Tuple[str, str]] = []
    pattern = re.compile(r"([FMS])\[([A-Z_]+)[:=]([^\[\]]{1,160})\]")
    for notation, kind, inner in pattern.findall(value or ""):
        pair = (kind, _clean(inner, 120))
        if pair not in leaves:
            leaves.append(pair)
    if not leaves:
        for part in re.split(r"<->|\|", value or ""):
            clean = _clean(part, 120)
            if clean:
                match = re.match(r"(?:[FMS]\[)?([A-Z_]+)[:=](.+?)(?:\])?$", clean)
                leaves.append((match.group(1), _clean(match.group(2), 120)) if match else ("RELATION", clean))
    return leaves[:10]


def _dominant_pair(points: Sequence[Mapping[str, Any]]) -> Tuple[Channel, Channel, Dict[str, float]]:
    pressures = {channel.name: 0.0 for channel in (Channel.A, Channel.B, Channel.C)}
    for point in points:
        channel = channel_for_kind(str(point.get("kind") or ""), str(point.get("value") or ""))
        if channel is not Channel.ZERO:
            pressures[channel.name] += max(0.0, float(point.get("pressure") or 0.0))
    ordered = sorted((Channel.A, Channel.B, Channel.C), key=lambda item: (-pressures[item.name], item.anchor))
    observed = [item for item in ordered if pressures[item.name] > 0]
    if len(observed) >= 2:
        return observed[0], observed[1], pressures
    if len(observed) == 1:
        return observed[0], Channel.ZERO, pressures
    return Channel.ZERO, Channel.ZERO, pressures


def _point_view(parent: str, source: str, layer: str, point: Mapping[str, Any], bracket: str) -> Tuple[MapNode, MapView | None]:
    value = _clean(point.get("value"), 220)
    kind = str(point.get("kind") or layer.upper())
    channel = channel_for_kind(kind, value)
    point_id = _stable_id("point", source, layer, kind, value)
    components = _relation_components(value) if layer in {"mix", "stir"} else []
    focus_view = f"view:{point_id}" if len(components) >= 2 else ""
    provenance = (f"{source}@{int(point.get('last_pos') or -1)}",)
    node = MapNode(
        point_id, _clean(value, 90), kind, channel.name, channel.anchor,
        round(float(point.get("pressure") or 0.0), 8), bracket, provenance,
        focus_view, {"count": int(point.get("count") or 0), "notation": layer},
    )
    if not focus_view:
        return node, None

    nodes: List[MapNode] = []
    for index, (component_kind, component_value) in enumerate(components):
        component_channel = channel_for_kind(component_kind, component_value)
        component_id = _stable_id("leaf", point_id, index, component_kind, component_value)
        nodes.append(MapNode(
            component_id, _clean(component_value, 80), component_kind,
            component_channel.name, component_channel.anchor,
            node.pressure / max(1, len(components)), bracket, provenance,
            "", {"leaf": True, "component_index": index},
        ))
    edges: List[MapEdge] = []
    for index in range(len(nodes) - 1):
        left = Channel[nodes[index].channel]
        right = Channel[nodes[index + 1].channel]
        residue = compose(left, right)
        edges.append(MapEdge(
            _stable_id("inner", point_id, index), nodes[index].id, nodes[index + 1].id,
            f"inner transition {index + 1}", residue.name,
            round(node.pressure / max(1, len(nodes) - 1), 8), bracket,
            tuple(dict.fromkeys((*nodes[index].provenance, *nodes[index + 1].provenance))),
            "", {"pressure_status_independent": True},
        ))
    view = MapView(
        focus_view, f"Inside {layer.upper()} transition", parent,
        tuple(nodes), tuple(edges),
        "Leaf relations exposed by semantic zoom. Cancellation retains provenance.",
    )
    return node, view


def build_case_transition_map(
    case_id: str,
    case_name: str,
    records: Sequence[Mapping[str, Any]],
    authorities: Sequence[Mapping[str, Any]] = (),
) -> CaseTransitionMap:
    """Build a deterministic recursive map from stored case indexes."""

    ordered_records = sorted((dict(item) for item in records), key=lambda row: str(row.get("source") or ""))
    ordered_authorities = sorted((dict(item) for item in authorities), key=lambda row: str(row.get("source_id") or row.get("id") or ""))
    signature = input_signature(ordered_records, ordered_authorities)
    seed = int(signature[:16], 16)
    views: Dict[str, MapView] = {}

    anchors = tuple(
        MapNode(f"anchor:{channel.name}", f"k{channel.anchor}  {channel.label}", "anchor",
                channel.name, channel.anchor, 0.0, "UNVERIFIED", (), "",
                {"fixed_anchor": True})
        for channel in (Channel.ZERO, Channel.A, Channel.B, Channel.C)
    )
    root_edges: List[MapEdge] = []
    doc_summaries: List[dict] = []

    for record in ordered_records:
        source = str(record.get("source") or "Document")
        bracket = floor_bracket((str(record.get("bracket") or "UNVERIFIED"),))
        float_items = list(record.get("top_float") or [])[:20]
        left, right, channel_pressures = _dominant_pair(float_items)
        residue = compose(left, right)
        document_view_id = f"view:{_stable_id('document', source, record.get('pattern_signature'))}"
        provenance = (source, str(record.get("pattern_signature") or ""))
        edge = MapEdge(
            _stable_id("transition", source, record.get("pattern_signature")),
            f"anchor:{left.name}", f"anchor:{right.name}", source,
            residue.name, round(float(record.get("total_pressure") or 0.0), 8), bracket,
            provenance, document_view_id,
            {
                "float_points": int(record.get("float_points") or 0),
                "mix_points": int(record.get("mix_points") or 0),
                "stir_points": int(record.get("stir_points") or 0),
                "pattern_signature": str(record.get("pattern_signature") or ""),
                "channel_pressures": channel_pressures,
                "pressure_status_independent": True,
            },
        )
        root_edges.append(edge)

        layer_nodes: List[MapNode] = []
        layer_edges: List[MapEdge] = []
        layer_data = (
            ("float", list(record.get("top_float") or []), "FLOAT observations"),
            ("mix", list(record.get("top_mix") or []), "MIX relations"),
            ("stir", list(record.get("top_stir") or []), "STIR recurrences"),
        )
        for layer, points, label in layer_data:
            layer_view_id = f"view:{_stable_id('layer', source, layer, record.get('pattern_signature'))}"
            pressure = round(sum(float(item.get("pressure") or 0.0) for item in points), 8)
            channel = {"float": left, "mix": right, "stir": residue}[layer]
            layer_node = MapNode(
                _stable_id("layer", source, layer), label, layer.upper(),
                channel.name, channel.anchor, pressure, bracket, provenance,
                layer_view_id, {"point_count": int(record.get(f"{layer}_points") or len(points))},
            )
            layer_nodes.append(layer_node)
            point_nodes: List[MapNode] = []
            point_views: List[MapView] = []
            for point in points[:16]:
                point_node, child = _point_view(layer_view_id, source, layer, point, bracket)
                point_nodes.append(point_node)
                if child:
                    point_views.append(child)
            point_edges: List[MapEdge] = []
            for index in range(len(point_nodes) - 1):
                first, second = point_nodes[index], point_nodes[index + 1]
                point_edges.append(MapEdge(
                    _stable_id("sequence", source, layer, index), first.id, second.id,
                    f"{layer} transition {index + 1}",
                    compose(Channel[first.channel], Channel[second.channel]).name,
                    round((first.pressure + second.pressure) / 2, 8),
                    floor_bracket((first.bracket, second.bracket)),
                    tuple(dict.fromkeys((*first.provenance, *second.provenance))),
                    "", {"deterministic_order": True, "pressure_status_independent": True},
                ))
            views[layer_view_id] = MapView(
                layer_view_id, f"{source} / {label}", document_view_id,
                tuple(point_nodes), tuple(point_edges),
                f"{label} inside the document transition. Double-click a relational point to zoom again.",
            )
            for point_view in point_views:
                views[point_view.id] = point_view

        for index in range(len(layer_nodes) - 1):
            first, second = layer_nodes[index], layer_nodes[index + 1]
            layer_edges.append(MapEdge(
                _stable_id("layer-edge", source, index), first.id, second.id,
                f"{first.kind} -> {second.kind}",
                compose(Channel[first.channel], Channel[second.channel]).name,
                round((first.pressure + second.pressure) / 2, 8), bracket,
                provenance, "", {"pressure_status_independent": True},
            ))
        views[document_view_id] = MapView(
            document_view_id, source, "root", tuple(layer_nodes), tuple(layer_edges),
            "The document transition resolved into Float, Mix, and Stir. Trust Lock is carried unchanged.",
        )
        doc_summaries.append({
            "source": source, "bracket": bracket, "left": left, "right": right,
            "residue": residue, "pressure": edge.pressure,
            "signature": str(record.get("pattern_signature") or ""),
            "channel_pressures": channel_pressures,
        })

    # Attached authorities remain separate records and never silently become
    # case evidence.  They appear as B-channel transitions with their stored
    # locks and source identifiers intact.
    for authority in ordered_authorities:
        source_id = str(authority.get("source_id") or authority.get("id") or "authority")
        title = _clean(authority.get("title") or f"PSi authority {source_id}", 100)
        bracket = floor_bracket((str(authority.get("bracket") or "UNVERIFIED"),))
        pressure = float(authority.get("total_pressure") or 0.0)
        root_edges.append(MapEdge(
            _stable_id("authority", source_id, title), "anchor:B", "anchor:ZERO", title,
            Channel.B.name, round(pressure, 8), bracket,
            (f"PSI:{source_id}", str(authority.get("pattern_signature") or "")), "",
            {"authority": True, "citation": str(authority.get("citation") or ""),
             "pressure_status_independent": True},
        ))

    views["root"] = MapView(
        "root", f"{case_name} / Case transition map", "", anchors, tuple(root_edges),
        "Documents occupy transitions between observed channels. Open a transition to inspect the map inside it.",
    )

    projections: List[Projection] = []
    if doc_summaries:
        strongest = max(doc_summaries, key=lambda item: (item["pressure"], item["source"]))
        weakest = min(doc_summaries, key=lambda item: (item["pressure"], item["source"]))
        absent = min((Channel.A, Channel.B, Channel.C), key=lambda c: sum(item["channel_pressures"][c.name] for item in doc_summaries))
        case_bracket = floor_bracket(item["bracket"] for item in doc_summaries)
        projections.extend((
            Projection("Clerk", "Record traced", f"{len(doc_summaries)} indexed document transition(s) are replayable from stored signatures.", Channel.ZERO.name, case_bracket, 0.0, tuple(item["source"] for item in doc_summaries)),
            Projection("Advocate", "Strongest observed path", f"{strongest['source']} carries the greatest relational pressure. That identifies attention, not truth.", strongest["residue"].name, strongest["bracket"], strongest["pressure"], (strongest["source"], strongest["signature"])),
            Projection("Opposition", "Least represented channel", f"{absent.label} has the least mapped support and is the first structural gap to inspect.", absent.name, case_bracket, weakest["pressure"], (weakest["source"],)),
            Projection("Precedent Judge", "Trust Lock held", "No transition or recurrence promoted a stored epistemic status.", Channel.B.name, case_bracket, sum(item["pressure"] for item in doc_summaries), tuple(item["source"] for item in doc_summaries)),
            Projection("Forecaster", "Next-state residue", f"The strongest mapped cross-pair leaves {strongest['residue'].label} as its unresolved residue.", strongest["residue"].name, strongest["bracket"], strongest["pressure"], (strongest["source"],)),
        ))
    else:
        projections.append(Projection(
            "Recorder", "No indexed transitions", "Ingest and index evidence to construct the first replayable map.",
            Channel.ZERO.name, "UNVERIFIED", 0.0, (),
        ))

    replay_payload = {
        "case_id": case_id, "case_name": case_name, "input_signature": signature,
        "root_view": "root", "views": {key: value.to_dict() for key, value in sorted(views.items())},
        "projections": [item.to_dict() for item in projections],
    }
    replay_signature = hashlib.blake2b(_canonical(replay_payload).encode("utf-8"), digest_size=16).hexdigest()
    projections.append(Projection(
        "Recorder", "Deterministic replay", f"Seed {seed} / replay {replay_signature}.",
        Channel.ZERO.name, floor_bracket(item.bracket for item in projections), 0.0,
        tuple(item["source"] for item in doc_summaries),
    ))
    # Recorder is intentionally added after the signature it describes; its
    # text is derived metadata, not an input into the replay computation.
    return CaseTransitionMap(
        1, case_id, case_name, signature, replay_signature, seed, "root",
        views, tuple(projections),
    )


__all__ = [
    "MapNode", "MapEdge", "MapView", "Projection", "CaseTransitionMap",
    "channel_for_kind", "floor_bracket", "input_signature", "build_case_transition_map",
]
