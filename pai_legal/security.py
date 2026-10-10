"""Professional security controls for the local PAi Legal workspace.

The desktop application remains a single-machine product.  These controls
bind authorization and secrets to the signed-in operating-system account and
allow a firm to require full-volume encryption before case data is written.
"""
from __future__ import annotations

import base64
import ctypes
import getpass
import json
import os
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .procutil import hidden

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class AccessDenied(PermissionError):
    pass


class SecretStoreUnavailable(RuntimeError):
    pass


ROLE_PERMISSIONS = {
    "owner": {"*"},
    "lawyer": {
        "case.read", "case.create", "case.archive", "case.export", "case.backup",
        "evidence.write", "workproduct.write", "research.write", "governance.write",
        "audit.verify", "filing.validate", "conflicts.check", "integration.manage",
    },
    "paralegal": {
        "case.read", "case.create", "case.export", "case.backup", "evidence.write",
        "workproduct.write", "research.write", "filing.validate", "conflicts.check",
    },
    "intake": {"case.read", "case.create", "evidence.write", "conflicts.check"},
    "auditor": {"case.read", "case.export", "audit.verify", "conflicts.check"},
}


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.02 * (attempt + 1))


def current_username() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    user = getpass.getuser().strip() or "unknown"
    return f"{domain}\\{user}".lower() if domain else user.lower()


