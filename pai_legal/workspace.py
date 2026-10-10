"""Permanent case/evidence workspace owned by PAi Legal."""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .ingestion import TextExtractor
from .audit import AuditChain
from .backup import create_backup, restore_backup
from .epistemic import BracketType, bracket_name, wrap_claim
from . import brackets, doctypes, matters, parliament, plainspeak
from .governance import (conflict_hits, disposition_status, parties_from_caption,
                         parse_retention_date, party_key)
from .jurisdiction import validate_filing
from .rpm_legal import process as rpm_process, state_record
from .security import (AccessController, DPAPIProtector, SecretStore,
                       SecretStoreUnavailable, SoftProtector, StoragePolicy)
from .transition_map import (
    CaseTransitionMap,
    build_case_transition_map,
    input_signature as transition_input_signature,
)

# PAi Legal 0.9.7: Microsoft commerce + read-only Claims Parliament handoff.
from .commerce import CommerceManager
from .claims_handoff import (
    handoff_summary, link_claims_workspace, linked_case_records,
    merge_projection_into_case_sources, read_legal_extensions,
    record_legal_extension, unlink_claims_workspace,
)

CASE_FOLDERS = (
    "00_inbox",
    "01_originals",
    "02_text",
    "court_papers",
    "depositions",
    "correspondence",
    "exhibits",
    "discovery",
    "04_index",
    "05_trace",
    "reasoning_corpus",
    "notes",
    "research",
    "audit",
    "exports",
)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    cleaned = "".join(char for char in value.strip() if char.isalnum() or char in " -_.").strip()
    return cleaned or "Untitled Case"


def default_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "PAiLegal"


@dataclass(frozen=True)
class CaseRef:
    case_id: str
    name: str
    path: Path
    status: str
    document_count: int

    @property
    def label(self) -> str:
        return f"{self.case_id} — {self.name}"


@dataclass(frozen=True)
class IngestedFile:
    original: Path
    filed_copy: Path
    normalized_text: Optional[Path]
    document_type: str
    source_folder: str
    extraction_method: str = ""
    error: str = ""


