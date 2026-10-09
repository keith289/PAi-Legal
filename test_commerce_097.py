import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pai_legal.commerce import ANNUAL_PRODUCT, SINGLE_CASE_PRODUCT, CommerceManager, StoreBridge, _cached_annual_valid


class FakeStore:
    def __init__(self, balance=0, annual=False):
        self.balance = balance
        self.annual = annual
        self.calls = []

    @staticmethod
    def _arg(args, name):
        try:
            return args[args.index(name) + 1]
        except (ValueError, IndexError):
            return ""

    def __call__(self, args):
        command = self._arg(args, "--command") or "state"
        product = self._arg(args, "--product")
        tracking = self._arg(args, "--tracking")
        self.calls.append((command, product, tracking))
        if command == "state":
            licenses = []
            if self.annual:
                licenses.append({
                    "productId": ANNUAL_PRODUCT,
                    "active": True,
                    "expirationUtc": "2099-12-31T23:59:59+00:00",
                })
            return {
                "ok": True, "available": True,
                "products": [
                    {"productId": SINGLE_CASE_PRODUCT, "balance": self.balance, "formattedPrice": "$50.00"},
                    {"productId": ANNUAL_PRODUCT, "balance": 0, "formattedPrice": "$400.00/year"},
                ],
                "licenses": licenses,
            }
        if command == "purchase":
            if product == SINGLE_CASE_PRODUCT:
                self.balance += 1
            elif product == ANNUAL_PRODUCT:
                self.annual = True
            return {"ok": True, "status": "Succeeded", "productId": product}
        if command == "consume":
            if self.balance < 1:
                return {"ok": False, "status": "InsufficentQuantity"}
            self.balance -= 1
            return {"ok": True, "status": "Succeeded", "productId": product, "balanceRemaining": self.balance}
        raise AssertionError(command)


class CommerceTests(unittest.TestCase):
    def manager(self, td, fake):
        return CommerceManager(Path(td), StoreBridge(runner=fake))

    def test_first_case_is_free(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeStore()
            manager = self.manager(td, fake)
            reservation = manager.begin_new_case(0)
            self.assertEqual(reservation.mode, "free")
            manager.commit_new_case(reservation, "CASE-000001")
            self.assertTrue(manager.read()["free_case_used"])
            self.assertFalse(any(call[0] == "consume" for call in fake.calls))

    def test_second_case_buys_and_consumes_after_commit(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeStore()
            manager = self.manager(td, fake)
            first = manager.begin_new_case(0)
            manager.commit_new_case(first, "CASE-000001")
            second = manager.begin_new_case(1)
            self.assertEqual(second.mode, "consumable")
            self.assertEqual(fake.balance, 1)
            self.assertFalse(any(c[0] == "consume" for c in fake.calls))
            manager.commit_new_case(second, "CASE-000002")
            self.assertEqual(fake.balance, 0)
            self.assertTrue(any(c[0] == "consume" for c in fake.calls))

    def test_failed_case_creation_does_not_consume_credit(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeStore(balance=1)
            manager = self.manager(td, fake)
            ledger = manager.read(); ledger["free_case_used"] = True; manager.write(ledger)
            reservation = manager.begin_new_case(1)
            manager.cancel_reservation(reservation)
            self.assertEqual(fake.balance, 1)
            self.assertFalse(any(c[0] == "consume" for c in fake.calls))

    def test_annual_can_be_purchased_in_app(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeStore(balance=0, annual=False)
            manager = self.manager(td, fake)
            status = manager.purchase_annual_access()
            self.assertTrue(status["annual_active"])
            self.assertTrue(fake.annual)
            self.assertTrue(any(c[0] == "purchase" and c[1] == ANNUAL_PRODUCT for c in fake.calls))

    def test_annual_bypasses_case_credit(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeStore(balance=0, annual=True)
            manager = self.manager(td, fake)
            reservation = manager.begin_new_case(7)
            self.assertEqual(reservation.mode, "annual")
            manager.commit_new_case(reservation, "CASE-000008")
            self.assertFalse(any(c[0] in {"purchase", "consume"} for c in fake.calls))

    def test_cached_annual_expires_after_seven_day_grace(self):
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        ledger = {
            "annual_expires_at": (now + timedelta(days=200)).isoformat(),
            "annual_last_verified_at": (now - timedelta(days=8)).isoformat(),
            "annual_clock_floor_at": (now - timedelta(days=8)).isoformat(),
        }
        self.assertFalse(_cached_annual_valid(ledger, now=now))

    def test_cached_annual_rejects_clock_rollback(self):
        verified = datetime(2026, 8, 31, tzinfo=timezone.utc)
        ledger = {
            "annual_expires_at": (verified + timedelta(days=200)).isoformat(),
            "annual_last_verified_at": verified.isoformat(),
            "annual_clock_floor_at": verified.isoformat(),
        }
        self.assertFalse(_cached_annual_valid(ledger, now=verified - timedelta(hours=1)))

    def test_cached_annual_accepts_short_offline_grace(self):
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        ledger = {
            "annual_expires_at": (now + timedelta(days=200)).isoformat(),
            "annual_last_verified_at": (now - timedelta(days=6)).isoformat(),
            "annual_clock_floor_at": (now - timedelta(days=6)).isoformat(),
        }
        self.assertTrue(_cached_annual_valid(ledger, now=now))

    def test_successful_store_query_without_annual_clears_cache(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeStore(balance=0, annual=False)
            manager = self.manager(td, fake)
            ledger = manager.read()
            ledger["annual_expires_at"] = "2099-12-31T23:59:59+00:00"
            ledger["annual_last_verified_at"] = "2026-08-31T00:00:00+00:00"
            ledger["annual_clock_floor_at"] = "2026-08-31T00:00:00+00:00"
            manager.write(ledger)
            self.assertFalse(manager.annual_active(refresh=True))
            self.assertEqual(manager.read()["annual_expires_at"], "")


if __name__ == "__main__":
    unittest.main()
