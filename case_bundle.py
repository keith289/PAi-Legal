"""
case_bundle.py — reads a PAi Legal case folder into a bundle dict
ready to pass to case_crypto.py
"""

import json
import os
from pathlib import Path


CORPUS_DIR  = "reasoning_corpus"
CORPUS_FILES = [
    "assertions.jsonl",
    "bracketed_facts.json",
    "bracketed_facts.txt",
    "case_blob.jsonl",
    "case_blob.txt",
    "corpus_manifest.json",
    "reasoning_check.json",
]


def read_bundle(case_path: str | Path) -> dict:
    """
    Read a case folder into a bundle dict.
    case_path is the top-level case folder (e.g. C:\\...\\cases\\CASE-000002).
    Raises FileNotFoundError if reasoning_corpus is missing.
    """
    root   = Path(case_path)
    corpus = root / CORPUS_DIR

    if not corpus.exists():
        raise FileNotFoundError(f"No reasoning_corpus at {corpus}")

    bundle = {
        "case_id":  root.name,
        "case_path": str(root),
        "corpus":   {},
        "rpm":      {},
        "meta":     {},
    }

    # ── reasoning corpus ─────────────────────────────────────────────────────
    for fname in CORPUS_FILES:
        fpath = corpus / fname
        if not fpath.exists():
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        if fname.endswith(".json"):
            try:
                bundle["corpus"][fname] = json.loads(text)
            except json.JSONDecodeError:
                bundle["corpus"][fname] = text      # store raw if malformed
        elif fname.endswith(".jsonl"):
            lines = [l for l in text.splitlines() if l.strip()]
            bundle["corpus"][fname] = []
            for line in lines:
                try:
                    bundle["corpus"][fname].append(json.loads(line))
                except json.JSONDecodeError:
                    bundle["corpus"][fname].append(line)
        else:
            bundle["corpus"][fname] = text          # .txt files stored raw

    # ── case.json / claim.json / case_graph.json at root ────────────────────
    for fname in ("case.json", "claim.json", "case_graph.json"):
        fpath = root / fname
        if fpath.exists():
            try:
                bundle["rpm"][fname] = json.loads(
                    fpath.read_text(encoding="utf-8", errors="replace")
                )
            except json.JSONDecodeError:
                pass

    # ── manifest ─────────────────────────────────────────────────────────────
    manifest = corpus / "corpus_manifest.json"
    if manifest.exists():
        try:
            bundle["meta"] = json.loads(
                manifest.read_text(encoding="utf-8", errors="replace")
            )
        except json.JSONDecodeError:
            pass

    return bundle


def write_bundle(bundle: dict, case_path: str | Path) -> None:
    """
    Restore a received bundle dict back into a case folder.
    Creates reasoning_corpus if it doesn't exist.
    Does NOT overwrite existing files — raises FileExistsError if present.
    """
    root   = Path(case_path)
    corpus = root / CORPUS_DIR
    corpus.mkdir(parents=True, exist_ok=True)

    for fname, content in bundle.get("corpus", {}).items():
        dest = corpus / fname
        if dest.exists():
            raise FileExistsError(
                f"{dest} already exists — choose a different case folder or clear it first."
            )
        if isinstance(content, list):
            # .jsonl
            dest.write_text(
                "\n".join(json.dumps(r, separators=(",", ":")) for r in content),
                encoding="utf-8",
            )
        elif isinstance(content, dict):
            dest.write_text(
                json.dumps(content, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            dest.write_text(str(content), encoding="utf-8")

    for fname, content in bundle.get("rpm", {}).items():
        dest = root / fname
        if dest.exists():
            continue        # don't overwrite RPM state on import
        dest.write_text(
            json.dumps(content, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
