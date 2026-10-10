"""Microsoft Store commerce for PAi Legal 0.9.7.

Business rules:
- First legal case is free.
- Each additional case consumes one `pai-legal-single-case` Store-managed consumable.
- An active `pai-legal-annual` subscription allows unlimited new cases.

The Store-managed consumable is fulfilled only *after* the case workspace has
been created successfully. The local ledger never substitutes for Microsoft as
payment authority; it only records the free-case marker, cached annual expiry,
and retry-safe fulfillment bookkeeping.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

SINGLE_CASE_PRODUCT = "pai-legal-single-case"
ANNUAL_PRODUCT = "pai-legal-annual"
LEDGER_SCHEMA = 2
ANNUAL_CACHE_GRACE = timedelta(days=7)
CLOCK_ROLLBACK_TOLERANCE = timedelta(minutes=2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_future(value: str | None, *, now: datetime | None = None) -> bool:
    parsed = _parse_dt(value)
    current = now or datetime.now(timezone.utc)
    return bool(parsed and parsed > current)


def _cached_annual_valid(ledger: dict, *, now: datetime | None = None) -> bool:
    """Revenue-safe offline cache.

    Cached annual access is accepted only for a short grace window after a
    successful Microsoft Store verification.  A wall-clock rollback below the
    last verified/observed UTC floor invalidates the cache instead of extending
    access.
    """
    current = now or datetime.now(timezone.utc)
    expiry = _parse_dt(str(ledger.get("annual_expires_at") or ""))
    verified = _parse_dt(str(ledger.get("annual_last_verified_at") or ""))
    floor = _parse_dt(str(ledger.get("annual_clock_floor_at") or ""))
    if not expiry or not verified or expiry <= current:
        return False
    if current + CLOCK_ROLLBACK_TOLERANCE < verified:
        return False
    if floor and current + CLOCK_ROLLBACK_TOLERANCE < floor:
        return False
    age = current - verified
    if age > ANNUAL_CACHE_GRACE:
        return False
    return True


class CommerceError(RuntimeError):
    """A customer-facing commerce failure."""


@dataclass(frozen=True)
class CaseReservation:
    mode: str  # free | annual | consumable
    tracking_id: str = ""
    product_id: str = ""
    created_at: str = ""


class StoreBridge:
    """Small JSON/stdio wrapper around PAiLegal.StoreBridge.exe."""

    def __init__(self, executable: Path | None = None, runner: Callable[[list[str]], dict] | None = None):
        self.executable = Path(executable) if executable else self._find_executable()
        self._runner = runner

    @staticmethod
    def _find_executable() -> Path:
        candidates: list[Path] = []
        frozen_root = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else None
        if frozen_root:
            candidates += [
                frozen_root / "store-bridge" / "PAiLegal.StoreBridge.exe",
                frozen_root / "PAiLegal.StoreBridge.exe",
            ]
        exe_root = Path(sys.executable).resolve().parent if sys.executable else Path.cwd()
        candidates += [
            exe_root / "_internal" / "store-bridge" / "PAiLegal.StoreBridge.exe",
            exe_root / "store-bridge" / "PAiLegal.StoreBridge.exe",
            Path(__file__).resolve().parents[1] / "store-bridge" / "bin" / "PAiLegal.StoreBridge.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[0] if candidates else Path("PAiLegal.StoreBridge.exe")

    def call(self, command: str, *, product: str = "", quantity: int = 1, tracking: str = "") -> dict:
        args = ["--command", command]
        if product:
            args += ["--product", product]
        if quantity:
            args += ["--quantity", str(quantity)]
        if tracking:
            args += ["--tracking", tracking]
        if self._runner:
            return self._runner(args)
        if os.name != "nt":
            raise CommerceError("Microsoft Store purchases are available only from the installed Windows Store build.")
        if not self.executable.is_file():
            raise CommerceError("Microsoft Store bridge is missing from this PAi Legal build.")
        completed = subprocess.run(
            [str(self.executable), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        payload: dict = {}
        for line in reversed(lines):
            try:
                candidate = json.loads(line)
                if isinstance(candidate, dict):
                    payload = candidate
                    break
            except json.JSONDecodeError:
                continue
        if not payload:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
            raise CommerceError(f"Microsoft Store did not return a valid response: {detail}")
        if not payload.get("ok"):
            raise CommerceError(str(payload.get("error") or payload.get("status") or "Microsoft Store request failed."))
        return payload

    def state(self) -> dict:
        return self.call("state", quantity=0)

    def purchase(self, product_id: str) -> dict:
        return self.call("purchase", product=product_id, quantity=0)

    def consume(self, product_id: str, tracking_id: str, quantity: int = 1) -> dict:
        return self.call("consume", product=product_id, quantity=quantity, tracking=tracking_id)


class CommerceManager:
    def __init__(self, workspace_root: Path, bridge: StoreBridge | None = None):
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.workspace_root / "commerce_ledger.json"
        self.bridge = bridge or StoreBridge()

    def _empty(self) -> dict:
        return {
            "schema_version": LEDGER_SCHEMA,
            "free_case_used": False,
            "free_case_case_id": "",
            "annual_expires_at": "",
            "annual_last_verified_at": "",
            "annual_clock_floor_at": "",
            "pending_fulfillment": None,
            "case_access": {},
            "history": [],
        }

    def read(self) -> dict:
        if not self.ledger_path.is_file():
            return self._empty()
        try:
            data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError, json.JSONDecodeError):
            data = self._empty()
        base = self._empty()
        base.update(data)
        if not isinstance(base.get("case_access"), dict):
            base["case_access"] = {}
        if not isinstance(base.get("history"), list):
            base["history"] = []
        return base

    def write(self, ledger: dict) -> None:
        ledger = dict(ledger)
        ledger["schema_version"] = LEDGER_SCHEMA
        temporary = self.ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.ledger_path)

    @staticmethod
    def _product(state: dict, product_id: str) -> dict:
        for product in state.get("products", []) or []:
            if str(product.get("productId", "")).lower() == product_id.lower():
                return product
        return {}

    @staticmethod
    def _license(state: dict, product_id: str) -> dict:
        for license_row in state.get("licenses", []) or []:
            if str(license_row.get("productId", "")).lower() == product_id.lower():
                return license_row
        return {}

    def _refresh_state(self, *, allow_cached_annual: bool = True) -> tuple[dict, dict]:
        ledger = self.read()
        try:
            state = self.bridge.state()
            now = _utc_now()
            annual = self._license(state, ANNUAL_PRODUCT)
            if annual and annual.get("active"):
                ledger["annual_expires_at"] = str(annual.get("expirationUtc") or "")
            else:
                # A successful Store query is authoritative.  If the license is
                # absent or inactive, stale cached annual access is cleared.
                ledger["annual_expires_at"] = ""
            ledger["annual_last_verified_at"] = now
            ledger["annual_clock_floor_at"] = now
            self.write(ledger)
            return ledger, state
        except CommerceError:
            if allow_cached_annual and _cached_annual_valid(ledger):
                return ledger, {"ok": False, "available": False, "products": [], "licenses": [], "cachedAnnual": True}
            raise

    def annual_active(self, *, refresh: bool = True) -> bool:
        ledger = self.read()
        if refresh:
            try:
                ledger, state = self._refresh_state(allow_cached_annual=True)
                annual = self._license(state, ANNUAL_PRODUCT)
                if annual and annual.get("active"):
                    return True
            except CommerceError:
                pass
        return _cached_annual_valid(ledger)

    def _history(self, ledger: dict, event: str, **detail) -> None:
        ledger.setdefault("history", []).append({"at": _utc_now(), "event": event, **detail})
        ledger["history"] = ledger["history"][-200:]

    def begin_new_case(self, existing_case_count: int) -> CaseReservation:
        """Reserve access but do not consume a paid credit yet."""
        ledger = self.read()

        # If the ledger was lost but case records remain, never accidentally
        # grant another introductory case.
        if existing_case_count > 0 and not ledger.get("free_case_used"):
            ledger["free_case_used"] = True
            self._history(ledger, "free_case_recovered_from_existing_workspace", existing_case_count=existing_case_count)
            self.write(ledger)

        # Annual customers are never asked to buy a case credit. Their first
        # actual case still counts as the introductory case for later fallback.
        try:
            refreshed, state = self._refresh_state(allow_cached_annual=True)
            annual = self._license(state, ANNUAL_PRODUCT)
            annual_active = bool(annual.get("active")) if annual else _cached_annual_valid(refreshed)
            ledger = refreshed
        except CommerceError:
            state = {}
            annual_active = _cached_annual_valid(ledger)

        if annual_active:
            return CaseReservation("annual", product_id=ANNUAL_PRODUCT, created_at=_utc_now())

        if not ledger.get("free_case_used") and existing_case_count == 0:
            return CaseReservation("free", created_at=_utc_now())

        # A paid case requires a Store-managed consumable balance. If none is
        # present, open Microsoft's purchase UI, then re-query the balance.
        if not state:
            _, state = self._refresh_state(allow_cached_annual=False)
        product = self._product(state, SINGLE_CASE_PRODUCT)
        balance = int(product.get("balance") or 0)
        if balance < 1:
            purchase = self.bridge.purchase(SINGLE_CASE_PRODUCT)
            status = str(purchase.get("status") or "")
            if status not in {"Succeeded", "AlreadyPurchased"}:
                raise CommerceError("The additional-case purchase was not completed.")
            _, state = self._refresh_state(allow_cached_annual=False)
            product = self._product(state, SINGLE_CASE_PRODUCT)
            balance = int(product.get("balance") or 0)
        if balance < 1:
            raise CommerceError("Microsoft Store did not report an available PAi Legal case credit after purchase.")

        tracking = str(uuid.uuid4())
        ledger = self.read()
        ledger["pending_fulfillment"] = {
            "tracking_id": tracking,
            "product_id": SINGLE_CASE_PRODUCT,
            "created_at": _utc_now(),
            "status": "reserved",
        }
        self._history(ledger, "case_credit_reserved", tracking_id=tracking)
        self.write(ledger)
        return CaseReservation("consumable", tracking_id=tracking, product_id=SINGLE_CASE_PRODUCT, created_at=_utc_now())

    def commit_new_case(self, reservation: CaseReservation, case_id: str) -> None:
        ledger = self.read()
        if reservation.mode == "consumable":
            result = self.bridge.consume(SINGLE_CASE_PRODUCT, reservation.tracking_id, 1)
            status = str(result.get("status") or "")
            if status != "Succeeded":
                raise CommerceError("Microsoft Store could not consume the case credit. The new empty case was not activated.")
            ledger["pending_fulfillment"] = None
        elif reservation.mode == "free":
            ledger["free_case_used"] = True
            ledger["free_case_case_id"] = case_id
        elif reservation.mode == "annual" and not ledger.get("free_case_used"):
            ledger["free_case_used"] = True
            ledger["free_case_case_id"] = case_id

        ledger.setdefault("case_access", {})[case_id] = {
            "mode": reservation.mode,
            "product_id": reservation.product_id,
            "tracking_id": reservation.tracking_id,
            "granted_at": _utc_now(),
        }
        self._history(ledger, "case_access_committed", case_id=case_id, mode=reservation.mode)
        try:
            self.write(ledger)
        except OSError:
            # If Microsoft has already consumed a paid credit, never turn a
            # successful purchase into a deleted case merely because the local
            # accounting ledger could not be updated. Existing case files are
            # the recovery signal on the next run.
            if reservation.mode != "consumable":
                raise

    def cancel_reservation(self, reservation: CaseReservation, *, reason: str = "case_creation_failed") -> None:
        if reservation.mode != "consumable":
            return
        ledger = self.read()
        pending = ledger.get("pending_fulfillment") or {}
        if pending.get("tracking_id") == reservation.tracking_id:
            # We have *not* called ReportConsumableFulfillmentAsync yet, so the
            # Microsoft balance remains untouched. Remove only our reservation.
            ledger["pending_fulfillment"] = None
            self._history(ledger, "case_credit_reservation_cancelled", tracking_id=reservation.tracking_id, reason=reason)
            self.write(ledger)

    def purchase_annual_access(self) -> dict:
        """Open Microsoft's subscription purchase UI and verify the entitlement."""
        if self.annual_active(refresh=True):
            return self.status()
        purchase = self.bridge.purchase(ANNUAL_PRODUCT)
        status = str(purchase.get("status") or "")
        if status not in {"Succeeded", "AlreadyPurchased"}:
            raise CommerceError("The annual-access purchase was not completed.")
        ledger, state = self._refresh_state(allow_cached_annual=False)
        annual = self._license(state, ANNUAL_PRODUCT)
        if not annual.get("active"):
            raise CommerceError("Microsoft Store completed the purchase but has not reported the annual entitlement as active yet. Reopen PAi Legal and try again.")
        ledger["annual_expires_at"] = str(annual.get("expirationUtc") or ledger.get("annual_expires_at") or "")
        verified_at = _utc_now()
        ledger["annual_last_verified_at"] = verified_at
        ledger["annual_clock_floor_at"] = verified_at
        self._history(ledger, "annual_access_activated", product_id=ANNUAL_PRODUCT)
        self.write(ledger)
        return self.status()

    def status(self) -> dict:
        ledger = self.read()
        result = {
            "first_case_free": True,
            "free_case_used": bool(ledger.get("free_case_used")),
            "single_case_product": SINGLE_CASE_PRODUCT,
            "annual_product": ANNUAL_PRODUCT,
            "annual_expires_at": str(ledger.get("annual_expires_at") or ""),
            "annual_active": _cached_annual_valid(ledger),
        }
        try:
            _, state = self._refresh_state(allow_cached_annual=True)
            product = self._product(state, SINGLE_CASE_PRODUCT)
            result["single_case_balance"] = int(product.get("balance") or 0)
            result["single_case_price"] = str(product.get("formattedPrice") or "")
            annual_product = self._product(state, ANNUAL_PRODUCT)
            result["annual_price"] = str(annual_product.get("formattedPrice") or "")
            result["store_available"] = bool(state.get("available", state.get("ok", False)))
            result["annual_active"] = self.annual_active(refresh=False) or bool(self._license(state, ANNUAL_PRODUCT).get("active"))
        except CommerceError as exc:
            result["store_available"] = False
            result["store_error"] = str(exc)
        return result
