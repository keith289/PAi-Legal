"""
case_crypto.py — PAi Legal bundle encryption
Three tiers:
  seal      — HMAC-SHA256 signature only, no encryption
  recipient — AES-256-GCM encrypted, unlock code sent separately
  tenant    — AES-256-GCM encrypted with a shared firm passphrase
"""

import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from base64 import b64encode, b64decode

# ── constants ────────────────────────────────────────────────────────────────
FORMAT   = "pailegal-bundle"
VERSION  = 1
APP_SIGN_KEY = b"PAiLegal-Seal-v1-DO-NOT-SHARE"   # baked in, seal tier only


# ── key derivation ───────────────────────────────────────────────────────────
def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256, 310000 rounds (OWASP 2024 min)."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        310_000,
        dklen=32,
    )


# ── AES-256-GCM via cryptography library ─────────────────────────────────────
def _aes_encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Returns (nonce, ciphertext+tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    ct    = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce, ct


def _aes_decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Raises cryptography.exceptions.InvalidTag on tamper."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(nonce, ciphertext, None)


# ── machine fingerprint (non-PII, used for audit trail only) ─────────────────
def _machine_id() -> str:
    try:
        import subprocess
        r = subprocess.run(
            ["wmic", "csproduct", "get", "UUID"],
            capture_output=True, text=True, timeout=3
        )
        uid = r.stdout.strip().splitlines()[-1].strip()
        return hashlib.sha256(uid.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


# ── public API ───────────────────────────────────────────────────────────────

def seal(bundle_dict: dict, case_id: str) -> dict:
    """
    Tier 1 — sign only.
    Returns a .pailegal dict the recipient can verify but anyone can read.
    """
    payload = json.dumps(bundle_dict, separators=(",", ":")).encode()
    sig = hmac.new(APP_SIGN_KEY, payload, hashlib.sha256).hexdigest()
    return {
        "format":      FORMAT,
        "version":     VERSION,
        "tier":        "seal",
        "case_id":     case_id,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "exported_by": _machine_id(),
        "signature":   sig,
        "payload":     b64encode(payload).decode(),
    }


def seal_verify(pkg: dict) -> tuple[bool, dict]:
    """Returns (ok, bundle_dict). ok=False means tampered."""
    try:
        payload = b64decode(pkg["payload"])
        sig     = hmac.new(APP_SIGN_KEY, payload, hashlib.sha256).hexdigest()
        ok      = hmac.compare_digest(sig, pkg["signature"])
        return ok, json.loads(payload) if ok else {}
    except Exception as e:
        return False, {"error": str(e)}


def encrypt_recipient(bundle_dict: dict, case_id: str) -> tuple[dict, str]:
    """
    Tier 2 — recipient-locked.
    Returns (pkg, unlock_code).
    Sender sends pkg as the file and unlock_code separately (email/SMS).
    Recipient enters the unlock_code in PAi Legal to open.
    """
    bundle_key = secrets.token_bytes(32)          # random per export
    unlock_code = bundle_key.hex()                # 64-char hex string

    plaintext = json.dumps(bundle_dict, separators=(",", ":")).encode()

    # sign then encrypt
    sig      = hmac.new(APP_SIGN_KEY, plaintext, hashlib.sha256).hexdigest()
    nonce, ct = _aes_encrypt(bundle_key, plaintext)

    pkg = {
        "format":      FORMAT,
        "version":     VERSION,
        "tier":        "recipient",
        "case_id":     case_id,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "exported_by": _machine_id(),
        "signature":   sig,
        "nonce":       b64encode(nonce).decode(),
        "payload":     b64encode(ct).decode(),
    }
    return pkg, unlock_code


def decrypt_recipient(pkg: dict, unlock_code: str) -> tuple[bool, dict]:
    """Returns (ok, bundle_dict)."""
    try:
        key      = bytes.fromhex(unlock_code.strip())
        nonce    = b64decode(pkg["nonce"])
        ct       = b64decode(pkg["payload"])
        plain    = _aes_decrypt(key, nonce, ct)
        sig      = hmac.new(APP_SIGN_KEY, plain, hashlib.sha256).hexdigest()
        ok       = hmac.compare_digest(sig, pkg["signature"])
        return ok, json.loads(plain) if ok else {}
    except Exception as e:
        return False, {"error": str(e)}


def encrypt_tenant(bundle_dict: dict, case_id: str, passphrase: str) -> dict:
    """
    Tier 3 — tenant-locked.
    Anyone in the firm who has the same passphrase configured can open it.
    passphrase comes from PAi Legal Settings → Firm Encryption Key.
    """
    salt     = secrets.token_bytes(16)
    key      = _derive_key(passphrase, salt)
    plaintext = json.dumps(bundle_dict, separators=(",", ":")).encode()
    sig      = hmac.new(APP_SIGN_KEY, plaintext, hashlib.sha256).hexdigest()
    nonce, ct = _aes_encrypt(key, plaintext)

    return {
        "format":      FORMAT,
        "version":     VERSION,
        "tier":        "tenant",
        "case_id":     case_id,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "exported_by": _machine_id(),
        "signature":   sig,
        "salt":        b64encode(salt).decode(),
        "nonce":       b64encode(nonce).decode(),
        "payload":     b64encode(ct).decode(),
    }


def decrypt_tenant(pkg: dict, passphrase: str) -> tuple[bool, dict]:
    """Returns (ok, bundle_dict)."""
    try:
        salt  = b64decode(pkg["salt"])
        key   = _derive_key(passphrase, salt)
        nonce = b64decode(pkg["nonce"])
        ct    = b64decode(pkg["payload"])
        plain = _aes_decrypt(key, nonce, ct)
        sig   = hmac.new(APP_SIGN_KEY, plain, hashlib.sha256).hexdigest()
        ok    = hmac.compare_digest(sig, pkg["signature"])
        return ok, json.loads(plain) if ok else {}
    except Exception as e:
        return False, {"error": str(e)}


# ── unified open ─────────────────────────────────────────────────────────────

def open_bundle(pkg: dict, unlock_code: str = "", passphrase: str = "") -> tuple[bool, dict]:
    """
    Auto-dispatch by tier.
    For recipient tier pass unlock_code.
    For tenant tier pass passphrase.
    """
    tier = pkg.get("tier", "")
    if tier == "seal":
        return seal_verify(pkg)
    elif tier == "recipient":
        return decrypt_recipient(pkg, unlock_code)
    elif tier == "tenant":
        return decrypt_tenant(pkg, passphrase)
    else:
        return False, {"error": f"Unknown tier: {tier}"}
