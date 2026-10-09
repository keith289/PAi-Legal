"""Encrypted, manifest-verified case backup format."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


MAGIC = b"PAILBKP1"
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _key(passphrase: str, salt: bytes) -> bytes:
    if len(str(passphrase)) < 12:
        raise ValueError("Backup passphrases must contain at least 12 characters")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _case_files(case_dir: Path):
    root = case_dir.resolve()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Case backups do not follow symbolic links: {path.name}")
        if path.is_file():
            yield path, path.relative_to(root).as_posix()


def create_backup(case_dir: Path, destination: Path, passphrase: str,
                  audit_key: bytes = b"") -> Path:
    case_dir = Path(case_dir).resolve()
    destination = Path(destination).resolve()
    if not case_dir.is_dir() or not (case_dir / "case.json").is_file():
        raise ValueError("A valid PAi Legal case directory is required")
    try:
        destination.relative_to(case_dir)
    except ValueError:
        pass
    else:
        raise ValueError("Write encrypted backups outside the live case directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = destination.with_suffix(destination.suffix + ".tmp")
    zip_fd, zip_name = tempfile.mkstemp(prefix="pai-backup-", suffix=".zip", dir=str(case_dir.parent))
    os.close(zip_fd)
    zip_path = Path(zip_name)
    try:
        manifest = {"schema_version": 1, "format": "PAi Legal encrypted case backup",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "case_id": json.loads((case_dir / "case.json").read_text(encoding="utf-8"))["case_id"],
                    "files": []}
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            for path, relative in _case_files(case_dir):
                manifest["files"].append({"path": relative, "size": path.stat().st_size,
                                          "sha256": _hash_file(path)})
                archive.write(path, "case/" + relative)
            archive.writestr("backup_manifest.json",
                             json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"))
            if audit_key:
                if len(audit_key) < 32:
                    raise ValueError("The case audit key is invalid")
                # This key is inside the authenticated encrypted envelope, not
                # inside the restored case directory or an unencrypted sidecar.
                archive.writestr("protected/audit_hmac_key.bin", bytes(audit_key))

        salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
        encryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce)).encryptor()
        with zip_path.open("rb") as source, temporary_output.open("wb") as target:
            target.write(MAGIC + salt + nonce)
            for block in iter(lambda: source.read(1024 * 1024), b""):
                target.write(encryptor.update(block))
            target.write(encryptor.finalize())
            target.write(encryptor.tag)
            target.flush(); os.fsync(target.fileno())
        temporary_output.replace(destination)
        return destination
    finally:
        zip_path.unlink(missing_ok=True)
        temporary_output.unlink(missing_ok=True)


def _decrypt_backup(source: Path, passphrase: str, zip_path: Path) -> None:
    minimum = len(MAGIC) + SALT_BYTES + NONCE_BYTES + TAG_BYTES
    if source.stat().st_size < minimum:
        raise ValueError("The backup is truncated")
    with source.open("rb") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise ValueError("This is not a PAi Legal encrypted backup")
        salt, nonce = handle.read(SALT_BYTES), handle.read(NONCE_BYTES)
        ciphertext_end = source.stat().st_size - TAG_BYTES
        handle.seek(ciphertext_end)
        tag = handle.read(TAG_BYTES)
        handle.seek(len(MAGIC) + SALT_BYTES + NONCE_BYTES)
        decryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce, tag)).decryptor()
        with zip_path.open("wb") as target:
            remaining = ciphertext_end - handle.tell()
            while remaining:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("The backup ciphertext is truncated")
                target.write(decryptor.update(block))
                remaining -= len(block)
            try:
                target.write(decryptor.finalize())
            except Exception as exc:
                raise ValueError("Backup authentication failed (wrong passphrase or altered file)") from exc


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def restore_backup(source: Path, cases_dir: Path, passphrase: str) -> tuple[Path, bytes]:
    source = Path(source).resolve()
    cases_dir = Path(cases_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    cases_dir.mkdir(parents=True, exist_ok=True)
    zip_fd, zip_name = tempfile.mkstemp(prefix="pai-restore-", suffix=".zip", dir=str(cases_dir.parent))
    os.close(zip_fd)
    zip_path = Path(zip_name)
    staging: Path | None = None
    try:
        _decrypt_backup(source, passphrase, zip_path)
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()
            names = [item.filename for item in members]
            if len(names) != len(set(names)):
                raise ValueError("The backup contains duplicate archive paths")
            if len(members) > 100002:
                raise ValueError("The backup contains an unreasonable number of files")
            for item in members:
                if not _safe_member(item.filename) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("The backup contains an unsafe path or symbolic link")
            try:
                manifest = json.loads(archive.read("backup_manifest.json"))
            except (KeyError, ValueError) as exc:
                raise ValueError("The backup manifest is missing or invalid") from exc
            case_id = str(manifest.get("case_id") or "")
            if not case_id.startswith("CASE-") or not case_id[5:].isdigit():
                raise ValueError("The backup contains an invalid case identity")
            target = cases_dir / case_id
            if target.exists():
                raise FileExistsError(f"A case already uses {case_id}")
            staging = cases_dir / f".{case_id}.restore-{os.getpid()}"
            if staging.exists():
                raise FileExistsError("A restore operation is already in progress")
            staging.mkdir()
            manifest_files = list(manifest.get("files", []))
            expected = {str(item["path"]): item for item in manifest_files}
            if len(expected) != len(manifest_files) or "case.json" not in expected:
                raise ValueError("The backup manifest has duplicate paths or no case metadata")
            declared_total = sum(int(item.get("size", -1)) for item in manifest_files)
            if declared_total < 0 or declared_total > int(shutil.disk_usage(cases_dir).free * 0.9):
                raise ValueError("The restored case would exceed safe available storage")
            info_by_name = {item.filename: item for item in members}
            for relative, item in expected.items():
                member = "case/" + relative
                if not _safe_member(member):
                    raise ValueError("The backup manifest contains an unsafe path")
                if member not in info_by_name or info_by_name[member].file_size != int(item.get("size", -1)):
                    raise ValueError(f"Backup metadata does not match {relative}")
                try:
                    source_handle = archive.open(member)
                except KeyError as exc:
                    raise ValueError(f"Backup file is missing: {relative}") from exc
                output = (staging / Path(*PurePosixPath(relative).parts)).resolve()
                try:
                    output.relative_to(staging.resolve())
                except ValueError as exc:
                    raise ValueError("The backup attempted to escape the case directory") from exc
                output.parent.mkdir(parents=True, exist_ok=True)
                with source_handle, output.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                if output.stat().st_size != int(item.get("size", -1)) or _hash_file(output) != item.get("sha256"):
                    raise ValueError(f"Backup verification failed for {relative}")
            archived_files = {name[5:] for name in archive.namelist() if name.startswith("case/") and not name.endswith("/")}
            if archived_files != set(expected):
                raise ValueError("The backup contains unmanifested case files")
            try:
                audit_key = archive.read("protected/audit_hmac_key.bin")
            except KeyError as exc:
                raise ValueError("The backup does not contain its protected audit key") from exc
            if len(audit_key) < 32:
                raise ValueError("The backup audit key is invalid")
        staging.replace(target)
        staging = None
        return target, audit_key
    finally:
        zip_path.unlink(missing_ok=True)
        if staging and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
