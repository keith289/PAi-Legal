"""Plain-English layer for people representing themselves.

The lawyer brief is correct and dense. A self-represented person needs the same
facts with the jargon removed: what these documents are, what the case is
about, and what is still missing.

Nothing here changes a finding. It renames and narrates what the deterministic
engine already computed. A gap is still a gap - softening it would defeat the
point, because the whole value of the finding is telling someone what their
case is missing before a judge does.

## On the orientation checklists

Court requirements are jurisdiction-specific: an answer deadline in a Georgia
magistrate court is not Florida's, and local rules vary by county. The lists
below are orientation - the kinds of things these cases usually turn on - not
requirements. Every one carries a verify-with-your-court instruction, and none
states a deadline, a page limit, or a filing fee.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

VERIFY = ("Check this against your own court's rules and deadlines. Rules differ "
          "by state, by county, and sometimes by judge.")

NOT_ADVICE = ("This is information to help you organize, not legal advice. "
              "A lawyer licensed in your state can tell you what applies to you.")

# Case types a self-represented person actually recognizes.
CASE_TYPES: Dict[str, dict] = {
    "insurance": {
        "label": "Insurance claim dispute",
        "about": "An insurance company denied, underpaid, or delayed a claim.",
        "usually_turns_on": [
            "The policy itself - what it covers and what it excludes.",
            "What you told the insurer and when, and what they told you back.",
            "An estimate or invoice showing what the loss actually cost.",
            "Every letter or email where they denied, delayed, or paid less.",
        ],
    },
    "eviction": {
        "label": "Eviction / housing",
        "about": "A landlord is trying to remove you, or there is a dispute over the tenancy.",
        "usually_turns_on": [
            "The lease, and any written notice you were given.",
            "Proof of rent paid - receipts, bank records, money orders.",
            "Photos or reports of conditions, if repairs are part of the dispute.",
            "Dates: eviction cases move faster than almost any other kind.",
        ],
    },
    "debt": {
        "label": "Debt collection",
        "about": "Someone is suing you over a debt, or a collector is pursuing you.",
        "usually_turns_on": [
            "Whether the company suing you can show it actually owns the debt.",
            "The original agreement, and a statement showing how the amount was calculated.",
            "Any letters you sent disputing it, and their replies.",
            "How old the debt is - some debts become too old to sue on.",
        ],
    },
    "family": {
        "label": "Family / custody / support",
        "about": "A dispute over custody, visitation, support, or a family court order.",
        "usually_turns_on": [
            "Any existing court order, and exactly what it says.",
            "A record of what actually happened - dates, times, who was present.",
            "Income and expense documents, if money is part of it.",
            "Whether the court requires mediation before it will hear you.",
        ],
    },
    "small_claims": {
        "label": "Small claims",
        "about": "A money dispute small enough for a simplified court.",
        "usually_turns_on": [
            "Proof the other side owed you something - a contract, invoice, or agreement.",
            "Proof of the amount, with receipts or estimates.",
            "Proof you asked them to pay before suing.",
            "The dollar limit for small claims in your state.",
        ],
    },
    "malpractice": {
        "label": "Professional malpractice",
        "about": "A professional you hired failed to do their job properly.",
        "usually_turns_on": [
            "The agreement that hired them.",
            "What they were supposed to do and what they did instead.",
            "What it cost you - often the value of what you lost because of it.",
            "Many states require an expert's sworn statement filed with the case.",
        ],
    },
    "other": {
        "label": "Something else",
        "about": "",
        "usually_turns_on": [
            "The document that created the obligation - a contract, policy, or agreement.",
            "A clear record of what happened, with dates.",
            "Proof of what it cost you.",
        ],
    },
}

# Which case type a set of pleaded theories suggests.
_THEORY_TO_CASE = {
    "bad_faith": "insurance",
    "breach_of_contract": "insurance",
    "legal_malpractice": "malpractice",
    "negligence": "other",
    "fraud": "other",
}


def infer_case_type(posture: List[dict]) -> str:
    for finding in posture:
        mapped = _THEORY_TO_CASE.get(str(finding.get("theory")))
        if mapped and mapped != "other":
            return mapped
    return "other"


# Plain names for the legal theories.
PLAIN_THEORY = {
    "breach_of_contract": "They broke the agreement",
    "bad_faith": "They handled your claim unfairly, on purpose",
    "negligence": "They were careless and it hurt you",
    "legal_malpractice": "Your lawyer mishandled your case",
    "fraud": "They lied to you and you relied on it",
}

PLAIN_CHANNEL = {
    "A": "proof of what it cost you",
    "B": "proof they owed you something",
    "C": "proof of when it happened",
}


def plain_theory(key: str, fallback: str = "") -> str:
    return PLAIN_THEORY.get(str(key), fallback or str(key))


def _first_sentence(text: str, limit: int = 180) -> str:
    cleaned = " ".join(str(text).split())
    match = re.split(r"(?<=[.!?])\s", cleaned)
    value = match[0] if match else cleaned
    return value[:limit].rstrip()


def narrative(case_name: str, documents: List[dict], posture: List[dict],
              case_type: str) -> str:
    """A short account of the case, assembled only from what is in the record."""
    profile = CASE_TYPES.get(case_type, CASE_TYPES["other"])
    parts: List[str] = []
    if profile["about"]:
        parts.append(profile["about"])

    pleading = next((item for item in documents if int(item.get("rank", 99)) == 1), None)
    if pleading:
        opening = next((line.get("text") for line in pleading.get("lines", [])
                        if len(str(line.get("text") or "").strip()) > 30), "")
        if opening:
            parts.append(f"Your main filing ({pleading['source']}) begins: "
                         f"\u201c{_first_sentence(opening)}\u201d")

    claims = [plain_theory(item.get("theory"), item.get("label", "")) for item in posture]
    if claims:
        joined = "; ".join(claims)
        parts.append(f"You are claiming: {joined}.")

    resolved = [item for item in posture if item.get("resolved")]
    gaps = [item for item in posture if not item.get("resolved")]
    if resolved:
        parts.append(f"{len(resolved)} of your {len(posture)} claim(s) have documents "
                     f"in this case supporting every part.")
    if gaps:
        parts.append(f"{len(gaps)} still has a piece missing - see \u201cWhat you still "
                     f"need\u201d below.")
    parts.append(f"There are {len(documents)} documents in this case record.")
    return " ".join(parts)


def still_needed(posture: List[dict]) -> List[dict]:
    """Gaps, phrased as the next thing to go find."""
    needs: List[dict] = []
    for finding in posture:
        if finding.get("resolved"):
            continue
        theory = plain_theory(finding.get("theory"), finding.get("label", ""))
        for element in finding.get("elements", []):
            if element.get("supported"):
                continue
            channel = PLAIN_CHANNEL.get(str(element.get("channel")), "supporting proof")
            if element.get("asserted_only"):
                why = ("You say this in your own court filing, but saying it in your "
                       "filing is not proof of it. A judge will want a document from "
                       "outside your own paperwork.")
                where = element.get("asserted_at") or []
            else:
                why = "Nothing in this case record supports this part yet."
                where = []
            needs.append({
                "claim": theory,
                "missing": element.get("label", ""),
                "plain": f"You still need {channel}.",
                "why": why,
                "you_said_it_here": list(where),
            })
    return needs


def orientation(case_type: str) -> dict:
    profile = CASE_TYPES.get(case_type, CASE_TYPES["other"])
    return {
        "case_type": case_type,
        "case_type_label": profile["label"],
        "usually_turns_on": list(profile["usually_turns_on"]),
        "verify": VERIFY,
        "not_advice": NOT_ADVICE,
        "note": ("These are the kinds of things cases like yours usually turn on. "
                 "They are not a list of what your court requires."),
    }
