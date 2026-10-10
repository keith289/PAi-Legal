"""Companion REST API server for PAi Legal Android Companion App.

Allows paired Android companion app to:
- List active cases
- Read case files and extracted document text
- Upload new evidence files and quick notes into a case
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .workspace import Workspace


class CompanionRequestHandler(BaseHTTPRequestHandler):
    workspace: Workspace
    pairing_token: str

    def log_message(self, format: str, *args) -> None:
        pass  # Suppress default HTTP server logging

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            return secrets.compare_digest(token, self.pairing_token)
        return False

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self._send_json(200, {"status": "online", "service": "PAi Legal Companion API", "version": "0.9.7"})
            return

        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized: invalid or missing pairing token"})
            return

        parts = [p for p in self.path.split("?")[0].split("/") if p]

        # GET /api/cases
        if parts == ["api", "cases"]:
            cases = self.workspace.list_cases()
            payload = [{
                "case_id": c.case_id,
                "name": c.name,
                "status": c.status,
                "document_count": c.document_count,
            } for c in cases]
            self._send_json(200, {"cases": payload})
            return

        # GET /api/cases/<case_id>/files
        if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "files":
            case_id = parts[2]
            case = self._find_case(case_id)
            if not case:
                self._send_json(404, {"error": f"Case {case_id} not found"})
                return
            files = []
            for text_file in sorted((case.path / "02_text").glob("*.txt")):
                files.append({
                    "name": text_file.name,
                    "stem": text_file.stem,
                    "bytes": text_file.stat().st_size,
                    "kind": "text"
                })
            for orig in sorted((case.path / "01_originals").glob("*")):
                if orig.is_file():
                    files.append({
                        "name": orig.name,
                        "stem": orig.stem,
                        "bytes": orig.stat().st_size,
                        "kind": "original"
                    })
            self._send_json(200, {"case_id": case_id, "files": files})
            return

        # GET /api/cases/<case_id>/files/<filename>
        if len(parts) == 5 and parts[:2] == ["api", "cases"] and parts[3] == "files":
            case_id = parts[2]
            filename = parts[4]
            case = self._find_case(case_id)
            if not case:
                self._send_json(404, {"error": f"Case {case_id} not found"})
                return

            # Search in 02_text or 01_originals
            target = case.path / "02_text" / filename
            if not target.is_file():
                target = case.path / "01_originals" / filename
            if not target.is_file():
                self._send_json(404, {"error": f"File {filename} not found in case {case_id}"})
                return

            try:
                content = target.read_text(encoding="utf-8", errors="replace")
                self._send_json(200, {"case_id": case_id, "filename": filename, "content": content})
            except Exception as exc:
                self._send_json(500, {"error": f"Failed to read file: {exc}"})
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self) -> None:
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized: invalid or missing pairing token"})
            return

        parts = [p for p in self.path.split("?")[0].split("/") if p]

        # POST /api/cases/<case_id>/evidence
        if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "evidence":
            case_id = parts[2]
            case = self._find_case(case_id)
            if not case:
                self._send_json(404, {"error": f"Case {case_id} not found"})
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON payload"})
                return

            filename = str(data.get("filename") or "").strip()
            text_content = str(data.get("text") or "").strip()
            note = str(data.get("note") or "").strip()

            if note and not filename:
                pinned = self.workspace.pin_claim(case, note, "UNVERIFIED", note_type="mobile_note")
                self._send_json(200, {"status": "ok", "type": "note", "note": pinned})
                return

            if not filename or not text_content:
                self._send_json(400, {"error": "filename and text/content (or note) are required"})
                return

            # Save uploaded document text/file
            inbox = case.path / "00_inbox" / filename
            inbox.parent.mkdir(parents=True, exist_ok=True)
            inbox.write_text(text_content, encoding="utf-8")

            ingested = self.workspace.ingest(case, [inbox])
            self._send_json(200, {
                "status": "ok",
                "type": "evidence",
                "filename": filename,
                "ingested": [item.filed_copy.name for item in ingested]
            })
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def _find_case(self, case_id: str):
        for c in self.workspace.list_cases():
            if c.case_id == case_id:
                return c
        return None


class CompanionServer:
    def __init__(self, workspace: Workspace, host: str = "0.0.0.0", port: int = 8088):
        self.workspace = workspace
        self.host = host
        self.port = port
        self.pairing_token = secrets.token_hex(16)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> dict:
        if self._server:
            return self.status()

        handler_class = type(
            "ConfiguredCompanionHandler",
            (CompanionRequestHandler,),
            {"workspace": self.workspace, "pairing_token": self.pairing_token}
        )
        self._server = HTTPServer((self.host, self.port), handler_class)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None

    def status(self) -> dict:
        running = self._server is not None
        return {
            "running": running,
            "host": self.host,
            "port": self.port,
            "pairing_token": self.pairing_token,
            "url": f"http://{self.host}:{self.port}" if running else ""
        }
