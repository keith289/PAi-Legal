"""
case_export.py â€” export and import .pailegal encrypted bundle files

Export flow:
    1. read_bundle(case_path)   â†’ bundle dict
    2. seal / encrypt_recipient / encrypt_tenant
    3. write_pailegal(pkg, dest_path)
    â†’ attorney sends the .pailegal file however they like

Import flow:
    1. read_pailegal(src_path)  â†’ pkg dict
    2. open_bundle(pkg, ...)    â†’ (ok, bundle dict)
    3. write_bundle(bundle, case_path)
"""

import json
from pathlib import Path

from .case_bundle import read_bundle, write_bundle
from .case_crypto import (
    seal,
    encrypt_recipient,
    encrypt_tenant,
    open_bundle,
)

EXTENSION = ".pailegal"


# â”€â”€ file I/O â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def write_pailegal(pkg: dict, dest_path: str | Path) -> Path:
    dest = Path(dest_path)
    if dest.suffix != EXTENSION:
        dest = dest.with_suffix(EXTENSION)
    dest.write_text(
        json.dumps(pkg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return dest


def read_pailegal(src_path: str | Path) -> dict:
    return json.loads(Path(src_path).read_text(encoding="utf-8"))


# â”€â”€ export â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def export_seal(case_path: str | Path, dest_path: str | Path) -> Path:
    """
    Tier 1 â€” signed, readable by anyone.
    Good for court filing or sharing with a client.
    """
    bundle   = read_bundle(case_path)
    case_id  = Path(case_path).name
    pkg      = seal(bundle, case_id)
    return write_pailegal(pkg, dest_path)


def export_recipient(
    case_path: str | Path,
    dest_path: str | Path,
) -> tuple[Path, str]:
    """
    Tier 2 â€” encrypted, unlock code returned separately.
    Send the .pailegal file to the recipient.
    Send the unlock_code separately (email, SMS â€” NOT in the same message).
    Returns (file_path, unlock_code).
    """
    bundle   = read_bundle(case_path)
    case_id  = Path(case_path).name
    pkg, unlock_code = encrypt_recipient(bundle, case_id)
    dest = write_pailegal(pkg, dest_path)
    return dest, unlock_code


def export_tenant(
    case_path: str | Path,
    dest_path: str | Path,
    passphrase: str,
) -> Path:
    """
    Tier 3 â€” encrypted with shared firm passphrase.
    Anyone at the firm with the same passphrase can open it.
    """
    bundle   = read_bundle(case_path)
    case_id  = Path(case_path).name
    pkg      = encrypt_tenant(bundle, case_id, passphrase)
    return write_pailegal(pkg, dest_path)


# â”€â”€ import â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def import_bundle(
    src_path: str | Path,
    case_path: str | Path,
    unlock_code: str = "",
    passphrase: str  = "",
) -> tuple[bool, str]:
    """
    Open a .pailegal file and restore the case into case_path.
    Returns (ok, message).
    """
    try:
        pkg = read_pailegal(src_path)
    except Exception as e:
        return False, f"Could not read file: {e}"

    ok, bundle = open_bundle(pkg, unlock_code=unlock_code, passphrase=passphrase)

    if not ok:
        tier = pkg.get("tier", "unknown")
        if tier == "recipient":
            return False, "Incorrect unlock code or file has been tampered with."
        elif tier == "tenant":
            return False, "Incorrect firm passphrase or file has been tampered with."
        else:
            return False, "File signature invalid â€” this bundle has been tampered with."

    try:
        write_bundle(bundle, case_path)
    except FileExistsError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Could not restore case: {e}"

    return True, f"Case {bundle.get('case_id', '')} imported successfully."


# â”€â”€ quick test â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    import tempfile, sys

    case = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\libby\PSi-Legal\cases\CASE-000002"
    tmp  = tempfile.mkdtemp()

    print("\nâ”€â”€ Tier 1: seal â”€â”€")
    f = export_seal(case, f"{tmp}\\CASE-000002-seal")
    print(f"Written: {f}")
    ok, b = open_bundle(read_pailegal(f))
    print(f"Verify: {ok}, keys: {list(b.keys())}")

    print("\nâ”€â”€ Tier 2: recipient â”€â”€")
    f, code = export_recipient(case, f"{tmp}\\CASE-000002-recipient")
    print(f"Written: {f}")
    print(f"Unlock code: {code}")
    ok, b = open_bundle(read_pailegal(f), unlock_code=code)
    print(f"Decrypt: {ok}, keys: {list(b.keys())}")
    ok2, _ = open_bundle(read_pailegal(f), unlock_code="wrong")
    print(f"Wrong code rejected: {not ok2}")

    print("\nâ”€â”€ Tier 3: tenant â”€â”€")
    pw = "FirmSecret2027!"
    f  = export_tenant(case, f"{tmp}\\CASE-000002-tenant", pw)
    print(f"Written: {f}")
    ok, b = open_bundle(read_pailegal(f), passphrase=pw)
    print(f"Decrypt: {ok}, keys: {list(b.keys())}")
    ok2, _ = open_bundle(read_pailegal(f), passphrase="wrong")
    print(f"Wrong passphrase rejected: {not ok2}")

    print("\nAll tiers passed.")
