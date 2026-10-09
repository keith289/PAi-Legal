"""Declarative jurisdiction rule packs and deterministic filing checks.

Checks identify mechanical omissions and privacy patterns.  They do not
calculate deadlines, decide legal sufficiency, or replace current local rules.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path


ALIASES = {
    "federal": "US-FEDERAL-CIVIL", "us federal": "US-FEDERAL-CIVIL",
    "us-federal-civil": "US-FEDERAL-CIVIL", "fed": "US-FEDERAL-CIVIL",
    "ga": "GA-SUPERIOR-CIVIL", "georgia": "GA-SUPERIOR-CIVIL",
    "ga superior": "GA-SUPERIOR-CIVIL", "ga-superior-civil": "GA-SUPERIOR-CIVIL",
}


@dataclass(frozen=True)
class FilingFinding:
    severity: str
    code: str
    message: str
    authority: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _pack_directory():
    return resources.files("pai_legal").joinpath("resources", "jurisdictions")


def available_rule_packs() -> list[dict]:
    packs = []
    for item in _pack_directory().iterdir():
        if item.name.endswith(".json"):
            with item.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            packs.append({key: value.get(key) for key in
                          ("id", "label", "verified_as_of", "source_url")})
    return sorted(packs, key=lambda item: str(item.get("label")))


def load_rule_pack(jurisdiction: str) -> dict:
    key = str(jurisdiction or "").strip()
    identifier = ALIASES.get(key.lower(), key.upper())
    if not re.fullmatch(r"[A-Z0-9-]+", identifier):
        raise ValueError("Jurisdiction identifiers may contain only letters, numbers, and hyphens")
    candidate = _pack_directory().joinpath(identifier + ".json")
    if not candidate.is_file():
        raise ValueError(f"No installed rule pack matches {jurisdiction!r}")
    with candidate.open("r", encoding="utf-8") as handle:
        pack = json.load(handle)
    if pack.get("schema_version") != 1 or pack.get("id") != identifier:
        raise ValueError("The jurisdiction rule pack is invalid")
    return pack


def validate_filing(text: str, jurisdiction: str, document_type: str = "filing",
                    metadata: dict | None = None) -> dict:
    pack = load_rule_pack(jurisdiction)
    body = str(text or "")
    fields = dict(metadata or {})
    kind = str(document_type or "filing").strip().lower()
    findings: list[FilingFinding] = []
    for rule in pack.get("rules", []):
        applies = [str(value).lower() for value in rule.get("applies_to", ["*"])]
        if "*" not in applies and kind not in applies:
            continue
        rule_type = rule.get("type")
        code = str(rule.get("code") or "RULE")
        severity = str(rule.get("severity") or "warning")
        authority = str(rule.get("authority") or "")
        if rule_type == "required_pattern" and not re.search(str(rule.get("pattern") or ""), body,
                                                               re.I | re.M):
            findings.append(FilingFinding(severity, code, str(rule.get("message")), authority))
        elif rule_type == "forbidden_pattern" and re.search(str(rule.get("pattern") or ""), body,
                                                               re.I | re.M):
            findings.append(FilingFinding(severity, code, str(rule.get("message")), authority))
        elif rule_type == "metadata_required" and not fields.get(str(rule.get("field") or "")):
            findings.append(FilingFinding(severity, code, str(rule.get("message")), authority))
    findings.append(FilingFinding(
        "warning", "VERIFY-CURRENT-LOCAL-RULES",
        "Verify the current court-specific local rules, standing orders, filing method, fees, service, and deadlines before filing.",
        str(pack.get("source_url") or "")))
    return {
        "jurisdiction": pack["id"], "label": pack["label"],
        "verified_as_of": pack.get("verified_as_of", ""),
        "source_url": pack.get("source_url", ""),
        "official_forms": list(pack.get("official_forms") or []),
        "document_type": kind, "passed": not any(item.severity == "error" for item in findings),
        "findings": [item.as_dict() for item in findings],
        "disclaimer": "Mechanical preflight only; not a legal-sufficiency determination.",
    }
