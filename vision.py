"""The optional vision model used only to check extractions.

This model never answers a question about a case.  It is handed a page image
and the text that was extracted from it, and asked whether they agree.  That is
the only thing it is ever asked.  Its answers are advisory: a person resolves
them.

It is a separate model from the analysis model on purpose:

* Checking is a different job from writing, and the model that is good at
  reading a scanned page is not the one you want phrasing a finding.
* Validation runs unattended over every page of every file.  Loading a
  vision model for that pass and unloading it afterwards keeps a laptop from
  carrying both at once.
* A firm that does not want a second model can decline it.  Without it the
  deterministic quality gate still runs and its flags still reach the queue.

Everything here follows the same boundaries as the rest of the product: the
server binds to loopback with a per-run key, the model is downloaded once
against an immutable revision and a published SHA-256, and nothing leaves the
machine.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .procutil import hidden
from .hardware import HardwareProfile, app_data_root, scan_hardware
from .models import ModelCandidate, download_model, resolve_huggingface_file
from .netsecurity import bearer_headers, require_loopback_url
from .local_ai import bundled_runtime


class VisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisionCandidate:
    """A vision model is two files: the weights and its projector."""
    key: str
    label: str
    repo_id: str
    filename: str
    mmproj_filename: str
    size_gb: float          # both files together
    min_ram_gb: float
    context: int
    rank: int
    license: str = "Apache-2.0"


# Qwen2.5-VL is the smallest family that reliably reads a scanned legal page
# and answers in structured form.  The 3B runs on an ordinary laptop; the 7B is
# noticeably better on poor scans and handwriting.
CATALOG = (
    VisionCandidate(
        "qwen2.5-vl-3b", "Qwen2.5-VL 3B · Checker",
        "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
        "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf",
        3.4, 10, 8192, 1),
    VisionCandidate(
        "qwen2.5-vl-7b", "Qwen2.5-VL 7B · Checker (thorough)",
        "ggml-org/Qwen2.5-VL-7B-Instruct-GGUF",
        "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        "mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf",
        6.2, 18, 8192, 2),
)


def compatible(profile: HardwareProfile) -> List[VisionCandidate]:
    usable = min(max(profile.available_ram_gb, profile.total_ram_gb * 0.65),
                 profile.total_ram_gb - 5.0)
    return [item for item in CATALOG
            if usable >= item.min_ram_gb and profile.free_disk_gb >= item.size_gb * 2.2 + 2]


def recommend(profile: HardwareProfile) -> Optional[VisionCandidate]:
    return max(compatible(profile), key=lambda item: item.rank, default=None)


def installation_path() -> Path:
    return app_data_root() / "config" / "vision_installation.json"


def read_installation() -> dict:
    try:
        return json.loads(installation_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _as_model(candidate: VisionCandidate, filename: str) -> ModelCandidate:
    """Reuse the vetted resolve/download path, one file at a time."""
    return ModelCandidate(candidate.key, candidate.label, candidate.repo_id, filename,
                          candidate.size_gb, candidate.min_ram_gb, candidate.context,
                          candidate.rank, candidate.license)


def provision(candidate: VisionCandidate, hardware: Optional[HardwareProfile] = None,
              progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Download the weights and the projector, both hash-verified."""
    runtime = bundled_runtime()
    if not runtime.is_file():
        raise VisionError("The PAi Legal local-AI runtime is missing from this build")
    profile = hardware or scan_hardware()
    destination = app_data_root() / "models"

    resolved_model = resolve_huggingface_file(_as_model(candidate, candidate.filename))
    if Path(resolved_model.filename).name != candidate.filename:
        raise VisionError(
            f"{candidate.repo_id} no longer publishes {candidate.filename}")
    model_path = download_model(resolved_model, destination, progress)

    resolved_proj = resolve_huggingface_file(_as_model(candidate, candidate.mmproj_filename))
    if Path(resolved_proj.filename).name != candidate.mmproj_filename:
        raise VisionError(
            f"{candidate.repo_id} no longer publishes {candidate.mmproj_filename}")
    mmproj_path = download_model(resolved_proj, destination, progress)

    payload = {
        "schema_version": 1,
        "model_id": candidate.key,
        "model_label": candidate.label,
        "repo_id": candidate.repo_id,
        "model_path": str(model_path),
        "mmproj_path": str(mmproj_path),
        "runtime_path": str(runtime),
        "model_revision": resolved_model.revision,
        "model_sha256": resolved_model.sha256,
        "mmproj_revision": resolved_proj.revision,
        "mmproj_sha256": resolved_proj.sha256,
        "context": candidate.context,
        "gpu_layers": -1 if profile.vram_gb >= candidate.size_gb + 2 else 0,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    path = installation_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)
    return payload


