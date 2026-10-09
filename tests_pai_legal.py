"""
Tests for PAi-Legal Database, AI, OCR, Drafting, and Licensing modules
"""

import os
import tempfile
import unittest
from pai_legal.database import LegalDatabaseManager
from pai_legal.ai import LocalAIEngine
from pai_legal.ocr import DocumentOCREngine
from pai_legal.drafting import DocumentDrafterEngine
from pai_legal.licensing import LicenseManager, PlanTier


class TestPAiLegal(unittest.TestCase):

    def setUp(self):
        self.temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_file.close()
        self.db = LegalDatabaseManager(db_path=self.temp_db_file.name)

    def tearDown(self):
        if os.path.exists(self.temp_db_file.name):
            os.remove(self.temp_db_file.name)

    def test_database_operations(self):
        matter_id = self.db.create_matter(
            title="Acme Corp Litigation",
            case_number="2026-CV-1001",
            client_name="Acme Corp",
            jurisdiction="US-FED",
        )
        self.assertIsNotNone(matter_id)

        matters = self.db.list_matters()
        self.assertEqual(len(matters), 1)
        self.assertEqual(matters[0]["title"], "Acme Corp Litigation")
        self.assertEqual(self.db.count_active_matters(), 1)

        # Test archiving matter
        self.assertTrue(self.db.archive_matter(matter_id))
        self.assertEqual(self.db.count_active_matters(), 0)

        # Archived matter is still readable
        archived_matter = self.db.get_matter(matter_id)
        self.assertEqual(archived_matter["status"], "Archived")

        # Unarchive
        self.assertTrue(self.db.unarchive_matter(matter_id))
        self.assertEqual(self.db.count_active_matters(), 1)

    def test_licensing_and_quotas(self):
        lm = LicenseManager()
        plan_info = lm.get_plan_info()
        self.assertEqual(plan_info["tier"], PlanTier.FREE_TRIAL)
        self.assertEqual(plan_info["allowed_active_matters"], 2)

        # Quota checks
        can_create, _ = lm.check_can_create_matter(current_active_matters=1)
        self.assertTrue(can_create)

        can_create, msg = lm.check_can_create_matter(current_active_matters=2)
        self.assertFalse(can_create)
        self.assertIn("Active matter quota reached", msg)

        # Upgrade to Solo signed license token
        token = LicenseManager.create_license_token(
            tier=PlanTier.SOLO,
            seats=1,
            included_active_matters=5,
            extra_matters=2,
            days_valid=30,
        )
        self.assertTrue(lm.load_signed_license_token(token))
        solo_info = lm.get_plan_info()
        self.assertEqual(solo_info["tier"], PlanTier.SOLO)
        self.assertEqual(solo_info["allowed_active_matters"], 7)  # 5 + 2

    def test_ai_engine(self):
        ai = LocalAIEngine()
        response = ai.generate_legal_analysis("Summarize contract terms.")
        self.assertIn("Contract Analysis", response)

    def test_ocr_engine(self):
        ocr = DocumentOCREngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Legal contract sample text")
            txt_file = f.name

        try:
            extracted = ocr.extract_text(txt_file)
            self.assertEqual(extracted, "Legal contract sample text")
        finally:
            if os.path.exists(txt_file):
                os.remove(txt_file)

    def test_drafter_engine(self):
        drafter = DocumentDrafterEngine()
        caption = {
            "court": "IN THE DISTRICT COURT OF APPEAL",
            "plaintiff": "JOHN DOE",
            "defendant": "JANE SMITH",
            "case_number": "2026-CA-001",
            "title": "MOTION TO COMPEL",
        }
        draft_html = drafter.draft_motion(caption, body_text="Plaintiff respectfully requests discovery compliance.")
        self.assertIn("MOTION TO COMPEL", draft_html)
        self.assertIn("JOHN DOE", draft_html)


if __name__ == "__main__":
    unittest.main()
