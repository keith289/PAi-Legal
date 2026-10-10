"""Retention, legal-hold, and deterministic conflict-control helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable


ENTITY_SUFFIXES = {
    "llc", "llp", "pllc", "pc", "inc", "incorporated", "corp", "corporation",
    "company", "co", "ltd", "limited", "exchange", "association",
}


def party_key(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(value or "").lower())
    while tokens and tokens[-1] in ENTITY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def parties_from_caption(value: str) -> list[str]:
    parts = re.split(r"\s+(?:v\.?|versus)\s+", str(value or ""), maxsplit=1, flags=re.I)
    return [part.strip(" ,-_") for part in parts if part.strip(" ,-_")] if len(parts) == 2 else []


@dataclass(frozen=True)
class ConflictHit:
    queried_name: str
    matched_name: str
    case_id: str
    case_name: str
    confidence: str
    reason: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def conflict_hits(query_names: Iterable[str], cases: Iterable[dict],
                  exclude_case_id: str = "") -> list[ConflictHit]:
    """Flag exact normalized names and strong surname/entity overlap.

    This is a screening aid, not a conflicts determination.  It deliberately
    returns possible matches for human review and never clears a representation.
    """
    hits: list[ConflictHit] = []
    seen = set()
    for query in query_names:
        query_normalized = party_key(query)
        if not query_normalized:
            continue
        query_tokens = set(query_normalized.split())
        for case in cases:
            if str(case.get("case_id")) == exclude_case_id:
                continue
            for candidate in case.get("parties", []):
                candidate_normalized = party_key(candidate)
                if not candidate_normalized:
                    continue
                candidate_tokens = set(candidate_normalized.split())
                confidence = ""
                reason = ""
                if query_normalized == candidate_normalized:
                    confidence, reason = "exact", "same normalized party name"
                elif len(query_tokens) >= 2 and len(candidate_tokens) >= 2:
                    overlap = query_tokens & candidate_tokens
                    ratio = len(overlap) / min(len(query_tokens), len(candidate_tokens))
                    if ratio >= 0.8:
                        confidence, reason = "possible", "strong token overlap"
                if confidence:
                    identity = (query_normalized, candidate_normalized, str(case.get("case_id")))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    hits.append(ConflictHit(str(query), str(candidate), str(case.get("case_id")),
                                            str(case.get("name")), confidence, reason))
    return hits


def parse_retention_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("Retention dates must use YYYY-MM-DD") from exc


def disposition_status(metadata: dict, today: date | None = None) -> dict:
    current = today or datetime.now(timezone.utc).date()
    governance = dict(metadata.get("governance") or {})
    hold = dict(governance.get("legal_hold") or {})
    retained_until = str(governance.get("retain_until") or "")
    if hold.get("active"):
        return {"eligible": False, "reason": "legal hold active", "retain_until": retained_until,
                "legal_hold": True}
    if not retained_until:
        return {"eligible": False, "reason": "no approved disposition date", "retain_until": "",
                "legal_hold": False}
    eligible = current >= parse_retention_date(retained_until)
    return {"eligible": eligible,
            "reason": "retention period elapsed" if eligible else "retention period still running",
            "retain_until": retained_until, "legal_hold": False}
