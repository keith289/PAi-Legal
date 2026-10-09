"""Read-only PAi Claims -> PAi Legal Parliament handoff.

PAi Legal never rewrites the Claims case graph. The Claims graph remains the
base Parliament record in the user-owned shared workspace. Legal creates a
small overlay under the workspace's `pai_legal` folder and a separate legal
extension graph. A source-traced JSONL projection lets the existing Legal
Parliament consume Claims atomic nodes without flattening their bracket,
provenance, relationships, or promotion history.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

MANIFEST_NAME = "pai_case_manifest.json"
CLAIM_NAME = "claim.json"
GRAPH_NAME = "case_graph.json"
REGISTRY_NAME = "linked_claims.json"
EXTENSIONS_NAME = "legal_graph_extensions.json"
PROJECTION_NAME = "claims_parliament_projection.jsonl"
MIN_CLAIMS_HANDOFF_VERSION = (1, 3, 2)

LEGAL_OVERLAY_FOLDERS = (
    "00_inbox", "01_originals", "02_text", "court_papers", "depositions",
    "correspondence", "exhibits", "discovery", "04_index", "05_trace",
    "reasoning_corpus", "notes", "research", "audit", "exports",
)

_BRACKET_MARKS = {
    "UNVERIFIED": ("[{", "}]"),
    "SPECULATIVE": ("[[", "]]"),
    "EXPLAINED": ("{[", "]}"),
    "VALIDATED": ("[[[", "]]]"),
    "CONTRADICTED": ("[!", "!@]"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def _atomic_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_case_id(workspace_id: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", workspace_id or "")[:12].upper()
    return f"CASE-CLAIMS-{compact or uuid.uuid4().hex[:12].upper()}"


def _wrap(statement: str, bracket: str) -> str:
    opening, closing = _BRACKET_MARKS.get(str(bracket).upper(), _BRACKET_MARKS["UNVERIFIED"])
    return f"{opening}{statement}{closing}"


def _last_non_contradicted(node: dict) -> str:
    bracket = str(node.get("bracket") or "UNVERIFIED").upper()
    if bracket != "CONTRADICTED":
        return bracket if bracket in _BRACKET_MARKS else "UNVERIFIED"
    history = node.get("history") or []
    for event in reversed(history):
        candidate = str(event.get("fromBracket") or event.get("toBracket") or "").upper()
        if candidate in {"UNVERIFIED", "SPECULATIVE", "EXPLAINED", "VALIDATED"}:
            return candidate
    return "UNVERIFIED"


def _version_tuple(value: object) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts[:4]) if parts else ()


def validate_claims_workspace(shared_root: Path) -> tuple[dict, dict, dict]:
    root = Path(shared_root).expanduser().resolve()
    manifest_path = root / MANIFEST_NAME
    graph_path = root / GRAPH_NAME
    claim_path = root / CLAIM_NAME
    if not manifest_path.is_file():
        raise ValueError(f"This folder is not a PAi Claims shared workspace: {MANIFEST_NAME} is missing.")
    if not graph_path.is_file():
        raise ValueError(f"This PAi Claims workspace is missing {GRAPH_NAME}.")
    if not claim_path.is_file():
        raise ValueError(f"This PAi Claims workspace is missing {CLAIM_NAME}.")
    manifest = _json(manifest_path, {}) or {}
    if manifest.get("schema") != "pai.shared-case-workspace":
        raise ValueError("The selected folder does not use the PAi shared-case workspace schema.")
    graph = _json(graph_path, {}) or {}
    claim = _json(claim_path, {}) or {}

    # PAi Claims 1.3.1 created a graph shell but did not persist every later
    # in-app mutation.  Never silently hand that incomplete snapshot to Legal.
    handoff = graph.get("handoff") if isinstance(graph.get("handoff"), dict) else {}
    writer_version = handoff.get("writer_version") or graph.get("source_version") or ""
    if not handoff.get("ready") or _version_tuple(writer_version) < MIN_CLAIMS_HANDOFF_VERSION:
        raise ValueError(
            "This PAi Claims graph is not handoff-ready. Open and save the case in "
            "PAi Claims 1.3.2 or later so the current bracket graph is persisted before Legal reads it."
        )

    claim_revision = str(claim.get("state_revision") or "")
    graph_revision = str(graph.get("state_revision") or handoff.get("state_revision") or "")
    if not claim_revision or claim_revision != graph_revision:
        raise ValueError(
            "PAi Claims handoff refused because claim.json and case_graph.json are not the same persisted revision. "
            "Reopen and save the case in PAi Claims before handing it to Legal."
        )

    expected_claim_hash = str(handoff.get("claim_file_sha256") or "").lower()
    actual_claim_hash = _sha256(claim_path).lower()
    if not expected_claim_hash or expected_claim_hash != actual_claim_hash:
        raise ValueError(
            "PAi Claims handoff refused because the persisted claim and graph do not match. "
            "Reopen and save the case in PAi Claims before handing it to Legal."
        )
    return manifest, claim, graph


def graph_parts(graph: dict) -> tuple[list[dict], list[dict]]:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list):
        nodes = graph.get("propositions") if isinstance(graph.get("propositions"), list) else []
    if not isinstance(edges, list):
        edges = graph.get("relationships") if isinstance(graph.get("relationships"), list) else []
    return [item for item in nodes if isinstance(item, dict)], [item for item in edges if isinstance(item, dict)]


def project_claims_graph(shared_root: Path) -> list[dict]:
    manifest, claim, graph = validate_claims_workspace(shared_root)
    nodes, edges = graph_parts(graph)
    records: list[dict] = []
    line = 1
    for node in nodes:
        node_id = str(node.get("id") or f"node-{line}")
        statement = str(node.get("statement") or node.get("value") or node_id)
        source_bracket = str(node.get("bracket") or "UNVERIFIED").upper()
        trust_lock = _last_non_contradicted(node)
        roots = list(node.get("provenanceRoots") or node.get("provenance_roots") or [])
        evidence_ids = list(node.get("sourceEvidenceIds") or node.get("source_evidence_ids") or [])
        reason = str(node.get("reason") or "")
        records.append({
            "source": f"PAi Claims graph [{node_id}]",
            "line": line,
            "text": f"{_wrap(statement, source_bracket)} [CLAIMS:{node_id}]",
            "role": "claims_atomic_node",
            "rank": 4,
            "bracket": trust_lock,
            "source_bracket": source_bracket,
            "contradicted": source_bracket == "CONTRADICTED",
            "origin": "pai-claims-handoff",
            "claim_node_id": node_id,
            "channel": node.get("channel"),
            "reason": reason,
            "sourceEvidenceIds": evidence_ids,
            "provenanceRoots": roots,
            "history": list(node.get("history") or []),
            "raw_node": node,
        })
        line += 1
    for edge in edges:
        edge_id = str(edge.get("id") or f"edge-{line}")
        source_bracket = str(edge.get("bracket") or "UNVERIFIED").upper()
        statement = (
            f"Relationship {edge.get('fromNodeId') or edge.get('from')} "
            f"--{edge.get('kind') or edge.get('type') or 'related_to'}--> "
            f"{edge.get('toNodeId') or edge.get('to')}"
        )
        records.append({
            "source": f"PAi Claims graph edge [{edge_id}]",
            "line": line,
            "text": f"{_wrap(statement, source_bracket)} [CLAIMS-EDGE:{edge_id}]",
            "role": "claims_atomic_relationship",
            "rank": 5,
            "bracket": _last_non_contradicted(edge),
            "source_bracket": source_bracket,
            "contradicted": source_bracket == "CONTRADICTED",
            "origin": "pai-claims-handoff",
            "claim_edge_id": edge_id,
            "reason": str(edge.get("reason") or ""),
            "sourceEvidenceIds": list(edge.get("sourceEvidenceIds") or []),
            "provenanceRoots": list(edge.get("provenanceRoots") or []),
            "history": list(edge.get("history") or []),
            "raw_edge": edge,
        })
        line += 1
    return records


def _registry_path(legal_root: Path) -> Path:
    return Path(legal_root) / REGISTRY_NAME


def linked_case_records(legal_root: Path) -> list[dict]:
    data = _json(_registry_path(Path(legal_root)), [])
    if not isinstance(data, list):
        return []
    output: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        overlay = Path(str(item.get("overlay_path") or ""))
        if overlay.is_dir() and (overlay / "case.json").is_file():
            output.append(item)
    return output


def link_claims_workspace(legal_root: Path, shared_root: Path) -> dict:
    legal_root = Path(legal_root).expanduser().resolve()
    shared_root = Path(shared_root).expanduser().resolve()
    manifest, claim, graph = validate_claims_workspace(shared_root)
    graph_path = shared_root / GRAPH_NAME
    before_hash = _sha256(graph_path)

    folder_name = str((manifest.get("folders") or {}).get("paiLegal") or "pai_legal")
    overlay = shared_root / folder_name
    overlay.mkdir(parents=True, exist_ok=True)
    for name in LEGAL_OVERLAY_FOLDERS:
        (overlay / name).mkdir(parents=True, exist_ok=True)

    workspace_id = str(manifest.get("workspace_id") or claim.get("claim_id") or shared_root.name)
    case_id = _safe_case_id(workspace_id)
    name = str(claim.get("name") or claim.get("claimNumber") or shared_root.name)
    metadata_path = overlay / "case.json"
    metadata = _json(metadata_path, {}) or {}
    metadata.update({
        "schema_version": max(2, int(metadata.get("schema_version", 1) or 1)),
        "case_id": metadata.get("case_id") or case_id,
        "name": metadata.get("name") or name,
        "status": metadata.get("status") or "CLAIMS_HANDOFF",
        "created_at": metadata.get("created_at") or _now(),
        "updated_at": _now(),
        "document_count": int(metadata.get("document_count", 0) or 0),
        "indexed_count": int(metadata.get("indexed_count", 0) or 0),
        "source_product": "pai-claims",
        "shared_workspace_root": str(shared_root),
        "source_workspace_id": workspace_id,
        "source_case_graph": str(graph_path),
        "handoff_mode": "parliament-read-only-base",
    })
    _atomic_write(metadata_path, metadata)

    extension_path = overlay / EXTENSIONS_NAME
    if not extension_path.is_file():
        _atomic_write(extension_path, {
            "schema": "pai.legal-graph-extensions",
            "schema_version": 1,
            "source_case_graph": str(graph_path),
            "source_case_graph_sha256_at_link": before_hash,
            "nodes": [],
            "edges": [],
            "history": [],
        })

    registry_path = _registry_path(legal_root)
    registry = _json(registry_path, [])
    if not isinstance(registry, list):
        registry = []
    record = {
        "case_id": str(metadata["case_id"]),
        "name": str(metadata["name"]),
        "status": str(metadata["status"]),
        "document_count": int(metadata.get("document_count", 0) or 0),
        "overlay_path": str(overlay),
        "shared_workspace_root": str(shared_root),
        "workspace_id": workspace_id,
        "linked_at": _now(),
    }
    registry = [item for item in registry if isinstance(item, dict) and item.get("workspace_id") != workspace_id]
    registry.append(record)
    _atomic_write(registry_path, registry)

    after_hash = _sha256(graph_path)
    if before_hash != after_hash:
        raise RuntimeError("PAi Legal handoff guard stopped because the Claims base graph changed during linking.")

    refresh_projection(overlay)
    return record


def unlink_claims_workspace(legal_root: Path, workspace_id: str) -> None:
    path = _registry_path(Path(legal_root))
    registry = _json(path, [])
    if not isinstance(registry, list):
        return
    registry = [item for item in registry if not (isinstance(item, dict) and item.get("workspace_id") == workspace_id)]
    _atomic_write(path, registry)


def _shared_root_from_overlay(case_overlay: Path) -> Path | None:
    metadata = _json(Path(case_overlay) / "case.json", {}) or {}
    value = metadata.get("shared_workspace_root")
    return Path(str(value)).expanduser().resolve() if value else None


def refresh_projection(case_overlay: Path) -> list[dict]:
    overlay = Path(case_overlay)
    shared_root = _shared_root_from_overlay(overlay)
    if not shared_root:
        return []
    records = project_claims_graph(shared_root)
    destination = overlay / "reasoning_corpus" / PROJECTION_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records


def merge_projection_into_case_sources(case_overlay: Path) -> int:
    overlay = Path(case_overlay)
    projection = refresh_projection(overlay)
    destination = overlay / "reasoning_corpus" / "case_sources.jsonl"
    existing: list[dict] = []
    if destination.is_file():
        for raw in destination.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(raw)
                if isinstance(record, dict) and record.get("origin") != "pai-claims-handoff":
                    existing.append(record)
            except json.JSONDecodeError:
                continue
    combined = [*existing, *projection]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for record in combined:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(projection)


def handoff_summary(case_overlay: Path) -> dict:
    overlay = Path(case_overlay)
    shared_root = _shared_root_from_overlay(overlay)
    if not shared_root:
        return {"linked": False}
    manifest, claim, graph = validate_claims_workspace(shared_root)
    nodes, edges = graph_parts(graph)
    return {
        "linked": True,
        "mode": "parliament-read-only-base",
        "shared_workspace_root": str(shared_root),
        "workspace_id": manifest.get("workspace_id"),
        "claim_id": claim.get("claim_id") or claim.get("id"),
        "base_graph_path": str(shared_root / GRAPH_NAME),
        "base_graph_sha256": _sha256(shared_root / GRAPH_NAME),
        "atomic_nodes": len(nodes),
        "atomic_relationships": len(edges),
        "legal_extensions_path": str(overlay / EXTENSIONS_NAME),
        "guard": "PAi Legal may extend the map but does not rewrite the PAi Claims base graph.",
    }


def read_legal_extensions(case_overlay: Path) -> dict:
    path = Path(case_overlay) / EXTENSIONS_NAME
    value = _json(path, {}) or {}
    return value if isinstance(value, dict) else {}


def record_legal_extension(case_overlay: Path, statement: str, bracket: str,
                           sources: Iterable[str] = (), note_type: str = "legal_proposition") -> dict | None:
    overlay = Path(case_overlay)
    if not _shared_root_from_overlay(overlay):
        return None
    path = overlay / EXTENSIONS_NAME
    graph = read_legal_extensions(overlay) or {
        "schema": "pai.legal-graph-extensions", "schema_version": 1,
        "nodes": [], "edges": [], "history": [],
    }
    source_list = [str(item) for item in sources if str(item)]
    claims_ids: list[str] = []
    for source in source_list:
        claims_ids.extend(re.findall(r"\[CLAIMS:([^\]]+)\]", source))
    node = {
        "id": f"legal:{uuid.uuid4()}",
        "kind": note_type or "legal_proposition",
        "statement": str(statement),
        "bracket": str(bracket or "UNVERIFIED").upper(),
        "sourceRefs": source_list,
        "sourceClaimsNodeIds": list(dict.fromkeys(claims_ids)),
        "provenanceRoots": ["PAi Legal Parliament"],
        "createdAt": _now(),
        "updatedAt": _now(),
        "history": [{
            "id": f"legal-history:{uuid.uuid4()}",
            "at": _now(),
            "action": "created",
            "toBracket": str(bracket or "UNVERIFIED").upper(),
            "reason": "Legal proposition created by the receiving Parliament; source Claims nodes remain unchanged.",
        }],
    }
    graph.setdefault("nodes", []).append(node)
    graph.setdefault("history", []).append({"at": _now(), "event": "legal_extension_added", "node_id": node["id"]})
    _atomic_write(path, graph)
    return node
