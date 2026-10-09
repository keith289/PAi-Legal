"""
Tests for PAi-Legal Database, AI, OCR, and Drafting modules
"""

import os
import tempfile
import unittest
from pai_legal.database import LegalDatabaseManager
from pai_legal.ai import LocalAIEngine
from pai_legal.ocr import DocumentOCREngine
from pai_legal.drafting import DocumentDrafterEngine


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

        doc_id = self.db.add_document(
            matter_id=matter_id,
            title="Complaint.pdf",
            content="Sample legal complaint text",
            doc_type="pleading",
        )
        self.assertIsNotNone(doc_id)

        docs = self.db.list_documents(matter_id=matter_id)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["title"], "Complaint.pdf")

        draft_id = self.db.add_draft(
            matter_id=matter_id,
            title="Motion to Dismiss",
            content_html="<html><body>Motion Draft</body></html>",
        )
        self.assertIsNotNone(draft_id)
        drafts = self.db.get_drafts(matter_id=matter_id)
        self.assertEqual(len(drafts), 1)

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
