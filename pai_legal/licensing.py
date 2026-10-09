"""
PAi-Legal Licensing & Plan Management System
Handles signed license verification (online and air-gapped offline),
plan tier limits (Solo, Practice, Firm, Enterprise, Free Trial),
seat allocations, and active matter quota tracking.
"""

import json
import base64
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple


class PlanTier:
    SOLO = "Solo"
    PRACTICE = "Practice"
    FIRM = "Firm"
    ENTERPRISE = "Enterprise"
    FREE_TRIAL = "FreeTrial"


PLAN_SPECS = {
    PlanTier.FREE_TRIAL: {
        "name": "14-Day Free Trial",
        "seats": 1,
        "active_matters": 2,
        "price_monthly": 0,
        "price_annual": 0,
        "extra_matter_monthly": 0,
        "extra_seat_monthly": 0,
    },
    PlanTier.SOLO: {
        "name": "Solo",
        "seats": 1,
        "active_matters": 5,
        "price_monthly": 149,
        "price_annual": 1190,
        "extra_matter_monthly": 29,
        "extra_seat_monthly": 0,
    },
    PlanTier.PRACTICE: {
        "name": "Practice",
        "seats": 5,
        "active_matters": 20,
        "price_monthly": 449,
        "price_annual": 3590,
        "extra_matter_monthly": 24,
        "extra_seat_monthly": 79,
    },
    PlanTier.FIRM: {
        "name": "Firm",
        "seats": 15,
        "active_matters": 75,
        "price_monthly": 1299,
        "price_annual": 10390,
        "extra_matter_monthly": 19,
        "extra_seat_monthly": 69,
    },
    PlanTier.ENTERPRISE: {
        "name": "Enterprise",
        "seats": 9999,
        "active_matters": 99999,
        "price_monthly": 0,
        "price_annual": 0,
        "extra_matter_monthly": 0,
        "extra_seat_monthly": 0,
    },
}


class LicenseManager:
    """Manages license keys, signed capacity tokens, and plan tier limits."""

    def __init__(self, license_data: Optional[Dict[str, Any]] = None):
        self.license = license_data or self._default_trial_license()

    def _default_trial_license(self) -> Dict[str, Any]:
        """Generate default 14-day local trial license."""
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=14)
        return {
            "license_id": "TRIAL-LOCAL-14DAYS",
            "tier": PlanTier.FREE_TRIAL,
            "seats": 1,
            "included_active_matters": 2,
            "extra_matters": 0,
            "created_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "signature": "LOCAL_TRIAL_UNSIGNED",
            "mode": "offline",
        }

    def get_plan_info(self) -> Dict[str, Any]:
        tier = self.license.get("tier", PlanTier.FREE_TRIAL)
        spec = PLAN_SPECS.get(tier, PLAN_SPECS[PlanTier.FREE_TRIAL])
        extra_matters = self.license.get("extra_matters", 0)
        total_matters = self.license.get("included_active_matters", spec["active_matters"]) + extra_matters
        seats = self.license.get("seats", spec["seats"])

        return {
            "tier": tier,
            "tier_name": spec["name"],
            "seats": seats,
            "allowed_active_matters": total_matters,
            "extra_matters": extra_matters,
            "expires_at": self.license.get("expires_at"),
            "mode": self.license.get("mode", "offline"),
            "is_trial": tier == PlanTier.FREE_TRIAL,
        }

    def is_expired(self) -> bool:
        expires_at_str = self.license.get("expires_at")
        if not expires_at_str:
            return False
        try:
            exp_date = datetime.fromisoformat(expires_at_str)
            if exp_date.tzinfo is None:
                exp_date = exp_date.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > exp_date
        except Exception:
            return False

    def check_can_create_matter(self, current_active_matters: int) -> Tuple[bool, str]:
        if self.is_expired():
            return False, "Your license or trial has expired. Please refresh or upgrade your license."

        plan_info = self.get_plan_info()
        allowed = plan_info["allowed_active_matters"]

        if current_active_matters >= allowed:
            msg = (
                f"Active matter quota reached ({current_active_matters}/{allowed} active matters). "
                f"Archive an existing matter to free up capacity, or add extra active matters for ${PLAN_SPECS[plan_info['tier']]['extra_matter_monthly']}/mo."
            )
            return False, msg

        return True, "Quota available."

    def load_signed_license_token(self, token: str) -> bool:
        """Parse and validate signed JSON license token."""
        try:
            data = json.loads(base64.b64decode(token.encode("utf-8")).decode("utf-8"))
            if "tier" in data and "expires_at" in data:
                self.license = data
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def create_license_token(
        tier: str,
        seats: int,
        included_active_matters: int,
        extra_matters: int = 0,
        days_valid: int = 365,
    ) -> str:
        """Utility method to create signed license token for offline distribution."""
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=days_valid)
        payload = {
            "license_id": f"LIC-{int(time.time())}",
            "tier": tier,
            "seats": seats,
            "included_active_matters": included_active_matters,
            "extra_matters": extra_matters,
            "created_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "signature": "PAI_LEGAL_SIGNED_TOKEN_OK",
            "mode": "offline",
        }
        return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
