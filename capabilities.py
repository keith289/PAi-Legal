"""Capability discovery for standalone PAi Legal and optional PSi Legal."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .procutil import hidden
from .netsecurity import bearer_headers, require_loopback_url
from .hardware import app_data_root
from .security import SecretStore, SecretStoreUnavailable

PSI_LEGAL_STORE_ID = "9NHNVPTD93XT"
PSI_LEGAL_FAMILY_HINT = "PAiLuton.PSiLegal"

DEFAULT_LFM_URL = "http://127.0.0.1:8081"
DEFAULT_PSI_URL = "http://127.0.0.1:8082"


def _vault_token(name: str) -> str:
    try:
        return SecretStore(app_data_root()).get(name) or ""
    except (SecretStoreUnavailable, OSError, ValueError):
        return ""


def store_link(product_id: str) -> str:
    return f"ms-windows-store://pdp/?productid={product_id}"


class Capability(str, Enum):
    WORKSPACE = "workspace"
    ANALYSIS = "analysis"
    CORPUS = "corpus"


@dataclass
class Probe:
    where: str
    outcome: str
    detail: str = ""


@dataclass
class CapabilityStatus:
    capability: Capability
    available: bool
    summary: str
    provider: Optional[str] = None
    resources: Dict[str, str] = field(default_factory=dict)
    remedy: Optional[str] = None
    remedy_link: Optional[str] = None
    probes: List[Probe] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "capability": self.capability.value,
            "available": self.available,
            "summary": self.summary,
            "provider": self.provider,
            "resources": dict(self.resources),
            "remedy": self.remedy,
            "remedy_link": self.remedy_link,
            "probes": [vars(p) for p in self.probes],
        }


@dataclass
class CapabilityReport:
    statuses: Dict[Capability, CapabilityStatus]

    def has(self, capability: Capability) -> bool:
        status = self.statuses.get(capability)
        return bool(status and status.available)

    @property
    def mode(self) -> str:
        analysis = self.has(Capability.ANALYSIS)
        corpus = self.has(Capability.CORPUS)
        if analysis and corpus:
            return "Full — analysis and case-law search"
        if corpus:
            return "Research — case-law search, no analysis"
        if analysis:
            return "Analysis — no case-law corpus installed"
        return "Workspace — cases and evidence only"

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "capabilities": {
                key.value: value.as_dict() for key, value in self.statuses.items()
            },
        }


def _readable(path: Path) -> tuple[bool, str]:
    try:
        with path.open("rb") as handle:
            handle.read(1)
        return True, ""
    except PermissionError as exc:
        return False, f"permission denied: {exc}"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _healthy(url: str, paths: Iterable[str], token: str = "") -> tuple[bool, str]:
    for suffix in paths:
        target = url.rstrip("/") + suffix
        try:
            request = urllib.request.Request(target, headers=bearer_headers(token))
            with urllib.request.urlopen(request, timeout=0.8) as response:
                if 200 <= response.status < 300:
                    return True, target
        except Exception:
            continue
    return False, ""


def _appx_packages(name_hint: str) -> List[Dict[str, str]]:
    if os.name != "nt":
        return []
    script = (
        f"Get-AppxPackage *{name_hint}* | "
        "Select-Object Name,PackageFamilyName,InstallLocation,Version | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
            **hidden(),
        )
        if result.returncode or not result.stdout.strip():
            return []
        value = json.loads(result.stdout)
        return value if isinstance(value, list) else [value]
    except Exception:
        return []


def _provider_manifests(filename: str) -> List[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    override = os.environ.get("PAI_PROVIDER_DIR")
    out: List[Path] = []
    if override:
        out.append(Path(override) / filename)
    if str(local):
        # Current deployment and the forward-compatible provider contract.
        out.extend([
            local / "PAiLuton" / "Providers" / filename,
            local / "PrivateAI" / "config" / filename,
        ])
    return out


def _read_manifest(candidates: Iterable[Path], probes: List[Probe]) -> tuple[Optional[dict], Optional[Path]]:
    for candidate in candidates:
        if not candidate.is_file():
            probes.append(Probe(str(candidate), "absent"))
            continue
        ok, why = _readable(candidate)
        if not ok:
            probes.append(Probe(str(candidate), "unreadable", why))
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            probes.append(Probe(str(candidate), "found"))
            return payload, candidate
        except (OSError, ValueError) as exc:
            probes.append(Probe(str(candidate), "error", str(exc)))
    return None, None


def detect_analysis() -> CapabilityStatus:
    probes: List[Probe] = []
    from .local_ai import installation_path, read_installation
    url = os.environ.get("PAI_LEGAL_AI_URL", "")
    token = os.environ.get("PAI_LEGAL_AI_KEY", "") or _vault_token("private_ai_session_token")
    if url:
        try:
            url = require_loopback_url(url, "Private AI")
            live, endpoint = _healthy(url, ("/health", "/v1/models"), token) if token else (False, "")
            probes.append(Probe(url, "found" if live else "untrusted",
                                "authenticated PAi Legal private AI" if token else "missing session token"))
            if live:
                return CapabilityStatus(
                    Capability.ANALYSIS, True, "PAi Legal private AI is ready.",
                    provider="PAi Legal",
                    resources={"api_url": url, "api_key": token, "health_endpoint": endpoint},
                    probes=probes,
                )
        except ValueError as exc:
            probes.append(Probe(url, "blocked", str(exc)))

    manifest = installation_path()
    payload = read_installation()
    probes.append(Probe(str(manifest), "found" if payload else "absent", "private AI installation"))
    if payload:
        model = Path(str(payload.get("model_path") or payload.get("model") or ""))
        runtime = Path(str(payload.get("runtime_path") or payload.get("runtime") or ""))
        missing: List[str] = []
        resources: Dict[str, str] = {}
        for label, path in (("model", model), ("runtime", runtime)):
            if not str(path) or str(path) == ".":
                missing.append(f"{label} path not set")
                continue
            ok, why = _readable(path)
            probes.append(Probe(str(path), "found" if ok else "unreadable", why or label))
            if ok:
                resources[f"{label}_path"] = str(path)
            else:
                missing.append(f"{label} unavailable")
        if not missing:
            return CapabilityStatus(
                Capability.ANALYSIS,
                True,
                f"Private model ready: {payload.get('model_label', model.name)}.",
                provider=str(manifest),
                resources={**resources, "context": str(payload.get("context") or 8192)},
                probes=probes,
            )

    return CapabilityStatus(
        Capability.ANALYSIS,
        False,
        "Private AI has not been set up yet.",
        remedy="Run PAi Legal Private AI Setup. The model stays on this device.",
        probes=probes,
    )


def _corpus_roots(extra_roots: Optional[Iterable[Path]]) -> List[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roots: List[Path] = []
    env_roots = os.environ.get("PSI_CORPUS_ROOTS", "")
    if env_roots:
        roots.extend(Path(item) for item in env_roots.split(os.pathsep) if item)
    if str(local):
        roots.extend([
            local / "PSiLegal" / "corpus",
            local / "PAiLuton" / "PSiLegal" / "corpus",
        ])
    roots.extend(Path(item) for item in (extra_roots or []))
    return roots


def detect_corpus(extra_roots: Optional[Iterable[Path]] = None) -> CapabilityStatus:
    probes: List[Probe] = []
    url = os.environ.get("PSI_LEGAL_URL", "")
    token = os.environ.get("PSI_LEGAL_TOKEN", "") or _vault_token("psi_legal_api_token")
    if url:
        try:
            url = require_loopback_url(url, "PSi Legal")
            live, endpoint = _healthy(url, ("/health", "/v1/corpus/stats"), token) if token else (False, "")
            probes.append(Probe(url, "found" if live else "untrusted",
                                "authenticated PSi Legal service" if token else "missing session token"))
            if live:
                return CapabilityStatus(
                    Capability.CORPUS, True, "PSi Legal case-law service ready.",
                    provider="PSi Legal",
                    resources={"api_url": url, "api_token": token, "health_endpoint": endpoint},
                    probes=probes,
                )
        except ValueError as exc:
            probes.append(Probe(url, "blocked", str(exc)))

    payload, manifest = _read_manifest(_provider_manifests("psi-legal.json"), probes)
    if payload:
        api_url = str(payload.get("api_url") or "")
        credential_name = str(payload.get("credential_name") or "psi_legal_api_token")
        api_token = _vault_token(credential_name)
        if payload.get("api_token"):
            probes.append(Probe(str(manifest), "blocked",
                                "plaintext api_token is not accepted; publish credential_name and store it in the DPAPI vault"))
        if api_url and api_token:
            try:
                api_url = require_loopback_url(api_url, "PSi Legal")
            except ValueError as exc:
                probes.append(Probe(api_url, "blocked", str(exc)))
                api_url = ""
            live, endpoint = _healthy(api_url, ("/health", "/v1/corpus/stats"), api_token) if api_url else (False, "")
            probes.append(Probe(api_url, "found" if live else "absent", "authenticated manifest endpoint"))
            if live:
                return CapabilityStatus(
                    Capability.CORPUS,
                    True,
                    "PSi Legal case-law service ready.",
                    provider=str(manifest),
                    resources={"api_url": api_url, "api_token": api_token, "health_endpoint": endpoint},
                    probes=probes,
                )

    roots = _corpus_roots(extra_roots)
    if payload:
        roots.extend(Path(item) for item in payload.get("corpus_roots", []))
        roots.extend(Path(item) for item in payload.get("shards", []))

    found: List[Path] = []
    blocked: List[Path] = []
    for root in roots:
        candidates = [root] if root.is_file() else []
        if root.is_dir():
            try:
                candidates.extend(sorted(root.rglob("casehold_*.db")))
                candidates.extend(sorted(root.rglob("*.idx")))
            except OSError as exc:
                probes.append(Probe(str(root), "error", str(exc)))
                continue
        if not candidates:
            probes.append(Probe(str(root), "absent", "no supported corpus files"))
            continue
        for candidate in candidates:
            ok, why = _readable(candidate)
            probes.append(Probe(str(candidate), "found" if ok else "unreadable", why))
            (found if ok else blocked).append(candidate)
        if found:
            break

    if found:
        return CapabilityStatus(
            Capability.CORPUS,
            True,
            f"PSi Legal corpus available ({len(found)} file(s)).",
            provider=str(found[0].parent),
            resources={"shards": os.pathsep.join(str(item) for item in found)},
            probes=probes,
        )
    if blocked:
        summary = "PSi Legal is installed but its corpus is blocked by package isolation."
        remedy = "Open PSi Legal and enable its local corpus provider."
    else:
        summary = "PSi Legal case-law corpus is not available."
        remedy = "Install PSi Legal to add the searchable case-law corpus."
    return CapabilityStatus(
        Capability.CORPUS,
        False,
        summary,
        remedy=remedy,
        remedy_link=store_link(PSI_LEGAL_STORE_ID),
        probes=probes,
    )


def detect_all(extra_corpus_roots: Optional[Iterable[Path]] = None) -> CapabilityReport:
    return CapabilityReport({
        Capability.WORKSPACE: CapabilityStatus(
            Capability.WORKSPACE,
            True,
            "Case and evidence workspace ready.",
            provider="PAi Legal",
        ),
        Capability.ANALYSIS: detect_analysis(),
        Capability.CORPUS: detect_corpus(extra_corpus_roots),
    })


def diagnostics(report: CapabilityReport) -> str:
    lines = [f"PAi Legal — {report.mode}", "=" * 64]
    for capability, status in report.statuses.items():
        lines.append(f"\n[{'ON ' if status.available else 'OFF'}] {capability.value.upper()}: {status.summary}")
        if status.provider:
            lines.append(f"      provider: {status.provider}")
        for key, value in status.resources.items():
            lines.append(f"      {key}: {value}")
        if status.remedy:
            lines.append(f"      remedy: {status.remedy}")
            lines.append(f"      link:   {status.remedy_link}")
        for probe in status.probes:
            detail = f" — {probe.detail}" if probe.detail else ""
            lines.append(f"      [{probe.outcome}] {probe.where}{detail}")
    return "\n".join(lines)
