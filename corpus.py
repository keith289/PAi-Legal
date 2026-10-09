"""Retrieval-only adapter for PSi Legal service or published SQLite shards."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from .rpm_legal import process as rpm_process
from .netsecurity import bearer_headers, require_loopback_url


class CorpusError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    source_id: str
    title: str
    excerpt: str = ""
    jurisdiction: str = ""
    year: str = ""
    citation: str = ""
    shard: str = ""
    source_row: str = ""
    score: float = 0.0
    flags: str = ""
    bracket: str = "UNVERIFIED"
    float_points: int = 0
    mix_points: int = 0
    stir_points: int = 0
    total_pressure: float = 0.0
    float_color: str = ""
    mix_color: str = ""
    stir_color: str = ""
    pattern_signature: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class PSiCorpus:
    def __init__(self, resources: Dict[str, str]):
        self.resources = dict(resources)
        self.api_url = self.resources.get("api_url", "").rstrip("/")
        self.api_token = self.resources.get("api_token", "")
        if self.api_url:
            try:
                self.api_url = require_loopback_url(self.api_url, "PSi Legal")
            except ValueError as exc:
                raise CorpusError(str(exc)) from exc
            if not self.api_token:
                raise CorpusError("PSi Legal service is missing its session authentication token")
        shards = self.resources.get("shards", "")
        self.shards = [Path(item) for item in shards.split(os.pathsep) if item]

    def search(self, query: str, limit: int = 10, jurisdiction: str = "") -> List[SearchResult]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 50))
        if self.api_url:
            return self._service_search(query, limit, jurisdiction)
        if not self.shards:
            raise CorpusError("PSi Legal did not publish a corpus service or readable shards")
        results: List[SearchResult] = []
        for shard in self.shards:
            if shard.suffix.lower() == ".db":
                results.extend(self._sqlite_search(shard, query, limit - len(results), jurisdiction))
            if len(results) >= limit:
                break
        return results[:limit]

    def _service_search(self, query: str, limit: int, jurisdiction: str) -> List[SearchResult]:
        state, lock = rpm_process(query, {"jurisdiction": jurisdiction} if jurisdiction else {})
        body = json.dumps({
            "q": query, "limit": limit, "jurisdiction": jurisdiction,
            "rpm_float": len(state.float), "rpm_mix": len(state.mix),
            "rpm_stir": len(state.stir), "rpm_signature": lock["signature"],
            "include": "rpm",
        }).encode("utf-8")
        request = urllib.request.Request(
            self.api_url + "/v1/corpus/search", data=body,
            headers={"Content-Type": "application/json", **bearer_headers(self.api_token)},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CorpusError(f"PSi Legal search service failed: {exc}") from exc
        rows = payload.get("results", payload if isinstance(payload, list) else [])
        return [self._from_mapping(item) for item in rows]

    @staticmethod
    def _from_mapping(item: dict) -> SearchResult:
        return SearchResult(
            source_id=str(item.get("source_id") or item.get("id") or item.get("uuid") or ""),
            title=str(item.get("title") or item.get("case_name") or "Untitled record"),
            excerpt=str(item.get("excerpt") or item.get("text") or item.get("summary") or ""),
            jurisdiction=str(item.get("jurisdiction") or ""),
            year=str(item.get("year") or item.get("date") or ""),
            citation=str(item.get("citation") or ""),
            shard=str(item.get("shard") or ""),
            source_row=str(item.get("source_row") or ""),
            score=float(item.get("score") or item.get("rank") or 0.0),
            flags=str(item.get("flags") or ""),
            bracket=str(item.get("bracket") or "UNVERIFIED"),
            float_points=int(item.get("float_points") or 0),
            mix_points=int(item.get("mix_points") or 0),
            stir_points=int(item.get("stir_points") or 0),
            total_pressure=float(item.get("total_pressure") or 0.0),
            float_color=str(item.get("float_color") or ""),
            mix_color=str(item.get("mix_color") or ""),
            stir_color=str(item.get("stir_color") or ""),
            pattern_signature=str(item.get("pattern_signature") or ""),
        )

    def _sqlite_search(self, shard: Path, query: str, limit: int, jurisdiction: str) -> List[SearchResult]:
        if limit <= 0:
            return []
        uri = f"file:{shard.as_posix()}?mode=ro&immutable=1"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise CorpusError(f"Cannot open PSi Legal shard {shard.name}: {exc}") from exc
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(docs)")}
            if not columns:
                raise CorpusError(f"{shard.name} does not contain the PSi Legal docs table")
            selected = [name for name in (
                "id", "uuid", "title", "case_name", "citation", "jurisdiction",
                "year", "date", "text", "excerpt", "summary", "shard",
                "source_row", "flags", "bracket", "float_points", "mix_points",
                "stir_points", "total_pressure", "float_color", "mix_color",
                "stir_color", "pattern_signature",
            ) if name in columns]
            projection = ", ".join(f"d.{name}" for name in selected)
            filters = ["titles MATCH ?"]
            parameters: List[object] = [query]
            if jurisdiction and "jurisdiction" in columns:
                filters.append("d.jurisdiction = ?")
                parameters.append(jurisdiction)
            parameters.append(limit)
            statement = (
                f"SELECT {projection}, bm25(titles) AS fts_score "
                "FROM titles JOIN docs d ON d.id = titles.rowid "
                f"WHERE {' AND '.join(filters)} ORDER BY fts_score LIMIT ?"
            )
            try:
                rows = connection.execute(statement, parameters).fetchall()
            except sqlite3.Error:
                # Some builds use titles' implicit docid but not docs.id.
                statement = (
                    f"SELECT {projection}, bm25(titles) AS fts_score "
                    "FROM titles JOIN docs d ON d.rowid = titles.rowid "
                    f"WHERE {' AND '.join(filters)} ORDER BY fts_score LIMIT ?"
                )
                rows = connection.execute(statement, parameters).fetchall()
            output: List[SearchResult] = []
            for row in rows:
                data = dict(row)
                data["score"] = -float(data.pop("fts_score", 0.0))
                data["source_id"] = str(data.get("id") or data.get("uuid") or "")
                output.append(self._from_mapping(data))
            return output
        except sqlite3.Error as exc:
            raise CorpusError(f"Search failed in {shard.name}: {exc}") from exc
        finally:
            connection.close()