class Workspace:
    def __init__(self, root: Optional[Path] = None, extractor: Optional[TextExtractor] = None,
                 access: AccessController | None = None,
                 storage_policy: StoragePolicy | None = None,
                 secret_store: SecretStore | None = None,
                 audit_secret_store: SecretStore | None = None):
        self.root = Path(root or default_root())
        self.extractor = extractor or TextExtractor()
        self.cases_dir = self.root / "cases"
        self.archive_dir = self.root / "archive"
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.access = access or AccessController(self.root)
        self.storage_policy = storage_policy or StoragePolicy(self.root)
        self.secret_store = secret_store or SecretStore(self.root)
        if audit_secret_store:
            self.audit_secret_store = audit_secret_store
        else:
            protector = DPAPIProtector(machine_scope=True) if os.name == "nt" else SoftProtector(self.root)
            self.audit_secret_store = SecretStore(self.root, protector=protector, filename="audit_vault.json")
        self._audit_chains: dict[str, AuditChain] = {}
        self._audit_key_cache: dict[str, bytes] = {}
        self._workspace_chain: AuditChain | None = None

    def _authorize(self, permission: str, write: bool = False) -> None:
        self.access.require(permission)
        if write:
            self.storage_policy.require_writable_storage()

    def security_status(self) -> dict:
        encryption = self.storage_policy.status()
        try:
            # Prove the vault round-trips without creating a case secret.
            probe_name = "workspace_vault_probe_v1"
            probe = self.secret_store.get_bytes(probe_name)
            if probe is None:
                self.secret_store.set(probe_name, secrets.token_bytes(32))
            vault = {"available": True, "provider": "Windows DPAPI (current user)"}
        except SecretStoreUnavailable as exc:
            vault = {"available": False, "provider": "unavailable", "detail": str(exc)}
        admin_audit = self.verify_workspace_audit()
        return {"access": self.access.status(), "encryption": encryption.as_dict(),
                "encryption_required": self.storage_policy.require_encrypted_volume,
                "credential_vault": vault, "administrative_audit": admin_audit}

    def _workspace_audit(self) -> AuditChain:
        if self._workspace_chain is None:
            name = "workspace_admin_audit_key_v1"
            key = self.audit_secret_store.get_bytes(name)
            if key is None:
                key = secrets.token_bytes(32)
                self.audit_secret_store.set(name, key)
            self._workspace_chain = AuditChain(self.root / "audit" / "workspace_events.jsonl", key)
        return self._workspace_chain

    def _append_workspace_event(self, event_type: str, payload: dict,
                                actor_role: str | None = None) -> dict:
        record = {"event_id": f"ADM-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                  "timestamp": now(), "event_type": event_type,
                  "actor": self.access.username,
                  "role": actor_role or self.access.role,
                  "identity_source": "operating_system_account", "payload": payload}
        chain = self._workspace_audit()
        anchor_raw = self.audit_secret_store.get("workspace_admin_chain_head_v1")
        if anchor_raw:
            anchor = json.loads(anchor_raw)
            if chain.anchor_status(int(anchor.get("sequence") or 0),
                                   str(anchor.get("integrity") or "")) == "mismatch":
                raise RuntimeError("Administrative audit rollback or replacement detected")
        appended = chain.append(record)
        verified = chain.verify()
        self.audit_secret_store.set("workspace_admin_chain_head_v1", json.dumps({
            "sequence": verified["events"], "integrity": verified["head"]}, separators=(",", ":")))
        return appended

    def verify_workspace_audit(self) -> dict:
        chain = self._workspace_audit()
        result = chain.verify()
        anchor_raw = self.audit_secret_store.get("workspace_admin_chain_head_v1")
        if anchor_raw:
            try:
                anchor = json.loads(anchor_raw)
                status = chain.anchor_status(int(anchor.get("sequence") or 0),
                                             str(anchor.get("integrity") or ""))
            except ValueError:
                status = "mismatch"
            result["anchor_status"] = status
            if status == "mismatch":
                result["valid"] = False
                result["errors"].append("Protected administrative audit head does not match")
        else:
            result["anchor_status"] = "missing"
        return result

    def assign_role(self, username: str, role: str) -> None:
        self._authorize("access.manage", write=True)
        actor_role = self.access.role
        self.access.set_role(username, role)
        self._append_workspace_event("workspace_role_assigned", {
            "username": str(username).strip().lower(), "role": str(role).strip().lower()}, actor_role)

    def set_encryption_enforcement(self, required: bool) -> None:
        self._authorize("access.manage", write=False)
        if required and self.storage_policy.status().protected is not True:
            raise PermissionError("Cannot require encrypted storage until BitLocker protection is verified")
        self.storage_policy.set_enforcement(bool(required))
        self._append_workspace_event("encrypted_volume_policy_changed", {"required": bool(required)})

    def set_integration_secret(self, name: str, value: str) -> None:
        self._authorize("integration.manage", write=True)
        allowed = {"psi_legal_api_token", "private_ai_session_token"}
        if name not in allowed:
            raise ValueError("Unsupported integration credential")
        secret = str(value or "")
        if len(secret) < 16:
            raise ValueError("Integration tokens must contain at least 16 characters")
        self.secret_store.set(name, secret)
        self._append_workspace_event("integration_credential_stored", {"credential_name": name})

    def delete_integration_secret(self, name: str) -> bool:
        self._authorize("integration.manage", write=True)
        if name not in {"psi_legal_api_token", "private_ai_session_token"}:
            raise ValueError("Unsupported integration credential")
        removed = self.secret_store.delete(name)
        if removed:
            self._append_workspace_event("integration_credential_deleted", {"credential_name": name})
        return removed

    def _audit_key(self, case_id: str) -> bytes:
        if case_id in self._audit_key_cache:
            return self._audit_key_cache[case_id]
        name = f"audit_hmac_key_v1:{case_id}"
        value = self.audit_secret_store.get_bytes(name)
        if value is None:
            value = secrets.token_bytes(32)
            self.audit_secret_store.set(name, value)
        self._audit_key_cache[case_id] = value
        return value

    def _audit_chain(self, case: CaseRef) -> AuditChain:
        key = str(case.path.resolve())
        chain = self._audit_chains.get(key)
        if chain is None:
            chain = AuditChain(case.path / "audit" / "epistemic_events.jsonl",
                               self._audit_key(case.case_id))
            self._audit_chains[key] = chain
        return chain

    @staticmethod
    def _audit_anchor_name(case_id: str) -> str:
        return f"audit_chain_head_v1:{case_id}"

    def _anchor(self, case_id: str) -> dict | None:
        value = self.audit_secret_store.get(self._audit_anchor_name(case_id))
        if not value:
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None

    def _save_anchor(self, case_id: str, verification: dict) -> None:
        self.audit_secret_store.set(self._audit_anchor_name(case_id), json.dumps({
            "sequence": int(verification.get("events") or 0),
            "integrity": str(verification.get("head") or ""),
        }, separators=(",", ":")))

    @staticmethod
    def _ensure_folders(case_dir: Path) -> None:
        for folder in CASE_FOLDERS:
            (case_dir / folder).mkdir(exist_ok=True)

    @staticmethod
    def _metadata_path(case_dir: Path) -> Path:
        return case_dir / "case.json"

    def _read(self, case_dir: Path) -> dict:
        return json.loads(self._metadata_path(case_dir).read_text(encoding="utf-8"))

    def _write(self, case_dir: Path, metadata: dict) -> None:
        metadata["updated_at"] = now()
        path = self._metadata_path(case_dir)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


    # PAi Legal 0.9.7 commerce / Parliament seam --------------------
    def _commerce_gate(self):
        return CommerceManager(self.root)

    def commerce_status(self):
        return self._commerce_gate().status()

    def purchase_annual_access(self):
        return self._commerce_gate().purchase_annual_access()

    def _commerce_case_count(self):
        count = len(self.list_cases())
        try:
            count += len(self.list_archived_cases())
        except Exception:
            pass
        return count

    @staticmethod
    def _rollback_empty_case(case) -> None:
        """Remove only a brand-new empty case if post-create fulfillment fails."""
        try:
            path = Path(case.path)
            metadata = json.loads((path / "case.json").read_text(encoding="utf-8"))
            if int(metadata.get("document_count", metadata.get("doc_count", 0)) or 0) != 0:
                return
            # A freshly-created case contains only PAi-created folders/files.
            shutil.rmtree(path)
        except Exception:
            pass

    def list_cases(self):
        cases = list(self._list_local_cases())
        existing = {case.case_id for case in cases}
        for item in linked_case_records(self.root):
            try:
                case_id = str(item["case_id"])
                if case_id in existing:
                    continue
                overlay = Path(str(item["overlay_path"]))
                metadata = self._read(overlay)
                cases.append(CaseRef(
                    case_id,
                    str(metadata.get("name") or item.get("name") or case_id),
                    overlay,
                    str(metadata.get("status", "CLAIMS_HANDOFF")),
                    int(metadata.get("document_count", metadata.get("doc_count", 0)) or 0),
                ))
                existing.add(case_id)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(cases, key=lambda case: case.case_id)

    def create_case(self, *args, **kwargs):
        self._authorize("case.create", write=True)
        reservation = self._commerce_gate().begin_new_case(self._commerce_case_count())
        case = None
        try:
            case = self._create_case_unmetered(*args, **kwargs)
            self._commerce_gate().commit_new_case(reservation, case.case_id)
            return case
        except Exception:
            if case is not None and reservation.mode == "consumable":
                self._rollback_empty_case(case)
            self._commerce_gate().cancel_reservation(reservation)
            raise

    def open_claims_workspace(self, shared_root):
        shared_root = Path(shared_root).expanduser().resolve()
        # Re-opening an already-linked Claims workspace is navigation, not a
        # new paid case. Never reserve or consume another credit for it.
        for existing in linked_case_records(self.root):
            try:
                if Path(str(existing.get("shared_workspace_root") or "")).expanduser().resolve() == shared_root:
                    overlay = Path(str(existing["overlay_path"]))
                    metadata = self._read(overlay)
                    case = CaseRef(
                        str(metadata["case_id"]), str(metadata["name"]), overlay,
                        str(metadata.get("status", "CLAIMS_HANDOFF")),
                        int(metadata.get("document_count", 0) or 0),
                    )
                    merge_projection_into_case_sources(case.path)
                    return case
            except (OSError, ValueError, KeyError, TypeError):
                continue

        reservation = self._commerce_gate().begin_new_case(self._commerce_case_count())
        record = None
        try:
            record = link_claims_workspace(self.root, shared_root)
            overlay = Path(record["overlay_path"])
            metadata = self._read(overlay)
            case = CaseRef(
                str(metadata["case_id"]), str(metadata["name"]), overlay,
                str(metadata.get("status", "CLAIMS_HANDOFF")),
                int(metadata.get("document_count", 0) or 0),
            )
            # The base Claims graph is projected read-only into the receiving
            # Parliament. The original case_graph.json is never rewritten.
            merge_projection_into_case_sources(case.path)
            self._commerce_gate().commit_new_case(reservation, case.case_id)
            self._append_workspace_event("claims_parliament_handoff", {
                "case_id": case.case_id,
                "workspace_id": record.get("workspace_id"),
                "shared_workspace_root": record.get("shared_workspace_root"),
                "guard": "Claims base graph read-only; Legal extensions separate",
            })
            return case
        except Exception:
            if record:
                unlink_claims_workspace(self.root, str(record.get("workspace_id") or ""))
            self._commerce_gate().cancel_reservation(reservation)
            raise

    def _list_local_cases(self) -> List[CaseRef]:
        self._authorize("case.read")
        cases: List[CaseRef] = []
        for case_dir in sorted(self.cases_dir.glob("CASE-*")):
            try:
                data = self._read(case_dir)
                cases.append(CaseRef(
                    str(data["case_id"]),
                    str(data["name"]),
                    case_dir,
                    str(data.get("status", "COLLECTING")),
                    int(data.get("document_count", data.get("doc_count", 0))),
                ))
            except (OSError, ValueError, KeyError):
                continue
        return cases

    def _create_case_unmetered(self, name: str, parties: Iterable[str] = ()) -> CaseRef:
        self._authorize("case.create", write=True)
        used = {case.case_id for case in (*self.list_cases(), *self.list_archived_cases())}
        number = 1
        while f"CASE-{number:06d}" in used:
            number += 1
        case_id = f"CASE-{number:06d}"
        case_dir = self.cases_dir / case_id
        case_dir.mkdir(parents=False, exist_ok=False)
        for folder in CASE_FOLDERS:
            (case_dir / folder).mkdir()
        data = {
            "schema_version": 1,
            "case_id": case_id,
            "name": safe_name(name),
            "status": "COLLECTING",
            "created_at": now(),
            "updated_at": now(),
            "document_count": 0,
            "indexed_count": 0,
            "conflict_parties": list(dict.fromkeys(
                safe_name(item) for item in (*parties_from_caption(name), *parties) if str(item).strip())),
            "governance": {"retain_until": "", "retention_basis": "manual review required",
                           "legal_hold": {"active": False}},
        }
        self._write(case_dir, data)
        case = CaseRef(case_id, data["name"], case_dir, data["status"], 0)
        self.append_event(case, "case_created", {"name": data["name"],
                                                  "conflict_parties": data["conflict_parties"]})
        return case

    def archive_case(self, case: CaseRef) -> Path:
        self._authorize("case.archive", write=True)
        self.append_event(case, "case_archived", {"recoverable": True})
        data = self._read(case.path)
        data["status"] = "ARCHIVED"
        data["closed_at"] = now()
        self._write(case.path, data)
        target = self.archive_dir / case.case_id
        if target.exists():
            raise FileExistsError(f"Archive already exists: {target}")
        return case.path.rename(target)

    def list_archived_cases(self) -> List[CaseRef]:
        self._authorize("case.read")
        cases: List[CaseRef] = []
        for case_dir in sorted(self.archive_dir.glob("CASE-*")):
            try:
                data = self._read(case_dir)
                cases.append(CaseRef(str(data["case_id"]), str(data["name"]), case_dir,
                                     "ARCHIVED", int(data.get("document_count", 0))))
            except (OSError, ValueError, KeyError):
                continue
        return cases

    def restore_case(self, case_id: str) -> CaseRef:
        self._authorize("case.archive", write=True)
        source = self.archive_dir / case_id
        if not source.is_dir():
            raise FileNotFoundError(f"Archived case not found: {case_id}")
        target = self.cases_dir / case_id
        if target.exists():
            raise FileExistsError(f"An active case already uses {case_id}")
        data = self._read(source); data["status"] = "COLLECTING"; data["restored_at"] = now()
        self._write(source, data); source.rename(target); self._ensure_folders(target)
        case = CaseRef(case_id, str(data["name"]), target, "COLLECTING", int(data.get("document_count", 0)))
        self.append_event(case, "case_restored", {"source": "workspace_archive"})
        return case

    @staticmethod
    def classify(path: Path, text: str = "") -> tuple[str, str]:
        role = doctypes.classify(path.name, text)
        return role.label, role.folder

    def _refile(self, case: CaseRef, filed: Path, normalized):
        """Re-sort a filed copy once its text is known."""
        try:
            head = normalized.read_text(encoding="utf-8", errors="replace")[:doctypes.TEXT_HEAD_CHARACTERS] if normalized else ""
        except OSError:
            head = ""
        role = doctypes.classify(filed.name, head)
        if role.folder == filed.parent.name:
            return filed, role.label, role.folder, normalized
        target = self._unique(case.path / role.folder / filed.name)
        try:
            target.parent.mkdir(exist_ok=True)
            filed.replace(target)
        except OSError:
            return filed, role.label, filed.parent.name, normalized
        return target, role.label, role.folder, normalized

    def ingest(self, case: CaseRef, paths: Iterable[Path]) -> List[IngestedFile]:
        self._authorize("evidence.write", write=True)
        results: List[IngestedFile] = []
        count = 0
        for source in (Path(item) for item in paths):
            if not source.is_file():
                continue
            document_type, folder = self.classify(source)
            destination = self._unique(case.path / folder / source.name)
            original = self._unique(case.path / "01_originals" / source.name)
            try:
                shutil.copy2(source, destination)
                shutil.copy2(source, original)
                count += 1
                try:
                    normalized, method = self.normalize(case, destination)
                    warning = ""
                    # The filename picked the folder before any text existed.
                    # Let the document's own first page correct it.
                    destination, document_type, folder, normalized = self._refile(
                        case, destination, normalized)
                except Exception as exc:
                    # The evidence is successfully preserved even when a text
                    # extractor is unavailable. Analysis simply excludes it
                    # until a supported extractor is installed.
                    normalized = None
                    method = ""
                    warning = f"Evidence preserved; normalization unavailable: {exc}"
                results.append(IngestedFile(
                    original, destination, normalized, document_type, folder, method, warning
                ))
            except Exception as exc:
                results.append(IngestedFile(original, destination, None, document_type, folder, "", str(exc)))
        if count:
            data = self._read(case.path)
            data["document_count"] = int(data.get("document_count", 0)) + count
            self._write(case.path, data)
            preserved = []
            for item in results:
                if item.original.is_file():
                    preserved.append({"source": item.original.name,
                                      "sha256": self._file_sha256(item.original),
                                      "bytes": item.original.stat().st_size})
            self.append_event(case, "evidence_ingested", {"documents": preserved})
        return results

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _unique(path: Path) -> Path:
        if not path.exists():
            return path
        number = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
            if not candidate.exists():
                return candidate
            number += 1

    def normalize(self, case: CaseRef, source: Path) -> tuple[Path, str]:
        target = self._unique(case.path / "02_text" / f"{source.stem}.txt")
        result = self.extractor.extract(source)
        header = (
            f"<<<SOURCE {source.name}>>>\n"
            f"<<<EXTRACTION {result.method}; pages={result.pages}; ocr_pages={result.ocr_pages}>>>\n"
        )
        target.write_text(header + result.text, encoding="utf-8")
        state, lock = rpm_process(result.text, {"source": source.name})
        index_path = self._unique(case.path / "04_index" / f"{source.stem}.rpm.json")
        index_path.write_text(json.dumps(
            state_record(state, lock, source=source.name), indent=2, ensure_ascii=False
        ), encoding="utf-8")
        return target, result.method


    def build_reasoning_corpus(self, *args, **kwargs):
        result = self._build_reasoning_corpus_local(*args, **kwargs)
        case = args[0] if args else kwargs.get("case")
        if case is not None:
            try:
                merge_projection_into_case_sources(case.path)
            except Exception:
                # A normal non-Claims case has no handoff metadata.
                pass
        return result

    def _build_reasoning_corpus_local(self, case: CaseRef) -> Path:
        self._authorize("workproduct.write", write=True)
        text_files = sorted((case.path / "02_text").glob("*.txt"))
        # Which lawsuit each document belongs to. One folder often holds more
        # than one, and everything downstream inherits the confusion if they
        # are not kept apart.
        matter_map = matters.detect_matters(
            (item.name, item.read_text(encoding="utf-8", errors="replace")) for item in text_files)
        matter_assignment = matter_map["assignment"]
        self._write_matters(case, matter_map)
        if not text_files:
            raise RuntimeError("No normalized documents are available")
        corpus_dir = case.path / "reasoning_corpus"
        corpus_dir.mkdir(exist_ok=True)
        jsonl_path = corpus_dir / "case_sources.jsonl"
        records = 0
        with jsonl_path.open("w", encoding="utf-8") as output:
            for text_file in text_files:
                index_candidates = sorted((case.path / "04_index").glob(f"{text_file.stem}*.rpm.json"))
                try:
                    rpm = json.loads(index_candidates[0].read_text(encoding="utf-8")) if index_candidates else {}
                except (OSError, ValueError):
                    rpm = {}
                body = text_file.read_text(encoding="utf-8", errors="replace")
                role = doctypes.classify(text_file.name, body)
                matter_id = matter_assignment.get(text_file.name, "")
                for line_number, line in enumerate(body.splitlines(), 1):
                    if not line.strip():
                        continue
                    output.write(json.dumps({
                        "source": text_file.name,
                        "line": line_number,
                        "text": line,
                        "role": role.key,
                        "rank": role.rank,
                        "matter": matter_id,
                        "bracket": rpm.get("bracket", BracketType.UNVERIFIED.name),
                        "rpm": {
                            "float_points": rpm.get("float_points", 0),
                            "mix_points": rpm.get("mix_points", 0),
                            "stir_points": rpm.get("stir_points", 0),
                            "total_pressure": rpm.get("total_pressure", 0.0),
                            "pattern_signature": rpm.get("pattern_signature", ""),
                        },
                    }, ensure_ascii=False) + "\n")
                    records += 1
        (corpus_dir / "manifest.json").write_text(json.dumps({
            "case_id": case.case_id,
            "built_at": now(),
            "documents": [item.name for item in text_files],
            "records": records,
            "derived": True,
        }, indent=2), encoding="utf-8")
        return jsonl_path

    # Words too common in legal documents to discriminate between them.
    _STOPWORDS = frozenset("""a an and any are as at be been but by for from has have if in
        is it its of on or shall such that the their there these this to was were what when
        which who will with would you your i me my we our us he she they them been being do
        does did not no nor so than then thus upon into over under about above after before
        between during without within case claim document documents file files please""".split())

    @classmethod
    def _terms(cls, question: str) -> List[str]:
        words = re.findall(r"[a-z0-9][a-z0-9\-]{2,}", question.lower())
        return [word for word in words if word not in cls._STOPWORDS]

    def _load_records(self, path: Path) -> List[dict]:
        records: List[dict] = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(raw)
                str(record["source"]), record["line"], str(record["text"])
            except (ValueError, KeyError):
                continue
            records.append(record)
        return records

    # Extraction bookkeeping the reader wrote into the text; useful in the file,
    # pure noise in a context window.
    _NOISE_PREFIXES = ("<<<SOURCE ", "<<<EXTRACTION ")

    @classmethod
    def _is_noise(cls, text: str) -> bool:
        return text.lstrip().startswith(cls._NOISE_PREFIXES)

    @staticmethod
    def _render_group(source: str, records: List[dict]) -> str:
        """Render one document as a header plus bare numbered lines.

        Repeating the filename and a bracket wrapper on every line spent most
        of the context window on prefixes rather than evidence — a 7-character
        line cost 60 characters to deliver. The header carries the source name,
        stored Trust Lock and pressure once; lines carry only their number, and
        stay citable as source:line.
        """
        rpm = records[0].get("rpm", {})
        bracket = str(records[0].get("bracket") or "UNVERIFIED")
        role = doctypes.label_of(records[0].get("role", "unclassified"))
        header = (f"=== {source} | {role} | {bracket} | F/M/S="
                  f"{rpm.get('float_points',0)}/{rpm.get('mix_points',0)}/{rpm.get('stir_points',0)}"
                  f" | pressure={rpm.get('total_pressure',0)} ===")
        body = [f"{record['line']}: {str(record['text']).strip()}" for record in records]
        return "\n".join([header] + body)

    @classmethod
    def _assemble(cls, records: List[dict], indexes) -> str:
        """Group by document and present them in the order a lawyer reads.

        The operative pleading defines the claims, so it comes first whatever
        the filenames sort like; correspondence and exhibits come last.
        """
        grouped: Dict[str, List[dict]] = {}
        for index in indexes:
            record = records[index]
            grouped.setdefault(str(record["source"]), []).append(record)
        ordered = sorted(
            grouped,
            key=lambda name: (int(grouped[name][0].get("rank", 99)), name.lower()),
        )
        return "\n\n".join(cls._render_group(source, grouped[source]) for source in ordered)

    def context(self, case: CaseRef, max_characters: int = 24_000, question: str = "",
                matter: str = "") -> str:
        """Assemble the analysis context, selecting for the question when given.

        A case can hold far more text than any context window. Reading the
        corpus front-to-back fills the budget with whichever documents sort
        first, so a question about mold never sees the mold report. When a
        question is supplied, lines are scored against it and the documents
        that actually answer it are selected; every line keeps its own source,
        line number, and stored bracket, so nothing is summarized away.
        """
        path = case.path / "reasoning_corpus" / "case_sources.jsonl"
        if not path.is_file():
            return ""
        records = self._load_records(path)
        if matter:
            records = [item for item in records if str(item.get("matter") or "") == matter]
        if not records:
            return ""

        terms = self._terms(question)
        scored: List[tuple] = []
        if terms:
            # Rarer terms discriminate better, so weight by inverse document
            # frequency across the case rather than raw hit count.
            frequency = {term: 0 for term in terms}
            for record in records:
                lowered = str(record["text"]).lower()
                for term in terms:
                    if term in lowered:
                        frequency[term] += 1
            total = len(records)
            weights = {term: math.log(1 + total / (1 + count)) for term, count in frequency.items()}
            # The filename is often the strongest signal a document has:
            # "Truview Mold Assessment.pdf" never says "mold" in its body.
            name_bonus: Dict[str, float] = {}
            for source in {str(record["source"]) for record in records}:
                lowered_name = source.lower()
                name_bonus[source] = sum(
                    weights[term] for term in terms if term in lowered_name
                )
            for index, record in enumerate(records):
                if self._is_noise(str(record["text"])):
                    continue
                lowered = str(record["text"]).lower()
                score = sum(weights[term] for term in terms if term in lowered)
                score += name_bonus.get(str(record["source"]), 0.0)
                if score > 0:
                    scored.append((score, index))

        if not scored:
            # No question, or nothing matched: still read in legal order.
            selected: List[int] = []
            used = 0
            records_in_order = sorted(
                range(len(records)),
                key=lambda i: (doctypes.rank_of(records[i].get("role", "unclassified")), i),
            )
            for index in records_in_order:
                record = records[index]
                if self._is_noise(str(record["text"])):
                    continue
                length = len(str(record["text"])) + 8
                if used + length > max_characters:
                    # One pathological/OCR-corrupt line must not hide every
                    # later record that would fit in the context window.
                    continue
                selected.append(index)
                used += length
            return self._assemble(records, sorted(selected))

        # Controlling documents are read whether or not the question mentions
        # them. A lawyer asked about a roof estimate still reads the complaint
        # first, because the pleading is what the estimate has to matter to.
        # A fixed share of the budget is reserved for them, so relevance
        # scoring can never crowd out the operative pleading.
        chosen: set = set()
        used = 0
        controlling_budget = int(max_characters * 0.35)
        controlling = [
            index for index, record in enumerate(records)
            if doctypes.is_controlling(record.get("role", "unclassified"))
            and not self._is_noise(str(record["text"]))
        ]
        if controlling:
            by_rank: Dict[str, List[int]] = {}
            for index in controlling:
                by_rank.setdefault(str(records[index]["source"]), []).append(index)
            for source in sorted(by_rank, key=lambda name: int(records[by_rank[name][0]].get("rank", 99))):
                share = controlling_budget // len(by_rank)
                spent = 0
                for index in by_rank[source]:
                    length = len(str(records[index]["text"])) + 8
                    if spent + length > share:
                        continue
                    chosen.add(index)
                    spent += length
                    used += length

        # Rank documents by their strongest passages, not by total length, so a
        # long irrelevant document cannot outrank a short decisive one.
        by_source: Dict[str, List[tuple]] = {}
        for score, index in scored:
            by_source.setdefault(str(records[index]["source"]), []).append((score, index))
        ranked_sources = sorted(
            by_source,
            key=lambda name: sum(s for s, _ in sorted(by_source[name], reverse=True)[:5]),
            reverse=True,
        )

        # Keep a matched line's neighbours: a figure means little without the
        # sentence that introduces it.
        budget = max_characters
        per_source = max(1500, max_characters // max(4, min(len(ranked_sources), 8)))
        for name in ranked_sources:
            if used >= budget:
                break
            source_used = 0
            for score, index in sorted(by_source[name], reverse=True):
                for neighbour in (index - 1, index, index + 1):
                    if not (0 <= neighbour < len(records)):
                        continue
                    if str(records[neighbour]["source"]) != name or neighbour in chosen:
                        continue
                    if self._is_noise(str(records[neighbour]["text"])):
                        continue
                    length = len(str(records[neighbour]["text"])) + 8
                    if source_used + length > per_source or used + length > budget:
                        continue
                    chosen.add(neighbour)
                    source_used += length
                    used += length

        # Budget usually remains after the matched lines. Spend it widening the
        # passages already chosen: the sentence that states an amount is often
        # next to, not inside, the line that names the subject.
        for reach in (2, 3, 4, 6):
            if used >= budget:
                break
            for index in sorted(chosen):
                name = str(records[index]["source"])
                for neighbour in (index - reach, index + reach):
                    if not (0 <= neighbour < len(records)) or neighbour in chosen:
                        continue
                    if str(records[neighbour]["source"]) != name:
                        continue
                    if self._is_noise(str(records[neighbour]["text"])):
                        continue
                    length = len(str(records[neighbour]["text"])) + 8
                    if used + length > budget:
                        continue
                    chosen.add(neighbour)
                    used += length

        return self._assemble(records, sorted(chosen))

    def rpm_summary(self, case: CaseRef) -> dict:
        """Aggregate the visible case-level Float/Mix/Stir dashboard values."""
        totals = {"documents": 0, "float_points": 0, "mix_points": 0,
                  "stir_points": 0, "total_pressure": 0.0, "top_relations": []}
        relations: list[dict] = []
        for path in sorted((case.path / "04_index").glob("*.rpm.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            totals["documents"] += 1
            for key in ("float_points", "mix_points", "stir_points"):
                totals[key] += int(record.get(key) or 0)
            totals["total_pressure"] += float(record.get("total_pressure") or 0.0)
            relations.extend(record.get("top_mix") or [])
            relations.extend(record.get("top_stir") or [])
        relations.sort(key=lambda item: (float(item.get("pressure") or 0), int(item.get("count") or 0)), reverse=True)
        totals["total_pressure"] = round(totals["total_pressure"], 2)
        totals["top_relations"] = relations[:8]
        return totals

    def _rpm_records(self, case: CaseRef) -> list[dict]:
        records: list[dict] = []
        for path in sorted((case.path / "04_index").glob("*.rpm.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def case_transition_map(self, case: CaseRef, *, force: bool = False) -> CaseTransitionMap:
        """Load or deterministically rebuild the recursively zoomable case map."""

        self._ensure_folders(case.path)
        records = self._rpm_records(case)
        authorities = self.attached_authorities(case)
        expected = transition_input_signature(records, authorities)
        destination = case.path / "05_trace" / "case_transition_map.json"

        if not force and destination.is_file():
            try:
                cached = CaseTransitionMap.from_dict(json.loads(destination.read_text(encoding="utf-8")))
                if cached.input_signature == expected:
                    return cached
            except (OSError, ValueError, KeyError, TypeError):
                pass

        built = build_case_transition_map(case.case_id, case.name, records, authorities)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(built.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)
        self.append_event(case, "transition_map_built", {
            "input_signature": built.input_signature,
            "replay_signature": built.replay_signature,
            "deterministic_seed": built.deterministic_seed,
            "views": len(built.views),
            "transitions": len(built.view().edges),
            "trust_lock_guard": "Pressure observed; status unchanged",
        })
        return built

    def document_rpm(self, case: CaseRef, document: Path | str) -> dict:
        path = Path(document)
        if path.suffix.lower() == ".json" and path.name.endswith(".rpm.json"):
            candidate = path
        else:
            candidates = sorted((case.path / "04_index").glob(f"{path.stem}*.rpm.json"))
            candidate = candidates[0] if candidates else Path()
        if not str(candidate) or not candidate.is_file():
            return {}
        try:
            record = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        # Use the unrounded document totals for contribution percentages.  The
        # dashboard rounds for display; using that rounded value here could
        # report a single document as 100.03% of its own case.
        total = sum(float(item.get("total_pressure") or 0.0) for item in self._rpm_records(case))
        pressure = float(record.get("total_pressure") or 0.0)
        record["case_pressure_percent"] = round(pressure / total * 100, 2) if total else 0.0
        record["index_path"] = str(candidate)
        return record

    def reprocess_document(self, case: CaseRef, document: Path | str) -> dict:
        """Re-extract one preserved/filed document without duplicating evidence."""
        self._authorize("evidence.write", write=True)
        source = Path(document).resolve()
        case_root = case.path.resolve()
        try:
            source.relative_to(case_root)
        except ValueError as exc:
            raise ValueError("Reprocessing is limited to evidence preserved inside this case") from exc
        if not source.is_file() or source.suffix.lower() in {".json", ".txt"} and source.parent.name in {"04_index", "02_text"}:
            raise ValueError("Select a preserved original or filed evidence document")
        result = self.extractor.extract(source)
        text_path = case.path / "02_text" / f"{source.stem}.txt"
        header = f"<<<SOURCE {source.name}>>>\n<<<EXTRACTION {result.method}; pages={result.pages}; ocr_pages={result.ocr_pages}>>>\n"
        temporary = text_path.with_suffix(".tmp"); temporary.write_text(header + result.text, encoding="utf-8"); temporary.replace(text_path)
        state, lock = rpm_process(result.text, {"source": source.name})
        rpm_path = case.path / "04_index" / f"{source.stem}.rpm.json"
        rpm = state_record(state, lock, source=source.name)
        temporary = rpm_path.with_suffix(".tmp"); temporary.write_text(json.dumps(rpm, indent=2, ensure_ascii=False), encoding="utf-8"); temporary.replace(rpm_path)
        self.append_event(case, "document_reprocessed", {"source": source.name, "method": result.method, "pattern_signature": rpm["pattern_signature"]})
        return {"source": source.name, "method": result.method, "text_path": str(text_path), "rpm_path": str(rpm_path), **rpm}

    def append_event(self, case: CaseRef, event_type: str, payload: dict) -> dict:
        self._ensure_folders(case.path)
        record = {"event_id": f"EVT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                  "timestamp": now(), "event_type": event_type, "case_id": case.case_id,
                  "actor": self.access.username, "role": self.access.role,
                  "identity_source": "operating_system_account", "payload": payload}
        chain = self._audit_chain(case)
        existing = chain.verify()
        anchor = self._anchor(case.case_id)
        if anchor:
            if not existing["valid"]:
                raise RuntimeError("Audit log integrity is invalid; refusing to append")
            anchor_status = chain.anchor_status(int(anchor.get("sequence") or 0),
                                                str(anchor.get("integrity") or ""))
            if anchor_status == "mismatch":
                raise RuntimeError("Audit log rollback or replacement detected; refusing to append")
            if anchor_status == "extended":
                # A prior append reached disk before its DPAPI anchor update.
                # A valid keyed extension can safely advance the anchor.
                self._save_anchor(case.case_id, existing)
        result = chain.append(record)
        self._save_anchor(case.case_id, chain.verify())
        return result

    def events(self, case: CaseRef) -> list[dict]:
        self._authorize("case.read")
        path = case.path / "audit" / "epistemic_events.jsonl"
        if not path.is_file(): return []
        output = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try: output.append(json.loads(line))
            except ValueError: pass
        return output

    def verify_audit(self, case: CaseRef) -> dict:
        self._authorize("audit.verify")
        chain = self._audit_chain(case)
        result = chain.verify()
        anchor = self._anchor(case.case_id)
        if anchor:
            anchor_status = chain.anchor_status(int(anchor.get("sequence") or 0),
                                                str(anchor.get("integrity") or ""))
            result["anchor_status"] = anchor_status
            if anchor_status == "mismatch":
                result["valid"] = False
                result["errors"].append("DPAPI-protected chain head does not match (rollback or replacement)")
        else:
            result["anchor_status"] = "missing"
        return result

    def verify_evidence_integrity(self, case: CaseRef) -> dict:
        self._authorize("audit.verify")
        errors: list[str] = []
        checked = 0
        expected: dict[str, dict] = {}
        for event in self.events(case):
            if event.get("event_type") == "evidence_ingested":
                for item in (event.get("payload") or {}).get("documents", []):
                    if item.get("source"):
                        expected[str(item["source"])] = dict(item)
        originals = (case.path / "01_originals").resolve()
        for name, item in expected.items():
            path = (originals / name).resolve()
            try:
                path.relative_to(originals)
            except ValueError:
                errors.append(f"unsafe original path recorded: {name}")
                continue
            if not path.is_file():
                errors.append(f"missing preserved original: {name}")
                continue
            checked += 1
            if path.stat().st_size != int(item.get("bytes", -1)):
                errors.append(f"size mismatch: {name}")
            elif self._file_sha256(path) != item.get("sha256"):
                errors.append(f"SHA-256 mismatch: {name}")
        return {"valid": not errors, "checked": checked,
                "expected": len(expected), "errors": errors, "algorithm": "SHA-256"}

    def set_retention(self, case: CaseRef, retain_until: str, basis: str) -> dict:
        self._authorize("governance.write", write=True)
        approved = parse_retention_date(retain_until).isoformat()
        reason = str(basis or "").strip()
        if not reason:
            raise ValueError("Record the policy, engagement term, or decision supporting retention")
        data = self._read(case.path)
        governance = dict(data.get("governance") or {})
        governance.update({"retain_until": approved, "retention_basis": reason,
                           "retention_set_at": now(), "retention_set_by": self.access.username})
        data["governance"] = governance
        self._write(case.path, data)
        self.append_event(case, "retention_set", {"retain_until": approved, "basis": reason})
        return governance

    def place_legal_hold(self, case: CaseRef, reason: str) -> dict:
        self._authorize("governance.write", write=True)
        explanation = str(reason or "").strip()
        if not explanation:
            raise ValueError("A legal-hold reason is required")
        data = self._read(case.path)
        governance = dict(data.get("governance") or {})
        governance["legal_hold"] = {"active": True, "reason": explanation,
                                    "placed_at": now(), "placed_by": self.access.username}
        data["governance"] = governance
        self._write(case.path, data)
        self.append_event(case, "legal_hold_placed", {"reason": explanation})
        return governance["legal_hold"]

    def release_legal_hold(self, case: CaseRef, reason: str) -> dict:
        self._authorize("governance.write", write=True)
        explanation = str(reason or "").strip()
        if not explanation:
            raise ValueError("A release reason is required")
        data = self._read(case.path)
        governance = dict(data.get("governance") or {})
        prior = dict(governance.get("legal_hold") or {})
        if not prior.get("active"):
            raise ValueError("No active legal hold exists")
        governance["legal_hold"] = {**prior, "active": False, "released_at": now(),
                                    "released_by": self.access.username,
                                    "release_reason": explanation}
        data["governance"] = governance
        self._write(case.path, data)
        self.append_event(case, "legal_hold_released", {"reason": explanation})
        return governance["legal_hold"]

    def disposition_status(self, case: CaseRef) -> dict:
        self._authorize("case.read")
        return disposition_status(self._read(case.path))

    def case_governance(self, case: CaseRef) -> dict:
        self._authorize("case.read")
        return dict(self._read(case.path).get("governance") or {})

    def purge_archived_case(self, case_id: str, confirmation: str) -> None:
        """Permanently dispose of an eligible archived case after an exact-ID confirmation."""
        self._authorize("governance.write", write=True)
        if str(confirmation) != str(case_id):
            raise ValueError("Permanent disposition requires the exact case ID as confirmation")
        case_dir = self.archive_dir / str(case_id)
        if not case_dir.is_dir():
            raise FileNotFoundError(case_id)
        data = self._read(case_dir)
        status = disposition_status(data)
        if not status["eligible"]:
            raise PermissionError("Case is not eligible for disposition: " + status["reason"])
        case = CaseRef(str(case_id), str(data.get("name")), case_dir, "ARCHIVED",
                       int(data.get("document_count", 0)))
        self.append_event(case, "case_disposition_authorized", status)
        sealed = self.verify_audit(case)
        self._append_workspace_event("archived_case_disposed", {
            "case_id": case.case_id, "case_name": case.name,
            "case_audit_events": sealed["events"], "case_audit_head": sealed["head"],
            "retention_basis": (data.get("governance") or {}).get("retention_basis", "")})
        shutil.rmtree(case_dir)
        self.audit_secret_store.delete(f"audit_hmac_key_v1:{case.case_id}")
        self.audit_secret_store.delete(self._audit_anchor_name(case.case_id))
        self._audit_key_cache.pop(case.case_id, None)
        self._audit_chains.pop(str(case.path.resolve()), None)

    def add_conflict_party(self, case: CaseRef, name: str) -> list[str]:
        self._authorize("governance.write", write=True)
        value = str(name or "").strip()
        if not party_key(value):
            raise ValueError("A party or related-person name is required")
        data = self._read(case.path)
        parties = list(data.get("conflict_parties") or [])
        if party_key(value) not in {party_key(item) for item in parties}:
            parties.append(value)
            data["conflict_parties"] = parties
            self._write(case.path, data)
            self.append_event(case, "conflict_party_added", {"name": value})
        return parties

    def _conflict_cases(self) -> list[dict]:
        cases: list[dict] = []
        for base in (self.cases_dir, self.archive_dir):
            for case_dir in sorted(base.glob("CASE-*")):
                try:
                    data = self._read(case_dir)
                except (OSError, ValueError):
                    continue
                parties = list(data.get("conflict_parties") or parties_from_caption(data.get("name", "")))
                try:
                    matter_map = json.loads((case_dir / "reasoning_corpus" / "matters.json").read_text(encoding="utf-8"))
                    for item in matter_map.get("matters", []):
                        parties.extend([item.get("plaintiff", ""), item.get("defendant", "")])
                except (OSError, ValueError):
                    pass
                cases.append({"case_id": data.get("case_id"), "name": data.get("name"),
                              "parties": [item for item in parties if str(item).strip()]})
        return cases

    def conflict_check(self, names: Iterable[str], exclude_case_id: str = "") -> list[dict]:
        self._authorize("conflicts.check")
        return [item.as_dict() for item in conflict_hits(names, self._conflict_cases(), exclude_case_id)]

    def backup_case(self, case: CaseRef, destination: Path, passphrase: str) -> Path:
        self._authorize("case.backup", write=True)
        destination = Path(destination)
        self.append_event(case, "case_backup_started", {"destination_name": destination.name,
                                                         "encrypted": True})
        created = create_backup(case.path, destination, passphrase,
                                audit_key=self._audit_key(case.case_id))
        self.append_event(case, "case_backup_completed", {
            "destination_name": created.name, "encrypted": True,
            "backup_sha256": self._file_sha256(created), "bytes": created.stat().st_size})
        return created

    def restore_case_backup(self, source: Path, passphrase: str) -> CaseRef:
        self._authorize("case.backup", write=True)
        # The encrypted manifest is inspected by restore_backup, but an archive
        # collision can only be checked after its case ID is known.  Reject a
        # duplicate immediately after extraction and remove the new active copy.
        target, audit_key = restore_backup(Path(source), self.cases_dir, passphrase)
        data = self._read(target)
        if (self.archive_dir / str(data.get("case_id"))).exists():
            shutil.rmtree(target)
            raise FileExistsError(f"An archived case already uses {data.get('case_id')}")
        self.audit_secret_store.set(f"audit_hmac_key_v1:{data.get('case_id')}", audit_key)
        self._audit_key_cache[str(data.get("case_id"))] = audit_key
        restored_chain = AuditChain(target / "audit" / "epistemic_events.jsonl", audit_key)
        restored_verification = restored_chain.verify()
        if not restored_verification["valid"]:
            shutil.rmtree(target)
            raise ValueError("The restored audit chain failed integrity verification")
        self._save_anchor(str(data.get("case_id")), restored_verification)
        data["status"] = "COLLECTING"
        data["restored_at"] = now()
        self._write(target, data)
        self._ensure_folders(target)
        case = CaseRef(str(data["case_id"]), str(data["name"]), target, "COLLECTING",
                       int(data.get("document_count", 0)))
        self.append_event(case, "case_restored", {"source": "encrypted_verified_backup",
                                                   "backup_name": Path(source).name})
        return case

    def validate_filing(self, case: CaseRef, text: str, jurisdiction: str,
                        document_type: str = "filing", metadata: dict | None = None) -> dict:
        self._authorize("filing.validate")
        result = validate_filing(text, jurisdiction, document_type, metadata)
        self.append_event(case, "filing_preflight_completed", {
            "jurisdiction": result["jurisdiction"], "document_type": document_type,
            "passed": result["passed"], "finding_codes": [item["code"] for item in result["findings"]],
            "rule_pack_verified_as_of": result["verified_as_of"],
        })
        return result


    def pin_claim(self, *args, **kwargs):
        result = self._pin_claim_local(*args, **kwargs)
        try:
            case = args[0] if args else kwargs.get("case")
            text = args[1] if len(args) > 1 else kwargs.get("text", "")
            bracket = args[2] if len(args) > 2 else kwargs.get("bracket", "UNVERIFIED")
            sources = args[3] if len(args) > 3 else kwargs.get("sources", ())
            note_type = args[4] if len(args) > 4 else kwargs.get("note_type", "legal_proposition")
            if case is not None:
                name = getattr(bracket, "name", bracket)
                record_legal_extension(case.path, str(text), str(name), sources or (), str(note_type))
        except Exception:
            # The user's original pin operation remains authoritative even if
            # an optional graph-extension write cannot be completed.
            pass
        return result

    def _pin_claim_local(self, case: CaseRef, text: str, bracket: str = "UNVERIFIED", sources: Iterable[str] = (), note_type: str = "claim") -> dict:
        self._authorize("workproduct.write", write=True)
        claim = text.strip()
        if not claim: raise ValueError("A pinned claim or note cannot be empty")
        status = bracket_name(bracket).name
        markers = tuple(dict.fromkeys((*sources, *re.findall(r"\[(?:PSI:|RPM:)?[^\]]+\]", claim))))
        record = {"id": f"NOTE-{datetime.now().strftime('%Y%m%d%H%M%S%f')}", "timestamp": now(),
                  "type": note_type, "text": claim, "bracket": status, "sources": markers}
        self._ensure_folders(case.path)
        with (case.path / "notes" / "pinned_claims.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.append_event(case, "claim_pinned", {"note_id": record["id"], "bracket": status, "sources": markers})
        return record

    def notes(self, case: CaseRef) -> list[dict]:
        path = case.path / "notes" / "pinned_claims.jsonl"
        if not path.is_file(): return []
        output = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try: output.append(json.loads(line))
            except ValueError: pass
        return output

    def attach_authorities(self, case: CaseRef, authorities: Iterable[dict]) -> int:
        self._authorize("research.write", write=True)
        self._ensure_folders(case.path)
        path = case.path / "research" / "attached_authorities.json"
        try: existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError): existing = []
        by_id = {str(item.get("source_id") or item.get("id") or ""): item for item in existing}
        before = len(by_id)
        for authority in authorities:
            key = str(authority.get("source_id") or authority.get("id") or authority.get("title") or "")
            if key: by_id[key] = dict(authority)
        values = list(by_id.values()); temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8"); temporary.replace(path)
        added = len(values) - before
        self.append_event(case, "authorities_attached", {"added": added, "source_ids": list(by_id)})
        return added

    def attached_authorities(self, case: CaseRef) -> list[dict]:
        path = case.path / "research" / "attached_authorities.json"
        try: value = json.loads(path.read_text(encoding="utf-8")); return value if isinstance(value, list) else []
        except (OSError, ValueError): return []

    def search_case(self, case: CaseRef, query: str, limit: int = 50) -> list[dict]:
        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9§'’.-]+", query) if len(term) > 1]
        if not terms: return []
        hits: list[dict] = []
        for path in sorted((case.path / "02_text").glob("*.txt")):
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                lowered = line.lower(); score = sum(lowered.count(term) for term in terms)
                if score: hits.append({"source": path.name, "line": number, "text": line.strip(), "score": score, "kind": "text"})
        for path in sorted((case.path / "04_index").glob("*.rpm.json")):
            rpm = self.document_rpm(case, path)
            for layer in ("top_float", "top_mix", "top_stir"):
                for point in rpm.get(layer, []):
                    value = str(point.get("value") or ""); score = sum(value.lower().count(term) for term in terms)
                    if score: hits.append({"source": path.name, "line": 0, "text": value, "score": score, "kind": layer})
        hits.sort(key=lambda item: (-item["score"], item["source"], item["line"]))
        return hits[:max(1, min(limit, 200))]

    @staticmethod
    def bracket_counts(text: str) -> dict:
        return brackets.count_names(text)

    def case_posture(self, case: CaseRef, matter: str = "") -> List[dict]:
        """Resolve every pleaded legal theory across the three transitions.

        Deterministic and model-free: the finding comes from the case record,
        so it is identical whether or not private AI is installed. Reported
        pressure describes structure only and never promotes a Trust Lock.
        """
        path = case.path / "reasoning_corpus" / "case_sources.jsonl"
        if not path.is_file():
            return []
        records = self._load_records(path)
        # One folder can hold more than one lawsuit. Scoped to a matter, only
        # that suit's documents fold - otherwise the insurance matter reports
        # a malpractice theory and the malpractice matter reports bad faith,
        # and every element is "supported" by the wrong case's evidence.
        if matter:
            records = [item for item in records if str(item.get("matter") or "") == matter]
        if not records:
            return []

        # Theories come from the controlling documents - what is actually
        # pleaded, not what the evidence happens to mention.
        pleading_text = "\n".join(
            str(record["text"]) for record in records
            if doctypes.defines_claims(record.get("role", "unclassified"))
        )
        # Do not infer claims from evidence, an answer, or an order. If the
        # operative pleading is missing, the honest result is no pleaded theory.
        theories = parliament.detect_theories(pleading_text)
        if not theories:
            return []

        # Gather channel observations across the whole record.
        matter: List[parliament.Observation] = []
        matter_asserted: List[parliament.Observation] = []
        by_line: List[tuple] = []
        for record in records:
            text = str(record["text"])
            if self._is_noise(text):
                continue
            source, line = str(record["source"]), int(record.get("line", 0))
            # A pleading asserts; only other documents can support.
            pleaded = doctypes.is_party_assertion(record.get("role", "unclassified"))
            found = parliament.extract_matter(text, source, line)
            (matter_asserted if pleaded else matter).extend(found)
            by_line.append((text, source, line, pleaded))

        findings: List[dict] = []
        for theory in theories:
            supports: Dict[parliament.Channel, parliament.ChannelSupport] = {}
            for element in theory.elements:
                support = parliament.ChannelSupport(element.channel, element)
                if element.channel is parliament.Channel.A:
                    # The kind filter is what keeps a repair estimate from
                    # standing in for extracontractual bad-faith harm.
                    support.observations = [
                        item for item in matter
                        if element.accepts(item)
                        and parliament.pattern_is_affirmed(item.text or item.value, element.patterns)
                    ]
                    support.assertions = [
                        item for item in matter_asserted
                        if element.accepts(item)
                    ]
                else:
                    for text, source, line, pleaded in by_line:
                        if parliament.pattern_is_affirmed(text, element.patterns):
                            observation = parliament.Observation(
                                element.channel, element.key, text[:120], source, line)
                            (support.assertions if pleaded else support.observations).append(observation)
                supports[element.channel] = support

            pressure = 0.0
            try:
                summary = self.rpm_summary(case)
                pressure = float(summary.get("total_pressure", 0.0) or 0.0)
            except Exception:
                pressure = 0.0

            # Repetition is evidence toward the conduct element, never proof
            # of it: only non-pleading documents count, and a pattern raises
            # the point for the user to argue rather than satisfying it.
            pattern = parliament.detect_pattern(
                [(text, source, line) for text, source, line, pleaded in by_line if not pleaded])
            finding = parliament.resolve_theory(theory, supports, pressure, pattern)
            findings.append({
                "theory": theory.key,
                "label": theory.label,
                "headline": finding.headline,
                "detail": finding.detail,
                "resolved": finding.resolved,
                "folded": [channel.label for channel in finding.folded],
                "predicted": finding.predicted.label,
                "predicted_anchor": finding.predicted.anchor,
                "elements": [
                    {
                        "label": element.label,
                        "channel": element.channel.name,
                        "anchor": element.channel.anchor,
                        "supported": supports[element.channel].supported,
                        "asserted_only": supports[element.channel].asserted_only,
                        "citations": supports[element.channel].citations(),
                        "asserted_at": supports[element.channel].assertion_citations(),
                    }
                    for element in theory.elements
                ],
                "pressure": pressure,
                "pressure_note": brackets.NOT_PROMOTED,
                "pattern_events": finding.pattern.events if finding.pattern else 0,
                "pattern_dates": list(finding.pattern.dates) if finding.pattern else [],
                "pattern_citations": list(finding.pattern.citations) if finding.pattern else [],
                "pattern_is_circumstantial": True,
            })
        return findings

    @staticmethod
    def research_terms(question: str, posture: Optional[List[dict]] = None) -> str:
        """Build a corpus query from the question and the pleaded theories.

        The theories matter: a question about "the denial" searches better as
        "denial bad faith unfair claims" than on its own, because the corpus
        indexes doctrine, not one case's vocabulary.
        """
        words = [word for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", question.lower())
                 if word not in Workspace._STOPWORDS]
        terms: List[str] = []
        for word in words:
            if word not in terms:
                terms.append(word)
        for finding in (posture or []):
            label = str(finding.get("label") or "")
            for word in re.findall(r"[A-Za-z]{4,}", label.lower()):
                if word not in terms and word not in Workspace._STOPWORDS:
                    terms.append(word)
        return " ".join(terms[:12])

    def research_for_question(self, case: CaseRef, question: str, corpus,
                              limit: int = 6, jurisdiction: str = "",
                              matter: str = "") -> List[dict]:
        """Retrieve stored authorities relevant to a question.

        Closes the gap where analysis could only see authorities the user had
        already found by hand: the corpus was installed and readable, but
        nothing in the analysis path ever queried it. Results are stored
        records with their stored brackets - never generated citations, never
        promoted.
        """
        if corpus is None:
            return []
        try:
            posture = self.case_posture(case, matter)
        except Exception:
            posture = []
        query = self.research_terms(question, posture)
        if not query:
            return []
        try:
            results = corpus.search(query, limit, jurisdiction)
        except Exception:
            return []
        retrieved: List[dict] = []
        for item in results:
            record = item.as_dict() if hasattr(item, "as_dict") else dict(item)
            record["retrieval"] = "auto"
            record["retrieval_query"] = query
            retrieved.append(record)
        return retrieved

    def claim_tensions(self, case: CaseRef) -> list[dict]:
        claims: list[dict] = list(self.notes(case))
        for event in self.events(case):
            if event.get("event_type") != "analysis_completed": continue
            answer = str(event.get("payload", {}).get("answer") or "")
            for _start, _end, status, claim in brackets.spans(answer):
                claims.append({"text": claim, "bracket": status.name,
                               "sources": re.findall(r"\[[^\]]+\]", claim),
                               "timestamp": event.get("timestamp")})
        groups: dict[str, list[dict]] = {}
        for claim in claims:
            normalized = " ".join(re.findall(r"[a-z0-9]+", str(claim.get("text") or "").lower()))
            if normalized: groups.setdefault(normalized, []).append(claim)
        tensions = []
        for normalized, items in groups.items():
            statuses = sorted({str(item.get("bracket") or "UNVERIFIED") for item in items})
            if len(statuses) > 1: tensions.append({"claim": normalized, "statuses": statuses, "occurrences": items})
        return tensions

    @staticmethod
    def _write_matters(case: CaseRef, matter_map: dict) -> None:
        path = case.path / "reasoning_corpus" / "matters.json"
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(matter_map, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def matters(self, case: CaseRef) -> dict:
        """The distinct lawsuits inside this case, and how they connect."""
        try:
            return json.loads((case.path / "reasoning_corpus" / "matters.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"matters": [], "assignment": {}, "unassigned": [], "connections": []}

    def _matters_with_posture(self, case: CaseRef) -> dict:
        """Each matter carries its own theories, not the whole folder's."""
        found = self.matters(case)
        for entry in found.get("matters", []):
            try:
                entry["posture"] = self.case_posture(case, entry["matter_id"])
            except Exception:
                entry["posture"] = []
        return found


    def case_brief(self, *args, **kwargs):
        brief = self._case_brief_local(*args, **kwargs)
        case = args[0] if args else kwargs.get("case")
        if isinstance(brief, dict) and case is not None:
            brief["claims_handoff"] = handoff_summary(case.path)
            brief["legal_graph_extensions"] = read_legal_extensions(case.path)
            brief.setdefault("guards", []).append(
                "PAi Legal may extend the map but never rewrites the PAi Claims base case graph."
            )
        return brief

    def _case_brief_local(self, case: CaseRef, analysis_text: str = "", corpus=None,
                   jurisdiction: str = "", mode: str = "lawyer", matter: str = "") -> dict:
        """Structured, source-traced case brief for an external drafting tool.

        The Markdown and PDF exports are prose for a human reader. A drafting
        model needs the structure instead: which theories are pleaded, which
        elements the record supports, the exact lines behind each one, and
        what is missing. Handing over 70 documents produces a worse draft than
        handing over this.

        Everything is copied as stored. Trust Locks are never promoted here,
        no finding is invented, and the gaps are reported as gaps so the
        drafter cannot quietly write around them.
        """
        posture = self.case_posture(case, matter)
        summary = self.rpm_summary(case)
        records = self._load_records(case.path / "reasoning_corpus" / "case_sources.jsonl")

        by_source: Dict[str, dict] = {}
        for record in records:
            source = str(record.get("source") or "")
            if not source or self._is_noise(str(record.get("text") or "")):
                continue
            if matter and str(record.get("matter") or "") != matter:
                continue
            entry = by_source.setdefault(source, {
                "source": source,
                "role": record.get("role", "unclassified"),
                "role_label": doctypes.label_of(record.get("role", "unclassified")),
                "rank": int(record.get("rank", 99)),
                "bracket": record.get("bracket", "UNVERIFIED"),
                "rpm": record.get("rpm", {}),
                "lines": [],
            })
            entry["lines"].append({"line": record.get("line"), "text": record.get("text")})

        documents = sorted(by_source.values(), key=lambda item: (item["rank"], item["source"]))
        brief = {
            "schema_version": 1,
            "generator": "PAi Legal",
            "exported_at": now(),
            "case": {"case_id": case.case_id, "name": case.name, "status": case.status},
            "disclaimer": DISCLAIMER_TEXT,
            "guards": [
                "Relational pressure never promotes or demotes a Trust Lock.",
                "A pleading asserts an element; it cannot support it.",
                "Authorities are stored records, never generated citations.",
                "Findings are computed from the record, not by a language model.",
            ],
            "posture": posture,
            "documents": documents,
            "matter_scope": matter or "all",
            "matters": self._matters_with_posture(case),
            "transition_map": self._brief_map(case),
            "authorities": self._brief_authorities(case, posture, corpus, jurisdiction),
            "notes": self.notes(case),
            "tensions": self.claim_tensions(case),
            "rpm_summary": summary,
            "analysis_text": analysis_text,
        }
        if mode == "prose":
            brief.update(self._prose_layer(case, posture, documents))
            brief["mode"] = "prose"
        else:
            brief["mode"] = "lawyer"
        return brief

    @staticmethod
    def _prose_layer(case: CaseRef, posture: List[dict], documents: List[dict]) -> dict:
        """Plain-English layer over the same findings.

        Renames and narrates; never softens. A gap stays a gap, because telling
        someone what their case is missing before a judge does is the whole
        point of computing it.
        """
        case_type = plainspeak.infer_case_type(posture)
        return {
            "plain": {
                "narrative": plainspeak.narrative(case.name, documents, posture, case_type),
                "your_claims": [{
                    "claim": plainspeak.plain_theory(item.get("theory"), item.get("label", "")),
                    "formal_name": item.get("label"),
                    "complete": bool(item.get("resolved")),
                } for item in posture],
                "you_still_need": plainspeak.still_needed(posture),
                "orientation": plainspeak.orientation(case_type),
                "your_documents": [{
                    "file": item["source"],
                    "what_it_is": doctypes.plain_label(item.get("role", "unclassified")),
                } for item in documents],
            },
        }

    def _brief_map(self, case: CaseRef) -> dict:
        """The Case Map's computed structure, without the whole node tree.

        The projections and root transitions are what a drafter argues from;
        the recursive zoom layers are for the UI and would swamp a prompt.
        """
        try:
            built = self.case_transition_map(case)
        except Exception:
            return {}
        try:
            view = built.view()
            edges = [{
                "source": getattr(edge, "source", ""),
                "target": getattr(edge, "target", ""),
                "channel": getattr(edge, "channel", ""),
                "label": getattr(edge, "label", ""),
                "bracket": getattr(edge, "bracket", "UNVERIFIED"),
                "pressure": getattr(edge, "pressure", 0),
            } for edge in list(view.edges)[:40]]
        except Exception:
            edges = []
        return {
            "deterministic_seed": getattr(built, "deterministic_seed", ""),
            "input_signature": getattr(built, "input_signature", ""),
            "replay_signature": getattr(built, "replay_signature", ""),
            "transitions": edges,
            "projections": [{
                "role": getattr(item, "role", ""),
                "headline": getattr(item, "headline", ""),
                "detail": getattr(item, "detail", ""),
                "channel": getattr(item, "channel", ""),
                "bracket": getattr(item, "bracket", "UNVERIFIED"),
                "pressure": getattr(item, "pressure", 0),
            } for item in getattr(built, "projections", [])],
            "guard": "Structural forecast from the stored record. Not a prediction of a "
                     "judge, jury, settlement or court outcome.",
        }

    def _brief_authorities(self, case: CaseRef, posture: List[dict],
                           corpus=None, jurisdiction: str = "") -> List[dict]:
        """Attached authorities, widened by a corpus search per pleaded theory.

        Limiting the brief to authorities the user already attached means a
        doctrine they did not know to look for never reaches the drafter. Each
        theory queries the corpus once; results are stored records carrying
        their stored brackets, tagged so they stay distinguishable from
        authorities the user chose deliberately.
        """
        attached = list(self.attached_authorities(case))
        for item in attached:
            item.setdefault("retrieval", "attached")
        if corpus is None or not posture:
            return attached
        known = {str(item.get("source_id") or item.get("id") or item.get("title") or "")
                 for item in attached}
        for finding in posture:
            query = self.research_terms(str(finding.get("label") or ""), [finding])
            if not query:
                continue
            try:
                results = corpus.search(query, 4, jurisdiction)
            except Exception:
                continue
            for result in results:
                record = result.as_dict() if hasattr(result, "as_dict") else dict(result)
                key = str(record.get("source_id") or record.get("id") or record.get("title") or "")
                if not key or key in known:
                    continue
                record["retrieval"] = "auto"
                record["retrieved_for"] = finding.get("theory")
                attached.append(record)
                known.add(key)
        return attached

    def export_case_package(self, case: CaseRef, destination: Path, analysis_text: str = "", authorities: Iterable[dict] = (), corpus=None, jurisdiction: str = "", matter: str = "") -> Path:
        self._authorize("case.export", write=True)
        destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
        summary = self.rpm_summary(case); attached = self.attached_authorities(case)
        authority_map = {str(item.get("source_id") or item.get("id") or item.get("title") or ""): item for item in attached}
        for item in authorities:
            key = str(item.get("source_id") or item.get("id") or item.get("title") or "")
            if key: authority_map[key] = dict(item)
        authority_rows = list(authority_map.values())
        lines = [f"# PAi Legal Case Record — {case.name}", "", f"Case ID: `{case.case_id}`",
                 f"Matter scope: `{matter or 'all'}`", f"Exported: {now()}", "", DISCLAIMER_TEXT,
                 "", "## Epistemic legend", "", brackets.legend_markdown(), "",
                 "## Relational Pressure Map", "", f"- Float observations: {summary['float_points']}", f"- Mix relations: {summary['mix_points']}", f"- Stir recurrences: {summary['stir_points']}", f"- Total pressure: {summary['total_pressure']}", ""]
        if summary["top_relations"]:
            lines += ["### Top relations", ""] + [f"- {item.get('value','')} — pressure {item.get('pressure',0)}" for item in summary["top_relations"]] + [""]
        transition_map = self.case_transition_map(case)
        lines += [
            "## Precognitive Case Map", "",
            f"- Deterministic seed: `{transition_map.deterministic_seed}`",
            f"- Input signature: `{transition_map.input_signature}`",
            f"- Replay signature: `{transition_map.replay_signature}`",
            f"- Root transitions: {len(transition_map.view().edges)}",
            f"- Semantic zoom views: {len(transition_map.views)}",
            "- Guard: Relational pressure cannot promote a Trust Lock.", "",
            "### Parliament projections", "",
        ]
        for projection in transition_map.projections:
            lines += [
                f"- **{projection.role}: {projection.headline}** — {projection.detail}",
                f"  Channel: {projection.channel} · Trust Lock: {projection.bracket} · pressure {projection.pressure}",
            ]
        lines.append("")
        lines += ["## Document RPM records", ""]
        rpm_paths = sorted((case.path / "04_index").glob("*.rpm.json"))
        if rpm_paths:
            for rpm_path in rpm_paths:
                record = self.document_rpm(case, rpm_path)
                lines += [f"### {record.get('source') or rpm_path.stem}",
                          f"- Float/Mix/Stir: {record.get('float_points',0)}/{record.get('mix_points',0)}/{record.get('stir_points',0)}",
                          f"- Pressure: {record.get('total_pressure',0)} · case contribution {record.get('case_pressure_percent',0)}%",
                          f"- Pattern signature: `{record.get('pattern_signature','')}`", ""]
        else:
            lines += ["No document RPM records are available.", ""]
        lines += ["## Attached authorities", ""]
        for item in authority_rows:
            lines += [f"### {item.get('title','Stored authority')}", f"- Source: `{item.get('source_id', item.get('id',''))}`", f"- Trust Lock: {item.get('bracket','UNVERIFIED')}", f"- Jurisdiction / year: {item.get('jurisdiction','—')} / {item.get('year','—')}", f"- Float/Mix/Stir: {item.get('float_points',0)}/{item.get('mix_points',0)}/{item.get('stir_points',0)} · pressure {item.get('total_pressure',0)}", f"- Pattern signature: `{item.get('pattern_signature','')}`", f"- Citation: {item.get('citation','')}", "", str(item.get('excerpt','')), ""]
        lines += ["## Pinned claims and notes", ""]
        for item in self.notes(case): lines += [f"- {wrap_claim(str(item.get('text','')), BracketType[str(item.get('bracket','UNVERIFIED'))])}  ", f"  Sources: {', '.join(item.get('sources') or [])} · {item.get('timestamp','')}"]
        lines += ["", "## Analysis record", "", analysis_text or "No analysis chat supplied to this export.", "", f"_{brackets.summary(analysis_text)}_", "", "## Epistemic audit events", ""]
        for event in self.events(case): lines.append(f"- {event.get('timestamp')} · {event.get('event_type')} · `{event.get('event_id')}`")
        markdown = "\n".join(lines)
        if destination.suffix.lower() == ".json":
            mode = "prose" if "plain" in destination.stem.lower() or "diy" in destination.stem.lower() else "lawyer"
            brief = self.case_brief(case, analysis_text, corpus=corpus,
                                    jurisdiction=jurisdiction, mode=mode, matter=matter)
            brief["authorities"] = authority_rows or brief["authorities"]
            destination.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
            self.append_event(case, "case_exported", {"path": str(destination), "format": ".json"})
            return destination
        if destination.suffix.lower() == ".pdf": self._write_pdf(destination, markdown, case.name)
        else: destination.write_text(markdown, encoding="utf-8")
        self.append_event(case, "case_exported", {"path": str(destination), "format": destination.suffix.lower()})
        return destination

    @staticmethod
    def _write_pdf(destination: Path, markdown: str, title: str) -> None:
        from html import escape
        import reportlab
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        font_dir = Path(reportlab.__file__).resolve().parent / "fonts"
        pdfmetrics.registerFont(TTFont("PAiVera", str(font_dir / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("PAiVeraBold", str(font_dir / "VeraBd.ttf")))
        styles = getSampleStyleSheet(); body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="PAiVera", fontSize=8.7, leading=12.5, textColor=HexColor("#132238"), spaceAfter=5)
        h1 = ParagraphStyle("H1", parent=styles["Title"], fontName="PAiVeraBold", fontSize=16, leading=20, textColor=HexColor("#0B1B33"), alignment=0, spaceAfter=12, keepWithNext=True)
        h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="PAiVeraBold", fontSize=11.5, leading=14, textColor=HexColor("#18A7FF"), spaceBefore=10, spaceAfter=6, keepWithNext=True)
        h3 = ParagraphStyle("H3", parent=h2, fontSize=10.2, leading=13, spaceBefore=7, spaceAfter=4, keepWithNext=True)
        story = []
        for line in markdown.splitlines():
            if not line: story.append(Spacer(1, 5)); continue
            if line.strip().startswith("| ---"): continue
            value = line.strip()
            if value.startswith("|") and value.endswith("|"):
                value = " — ".join(cell.strip() for cell in value.strip("|").split("|"))
            value = value.strip("_")
            clean = escape(value.lstrip("#- >").replace("`", ""))
            style = h1 if line.startswith("# ") else h3 if line.startswith("### ") else h2 if line.startswith("## ") else body
            story.append(Paragraph(clean, style))
        document = SimpleDocTemplate(str(destination), pagesize=letter, rightMargin=.65*inch, leftMargin=.65*inch, topMargin=.6*inch, bottomMargin=.6*inch, title=f"PAi Legal — {title}")
        document.build(story)


DISCLAIMER_TEXT = "PAi Legal provides legal information and work-product assistance, not legal advice. Verify authorities and current law."