class AccessController:
    """Maps operating-system accounts to local workspace roles.

    This is meaningful authorization only when different staff use separate OS
    accounts and the workspace ACL does not let them rewrite the policy file.
    The status report surfaces that limitation instead of presenting role
    switching as authentication.
    """

    def __init__(self, root: Path, username: str | None = None):
        self.path = Path(root) / "config" / "access.json"
        self.username = (username or current_username()).strip().lower()
        if not self.path.is_file():
            _atomic_json(self.path, {
                "schema_version": 1,
                "identity_source": "operating_system_account",
                "users": {self.username: "owner"},
            })

    def _data(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AccessDenied("The workspace access policy is missing or invalid") from exc
        if value.get("identity_source") != "operating_system_account":
            raise AccessDenied("The workspace access policy has an unsupported identity source")
        return value

    @property
    def role(self) -> str:
        role = str(self._data().get("users", {}).get(self.username, ""))
        if role not in ROLE_PERMISSIONS:
            raise AccessDenied(f"OS account {self.username} has no PAi Legal workspace role")
        return role

    def allows(self, permission: str) -> bool:
        permissions = ROLE_PERMISSIONS[self.role]
        return "*" in permissions or permission in permissions

    def require(self, permission: str) -> None:
        if not self.allows(permission):
            raise AccessDenied(f"Role {self.role} cannot perform {permission}")

    def set_role(self, username: str, role: str) -> None:
        self.require("access.manage")
        normalized_role = str(role).strip().lower()
        if normalized_role not in ROLE_PERMISSIONS:
            raise ValueError(f"Unknown role: {role}")
        normalized_user = str(username).strip().lower()
        if not normalized_user:
            raise ValueError("An operating-system account is required")
        data = self._data()
        users = dict(data.get("users") or {})
        if (normalized_user == self.username and users.get(normalized_user) == "owner" and
                normalized_role != "owner" and
                sum(assigned == "owner" for assigned in users.values()) <= 1):
            raise AccessDenied("Assign another owner before changing the last owner account")
        users[normalized_user] = normalized_role
        data["users"] = users
        _atomic_json(self.path, data)

    def status(self) -> dict:
        return {"username": self.username, "role": self.role,
                "identity_source": "operating_system_account"}


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class DPAPIProtector:
    """Windows DPAPI wrapper for user- or local-machine-scoped ciphertext."""

    def __init__(self, machine_scope: bool = False):
        self.machine_scope = bool(machine_scope)
        self.description = ("Windows DPAPI (local machine)" if self.machine_scope
                            else "Windows DPAPI (current user)")

    @staticmethod
    def _blob(value: bytes):
        buffer = ctypes.create_string_buffer(value)
        blob = _DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def protect(self, value: bytes) -> bytes:
        if os.name != "nt":
            raise SecretStoreUnavailable("Windows DPAPI is unavailable on this platform")
        source, source_buffer = self._blob(value)
        entropy, entropy_buffer = self._blob(b"PAi Legal credential vault v1")
        output = _DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        flags = 0x1 | (0x4 if self.machine_scope else 0)
        if not crypt32.CryptProtectData(ctypes.byref(source), "PAi Legal", ctypes.byref(entropy),
                                        None, None, flags, ctypes.byref(output)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)

    def unprotect(self, value: bytes) -> bytes:
        if os.name != "nt":
            raise SecretStoreUnavailable("Windows DPAPI is unavailable on this platform")
        source, source_buffer = self._blob(value)
        entropy, entropy_buffer = self._blob(b"PAi Legal credential vault v1")
        output = _DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        description = wintypes.LPWSTR()
        if not crypt32.CryptUnprotectData(ctypes.byref(source), ctypes.byref(description),
                                          ctypes.byref(entropy), None, None, 0x1,
                                          ctypes.byref(output)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if description:
                ctypes.windll.kernel32.LocalFree(description)
            ctypes.windll.kernel32.LocalFree(output.pbData)


class SoftProtector:
    """Fallback software protector when DPAPI is unavailable (e.g., Linux/macOS or tests)."""

    def __init__(self, root: Path | None = None):
        self.description = "PAi Legal Software Vault (PBKDF2/AES-GCM)"
        self.key_path = (Path(root) / "config" / ".vault.key") if root else None

    def _get_key(self) -> bytes:
        if not self.key_path:
            return b"PAiLegalFallbackTestKey32BytesLong!"[:32]
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.is_file():
            return base64.b64decode(self.key_path.read_text(encoding="utf-8").strip())
        key = os.urandom(32)
        self.key_path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")
        return key

    def protect(self, value: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = self._get_key()
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, value, b"PAi Legal credential vault v1")
        return nonce + ciphertext

    def unprotect(self, value: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = self._get_key()
        aesgcm = AESGCM(key)
        nonce = value[:12]
        ciphertext = value[12:]
        return aesgcm.decrypt(nonce, ciphertext, b"PAi Legal credential vault v1")


class SecretStore:
    """Small DPAPI-backed (or SoftProtector fallback) credential vault; plaintext is never written to disk."""

    def __init__(self, root: Path, protector=None, filename: str = "secrets.json"):
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise ValueError("Secret-store filenames must be simple JSON filenames")
        self.path = Path(root) / "config" / filename
        if protector:
            self.protector = protector
        elif os.name == "nt":
            self.protector = DPAPIProtector()
        else:
            self.protector = SoftProtector(root)

    def _data(self) -> dict:
        if not self.path.is_file():
            return {"schema_version": 1, "protection": self.protector.description, "entries": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SecretStoreUnavailable("The protected-secret store is invalid") from exc
        return value

    def set(self, name: str, secret: str | bytes) -> None:
        key = str(name).strip()
        if not key:
            raise ValueError("A secret name is required")
        raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        encrypted = self.protector.protect(raw)
        with _path_lock(self.path):
            data = self._data()
            entries = dict(data.get("entries") or {})
            entries[key] = base64.b64encode(encrypted).decode("ascii")
            data["entries"] = entries
            _atomic_json(self.path, data)

    def get_bytes(self, name: str) -> bytes | None:
        with _path_lock(self.path):
            encoded = self._data().get("entries", {}).get(str(name))
        if encoded is None:
            return None
        try:
            return self.protector.unprotect(base64.b64decode(encoded, validate=True))
        except Exception as exc:
            raise SecretStoreUnavailable(f"Protected secret {name!r} cannot be opened") from exc

    def get(self, name: str) -> str | None:
        value = self.get_bytes(name)
        return value.decode("utf-8") if value is not None else None

    def delete(self, name: str) -> bool:
        with _path_lock(self.path):
            data = self._data()
            entries = dict(data.get("entries") or {})
            removed = entries.pop(str(name), None) is not None
            if removed:
                data["entries"] = entries
                _atomic_json(self.path, data)
            return removed

    def names(self) -> list[str]:
        with _path_lock(self.path):
            return sorted(self._data().get("entries", {}))


@dataclass(frozen=True)
class EncryptionStatus:
    protected: bool | None
    provider: str
    detail: str
    mount_point: str

    def as_dict(self) -> dict:
        return asdict(self)


def volume_encryption_status(path: Path,
                             runner: Callable[..., subprocess.CompletedProcess] = subprocess.run
                             ) -> EncryptionStatus:
    resolved = Path(path).resolve()
    anchor = resolved.anchor or str(resolved)
    if os.name != "nt":
        return EncryptionStatus(None, "unsupported", "Volume encryption could not be verified", anchor)
    script = (
        "$v=Get-BitLockerVolume -MountPoint '" + anchor.replace("'", "''") +
        "' -ErrorAction Stop; $v | Select-Object MountPoint,ProtectionStatus,VolumeStatus | ConvertTo-Json -Compress"
    )
    try:
        result = runner(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                        capture_output=True, text=True, timeout=15, **hidden())
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        payload = json.loads(result.stdout)
        protection = str(payload.get("ProtectionStatus", "")).lower()
        protected = protection in {"on", "1"}
        return EncryptionStatus(protected, "Windows BitLocker",
                                f"ProtectionStatus={payload.get('ProtectionStatus')}; "
                                f"VolumeStatus={payload.get('VolumeStatus')}", anchor)
    except Exception as exc:
        return EncryptionStatus(None, "Windows BitLocker", f"Status unavailable: {exc}", anchor)


class StoragePolicy:
    def __init__(self, root: Path, status_probe: Callable[[Path], EncryptionStatus] = volume_encryption_status):
        self.root = Path(root)
        self.path = self.root / "config" / "security_policy.json"
        self.status_probe = status_probe
        if not self.path.is_file():
            _atomic_json(self.path, {"schema_version": 1, "require_encrypted_volume": False})

    def _data(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    @property
    def require_encrypted_volume(self) -> bool:
        return bool(self._data().get("require_encrypted_volume"))

    def set_enforcement(self, required: bool) -> None:
        data = self._data()
        data["require_encrypted_volume"] = bool(required)
        _atomic_json(self.path, data)

    def status(self) -> EncryptionStatus:
        return self.status_probe(self.root)

    def require_writable_storage(self) -> None:
        if not self.require_encrypted_volume:
            return
        status = self.status()
        if status.protected is not True:
            raise PermissionError(
                "This firm's policy requires an encrypted workspace volume; " + status.detail)