class VisionClient:
    """Loopback llama-server with a projector loaded, used for checking only.

    One method: ``look(image, prompt, text)`` — the page and the text that was
    pulled off it, with a question about whether they agree.  There is no
    method for asking this model anything else, which is the point.

    Temperature is pinned at zero and the reply is capped: it is answering a
    structured question, not composing.
    """

    def __init__(self, resources: Optional[dict] = None, timeout: int = 240):
        self.resources = resources or read_installation()
        self.timeout = timeout
        self.api_url = ""
        self.api_key = ""
        self._process: Optional[subprocess.Popen] = None

    @property
    def model_label(self) -> str:
        return str(self.resources.get("model_label") or "")

    @property
    def installed(self) -> bool:
        model = Path(str(self.resources.get("model_path") or ""))
        mmproj = Path(str(self.resources.get("mmproj_path") or ""))
        return model.is_file() and mmproj.is_file()

    def _healthy(self) -> bool:
        for suffix in ("/health", "/v1/models"):
            try:
                request = urllib.request.Request(self.api_url.rstrip("/") + suffix,
                                                 headers=bearer_headers(self.api_key))
                with urllib.request.urlopen(request, timeout=1) as response:
                    if 200 <= response.status < 300:
                        return True
            except Exception:
                pass
        return False

    def start(self) -> None:
        if self.api_url and self._healthy():
            return
        if not self.installed:
            raise VisionError("Run Validation Model Setup before running a second read")
        runtime = Path(str(self.resources.get("runtime_path") or bundled_runtime()))
        if not runtime.is_file():
            raise VisionError("The local-AI runtime is missing from this build")

        port = int(os.environ.get("PAI_LEGAL_VISION_PORT", "8083"))
        self.api_url = require_loopback_url(f"http://127.0.0.1:{port}", "Validation model")
        self.api_key = secrets.token_urlsafe(32)
        args = [
            str(runtime),
            "--model", str(self.resources["model_path"]),
            "--mmproj", str(self.resources["mmproj_path"]),
            "--host", "127.0.0.1", "--port", str(port),
            "--api-key", self.api_key,
            "-c", str(self.resources.get("context") or 8192),
            "--log-disable",
        ]
        if int(self.resources.get("gpu_layers") or 0):
            args += ["-ngl", str(self.resources["gpu_layers"])]
        self._process = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, **hidden())
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self._healthy():
                return
            if self._process.poll() is not None:
                raise VisionError("The validation model stopped while loading")
            time.sleep(0.5)
        self.close()
        raise VisionError("The validation model did not become ready in time")

    def _complete(self, messages: list, max_tokens: int = 600) -> str:
        self.start()
        body = json.dumps({
            "model": "local", "messages": messages,
            "temperature": 0.0, "top_p": 0.1,
            "max_tokens": max_tokens, "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.api_url + "/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json", **bearer_headers(self.api_key)},
            method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"]).strip()

    @staticmethod
    def _data_url(image: Path) -> str:
        suffix = Path(image).suffix.lower()
        media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
                 ".tif": "image/tiff", ".tiff": "image/tiff"}.get(suffix, "image/png")
        encoded = base64.b64encode(Path(image).read_bytes()).decode("ascii")
        return f"data:{media};base64,{encoded}"

    def look(self, image: Path, prompt: str, text: str) -> str:
        """Fidelity: does this text match this page image."""
        return self._complete([
            {"role": "system", "content": prompt},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": self._data_url(image)}},
                {"type": "text",
                 "text": "TEXT EXTRACTED FROM THIS PAGE\n" + str(text or "[empty]")},
            ]},
        ])

    def close(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self.api_url = ""
        self.api_key = ""

    def __enter__(self) -> "VisionClient":
        self.start()
        return self

    def __exit__(self, *exception) -> None:
        self.close()


def available_client() -> Optional[VisionClient]:
    """A started client, or None when no validation model is installed.

    Callers treat None as "run the deterministic half only" rather than as an
    error, which is what keeps validation working on a machine that declined
    the second model.
    """
    client = VisionClient()
    if not client.installed:
        return None
    try:
        client.start()
    except (VisionError, OSError):
        return None
    return client
