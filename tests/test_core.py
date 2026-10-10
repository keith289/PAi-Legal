from __future__ import annotations

import json
import sqlite3
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pai_legal.capabilities import (Capability, CapabilityReport, CapabilityStatus,
                                    detect_analysis, detect_corpus)
from pai_legal.corpus import CorpusError, PSiCorpus
from pai_legal.ingestion import TextExtractor
from pai_legal.hardware import HardwareProfile
from pai_legal.local_ai import PrivateAIClient, enforce_brackets
from pai_legal.models import ModelCandidate, compatible_models, download_model, recommend_model
from pai_legal.security import (AccessController, AccessDenied, EncryptionStatus,
                                SecretStore, StoragePolicy)
from pai_legal.jurisdiction import available_rule_packs, validate_filing
from pai_legal.epistemic import BracketFloat, BracketType, bracket_name, mix, stir
from pai_legal import brackets
from pai_legal.rpm_legal import process as rpm_process
from pai_legal.rpm_legal import state_record
from pai_legal.parliament import Channel, compose, verify_klein_closure
from pai_legal.transition_map import build_case_transition_map
from pai_legal import doctypes, parliament
from pai_legal.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def test_case_ingestion_and_source_traced_context(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "motion.txt"
            source.write_text("The motion was filed on August 1.", encoding="utf-8")
            workspace = Workspace(base / "data")
            case = workspace.create_case("Smith v. Jones")
            results = workspace.ingest(case, [source])
            self.assertEqual(1, len(results))
            self.assertFalse(results[0].error)
            workspace.build_reasoning_corpus(case)
            context = workspace.context(case)
            self.assertIn("motion.txt", context)
            self.assertIn("August 1", context)
            # Context now groups each document under one header, then bare
            # numbered lines. Repeating the filename and a bracket wrapper on
            # every line spent the window on prefixes, not evidence.
            self.assertIn("=== motion.txt |", context)
            self.assertIn("UNVERIFIED", context)
            self.assertRegex(context, r"(?m)^\d+: ")
            self.assertNotIn("[RPM:", context)
            self.assertEqual(1, len(list((case.path / "04_index").glob("*.rpm.json"))))
            summary = workspace.rpm_summary(case)
            self.assertEqual(1, summary["documents"])
            self.assertGreater(summary["float_points"], 0)
            self.assertTrue((case.path / "01_originals" / "motion.txt").is_file())

    def test_context_selects_documents_relevant_to_the_question(self):
        """A case can hold more text than any context window.

        Reading the corpus front-to-back filled the budget with whichever
        documents sorted first, so a question about mold never reached the
        mold report. Context must select against the question.
        """
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            workspace = Workspace(base / "data")
            case = workspace.create_case("Retrieval")
            text_dir = case.path / "02_text"
            (text_dir / "aardvark_routine_notice.txt").write_text(
                "Acknowledgement of receipt. Retain this notice for your records.\n" * 8,
                encoding="utf-8")
            (text_dir / "truview_mold_assessment.txt").write_text(
                "Air sampling detected elevated Stachybotrys in the master bedroom.\n"
                "Remediation subtotal: $8,450.00\n", encoding="utf-8")
            (text_dir / "settlement_release.txt").write_text(
                "In consideration of payment by the carrier of TWELVE THOUSAND DOLLARS.\n",
                encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            mold = workspace.context(case, question="what did the mold assessment find")
            self.assertIn("truview_mold_assessment.txt", mold)
            self.assertNotIn("aardvark_routine_notice.txt", mold)

            money = workspace.context(case, question="how much did the carrier pay to settle")
            self.assertIn("settlement_release.txt", money)
            self.assertNotIn("truview_mold_assessment.txt", money)

            # Extraction bookkeeping never reaches the model.
            self.assertNotIn("<<<EXTRACTION", mold)
            self.assertNotIn("<<<SOURCE", mold)

    def test_controlling_documents_lead_regardless_of_the_question(self):
        """Sorting by file type alone makes a complaint a peer of an advert.

        A lawyer asked about a repair estimate still reads the complaint first,
        because the estimate only matters as it bears on a pleaded claim. The
        operative pleading therefore holds reserved context budget.
        """
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            workspace = Workspace(base / "data")
            case = workspace.create_case("Precedence")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_Smith_v_Acme.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOMES NOW Plaintiff SMITH.\n"
                "Count I: Breach of contract.\n", encoding="utf-8")
            (text_dir / "zzz_repair_estimate.txt").write_text(
                "Roof replacement estimate total: $24,300.00\n", encoding="utf-8")
            (text_dir / "advertisement.txt").write_text(
                "Subscribe today for exclusive savings.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            context = workspace.context(case, question="what is the roof estimate total")
            headers = re.findall(r"^=== (.+?) \|", context, re.M)
            self.assertTrue(headers, "context produced no document headers")
            # The pleading leads even though the question is about the estimate
            # and the estimate's filename sorts last.
            self.assertEqual("Complaint_Smith_v_Acme.txt", headers[0])
            self.assertIn("zzz_repair_estimate.txt", headers)
            self.assertNotIn("advertisement.txt", headers)
            self.assertIn("Operative pleading", context)

    def test_separators_do_not_hide_a_document_role(self):
        """Underscores and hyphens are word characters to \\b.

        A rule like \\bcomplaint\\b never fires on "Complaint_Stamm_v_Kin.txt",
        so an operative pleading silently filed as unclassified and sorted
        last - behind the advertisements.
        """
        for name, key in (
            ("Complaint_Stamm_v_Kin.txt", "operative_pleading"),
            ("Answer_and_Affirmative_Defenses.txt", "responsive_pleading"),
            ("Gwinnett_Order_on_Motion.txt", "order"),
            ("denial_letter.txt", "correspondence"),
            ("coverage-letter.pdf", "correspondence"),
            ("Truview-Mold-Assessment.pdf", "expert"),
            ("depo_smith.txt", "deposition"),
        ):
            self.assertEqual(key, doctypes.classify(name).key, name)
        self.assertEqual("unclassified", doctypes.classify("advertisement.txt").key)

    def test_document_role_is_read_from_text_when_the_name_is_useless(self):
        role = doctypes.classify("scan_0142.pdf", "COMPLAINT FOR DAMAGES\nCOMES NOW Plaintiff")
        self.assertEqual("operative_pleading", role.key)
        self.assertTrue(doctypes.is_controlling(role.key))
        self.assertFalse(doctypes.is_controlling("correspondence"))

    def test_analysis_retrieves_authorities_the_user_never_searched_for(self):
        """The corpus was installed and readable, and analysis never queried it.

        Authorities only reached the model if the user had already searched,
        selected and attached them by hand, so a doctrine they did not know to
        look for stayed invisible. The query is widened with the pleaded
        theories, because the corpus indexes doctrine rather than one case's
        vocabulary.
        """
        class FakeCorpus:
            def __init__(self): self.queries = []
            def search(self, query, limit=10, jurisdiction=""):
                self.queries.append((query, jurisdiction))
                return [{"source_id": "cap-1", "title": "Ga. bad faith standard",
                         "bracket": "EXPLAINED", "float_points": 14,
                         "mix_points": 6, "stir_points": 3}]

        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Kin")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_Stamm_v_Kin.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOUNT II - BAD FAITH. The carrier delayed.\n",
                encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            corpus = FakeCorpus()
            found = workspace.research_for_question(
                case, "was the denial unreasonable", corpus, jurisdiction="Ga.")
            self.assertEqual(1, len(found))
            self.assertEqual("auto", found[0]["retrieval"])
            # Stored bracket is carried through, never promoted.
            self.assertEqual("EXPLAINED", found[0]["bracket"])
            query, jurisdiction = corpus.queries[0]
            self.assertIn("denial", query)
            self.assertIn("faith", query)      # widened by the pleaded theory
            self.assertEqual("Ga.", jurisdiction)

            # Analysis must still work with no corpus installed.
            self.assertEqual([], workspace.research_for_question(
                case, "was the denial unreasonable", None))

    def test_case_brief_is_structured_for_an_external_drafter(self):
        """The Markdown export is prose; a drafting model needs structure.

        The brief carries the pleaded theories, the record in legal order with
        the lines behind each document, and the gaps - reported as gaps, so a
        drafter cannot quietly write around an unsupported element.
        """
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Stamm v Kin")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_Stamm_v_Kin.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOUNT I - BREACH OF CONTRACT.\n", encoding="utf-8")
            (text_dir / "POLICY (1).txt").write_text(
                "THIS POLICY of insurance. Premium paid.\n", encoding="utf-8")
            (text_dir / "denial_letter.txt").write_text(
                "December 2, 2024. We denied and refused to pay.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            destination = Path(temp) / "brief.json"
            workspace.export_case_package(case, destination)
            brief = json.loads(destination.read_text(encoding="utf-8"))

            self.assertEqual("PAi Legal", brief["generator"])
            self.assertEqual(1, brief["schema_version"])
            self.assertEqual(case.case_id, brief["case"]["case_id"])
            self.assertTrue(brief["posture"])
            # Documents arrive in legal reading order, pleading first.
            ranks = [item["rank"] for item in brief["documents"]]
            self.assertEqual(sorted(ranks), ranks)
            self.assertEqual("Complaint_Stamm_v_Kin.txt", brief["documents"][0]["source"])
            self.assertEqual("Operative pleading", brief["documents"][0]["role_label"])
            self.assertTrue(brief["documents"][0]["lines"])
            self.assertIn("cannot support it", " ".join(brief["guards"]))
            # The map's computed projections travel with the brief, labelled a
            # structural forecast rather than an outcome prediction.
            self.assertIn("transition_map", brief)
            self.assertIn("not a prediction", brief["transition_map"]["guard"].lower())

    def test_brief_authorities_are_widened_by_the_corpus_per_theory(self):
        """Only-what-was-attached leaves a doctrine nobody looked for invisible.

        Each pleaded theory queries the corpus once. Retrieved records stay
        distinguishable from authorities the client chose, and their stored
        Trust Locks are carried through rather than promoted.
        """
        class FakeCorpus:
            def __init__(self): self.queries = []
            def search(self, query, limit=10, jurisdiction=""):
                self.queries.append(query)
                return [{"source_id": f"cap-{len(self.queries)}",
                         "title": f"Authority for {query[:20]}", "bracket": "EXPLAINED"}]

        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Kin")
            (case.path / "02_text" / "Complaint_k.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOUNT I - BREACH OF CONTRACT.\n"
                "COUNT II - BAD FAITH. The carrier delayed.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            corpus = FakeCorpus()
            brief = workspace.case_brief(case, corpus=corpus, jurisdiction="Ga.")
            self.assertEqual(2, len(corpus.queries))          # one per theory
            retrieved = [a for a in brief["authorities"] if a.get("retrieval") == "auto"]
            self.assertEqual(2, len(retrieved))
            self.assertEqual({"breach_of_contract", "bad_faith"},
                             {a["retrieved_for"] for a in retrieved})
            self.assertEqual("EXPLAINED", retrieved[0]["bracket"])

            # No corpus installed: attached authorities only, no failure.
            plain = workspace.case_brief(case)
            self.assertFalse([a for a in plain["authorities"] if a.get("retrieval") == "auto"])

    def test_prose_brief_renames_without_softening_a_gap(self):
        """A self-represented reader needs the jargon gone, not the findings.

        Softening a gap would defeat the point: telling someone what their case
        is missing before a judge does is the reason for computing it.
        """
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Stamm v Kin")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_Stamm_v_Kin.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOMES NOW Plaintiff.\n"
                "COUNT I - BREACH OF CONTRACT. Kin issued a policy and refused to "
                "pay $50,000.00.\n", encoding="utf-8")
            (text_dir / "POLICY (1).txt").write_text(
                "THIS POLICY of insurance. Premium paid.\n", encoding="utf-8")
            (text_dir / "denial_letter.txt").write_text(
                "December 2, 2024. We denied and refused to pay.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            lawyer = workspace.case_brief(case)
            prose = workspace.case_brief(case, mode="prose")
            plain = prose["plain"]

            # Same findings underneath.
            self.assertEqual([f["resolved"] for f in lawyer["posture"]],
                             [f["resolved"] for f in prose["posture"]])

            self.assertIn("insurance", plain["narrative"].lower())
            self.assertIn("They broke the agreement",
                          [c["claim"] for c in plain["your_claims"]])
            self.assertEqual("Your main court filing that starts the case",
                             plain["your_documents"][0]["what_it_is"])

            # The gap survives translation, and says why a pleading is not proof.
            needs = plain["you_still_need"]
            self.assertTrue(needs)
            self.assertTrue(any("still need" in n["plain"].lower() for n in needs))
            self.assertTrue(any("not proof" in n["why"].lower() for n in needs))

            # Orientation is labelled as orientation, never as requirements.
            orientation = plain["orientation"]
            self.assertEqual("Insurance claim dispute", orientation["case_type_label"])
            self.assertIn("not a list of what your court requires", orientation["note"])
            self.assertIn("differ", orientation["verify"])
            self.assertIn("not legal advice", orientation["not_advice"].lower())

            # The lawyer brief is unchanged by any of this.
            self.assertNotIn("plain", lawyer)

    def test_two_lawsuits_in_one_folder_stay_separate_but_linked(self):
        """A denied claim and the lawyer who mishandled it are two suits.

        Filed together they read as one dispute, and a drafter merges them.
        They are kept distinct - but not severed, because the malpractice
        matter's proof lives in the insurance documents.
        """
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("inshurance")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_Stamm_Luton_v_Kin.txt").write_text(
                "ELIZABETH STAMM and KEITH LUTON v. KIN INTERINSURANCE NEXUS EXCHANGE,\n"
                "Civil Action No. 24-A-01234-5\nClaim No. HO-4291018\n"
                "COMPLAINT FOR DAMAGES.\n", encoding="utf-8")
            (text_dir / "Stamm_Luton_v_YIA_Complaint.txt").write_text(
                "ELIZABETH STAMM and KEITH LUTON v. YOUR INSURANCE ATTORNEY PLLC,\n"
                "Civil Action No. 26-C-00075-2\n"
                "COMPLAINT. Malpractice arising from claim HO-4291018.\n", encoding="utf-8")
            (text_dir / "POLICY (1).txt").write_text(
                "THIS POLICY. Claim No. HO-4291018.\n", encoding="utf-8")
            (text_dir / "random_note.txt").write_text(
                "Called the office today.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            found = workspace.matters(case)
            self.assertEqual(2, len(found["matters"]))
            first, second = found["matters"]
            self.assertIn("Kin", first["label"])
            self.assertIn("Your Insurance Attorney", second["label"])
            self.assertEqual(["24-A-01234-5"], first["dockets"])

            # Both complaints cite the same claim number - the malpractice suit
            # is ABOUT that claim - so it must not sweep the insurer's own
            # evidence into the malpractice matter.
            self.assertIn("POLICY (1).txt", first["documents"])
            self.assertNotIn("POLICY (1).txt", second["documents"])
            self.assertTrue(any(item["source"] == "POLICY (1).txt" and
                                item["matter"] == first["matter_id"]
                                for item in found["inferred"]))

            # A document with no identifying signal is left alone, not guessed.
            self.assertIn("random_note.txt", found["unassigned"])

            # Kept distinct, not severed: the link records why.
            self.assertEqual(1, len(found["connections"]))
            self.assertIn("HO-4291018", found["connections"][0]["why"])

            # Every corpus record carries its matter, so retrieval can scope.
            records = workspace._load_records(
                case.path / "reasoning_corpus" / "case_sources.jsonl")
            by_source = {r["source"]: r.get("matter") for r in records}
            self.assertEqual(first["matter_id"], by_source["POLICY (1).txt"])

    def test_a_matter_is_building_until_a_court_takes_it_in(self):
        """Whether deadlines are running is the thing not to be wrong about.

        A docket number is the strongest signal because clerks assign them and
        parties do not. A draft marker never overrides one - a file-stamped
        complaint in a folder named "draft" is still filed.
        """
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("two matters")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_Stamm_Luton_v_Kin.txt").write_text(
                "ELIZABETH STAMM and KEITH LUTON v. KIN INTERINSURANCE NEXUS EXCHANGE,\n"
                "Civil Action No. 24-A-01234-5\n"
                "FILED IN OFFICE. Clerk of the Superior Court.\n"
                "COMPLAINT FOR DAMAGES.\n", encoding="utf-8")
            (text_dir / "Stamm_Luton_v_YIA_Complaint_DRAFT.txt").write_text(
                "ELIZABETH STAMM and KEITH LUTON v. YOUR INSURANCE ATTORNEY PLLC,\n"
                "COMPLAINT (draft). Malpractice arising from the claim.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            filed, building = workspace.matters(case)["matters"]
            self.assertEqual("filed", filed["status"])
            self.assertIn("24-A-01234-5", filed["status_detail"])
            self.assertIn("may be running", filed["status_detail"])
            self.assertIn("Verify", filed["status_detail"])
            self.assertTrue(filed["filed_evidence"])

            self.assertEqual("building", building["status"])
            self.assertIn("still building", building["status_label"])
            # Lack of a docket is not represented as proof that no clock runs.
            self.assertNotIn("have not started", building["status_detail"])
            self.assertIn("Do not assume", building["status_detail"])
            self.assertIn("time limits", building["status_detail"])

    def test_each_matter_folds_only_its_own_theories_and_evidence(self):
        """Unscoped, the insurance matter reports malpractice and vice versa.

        Worse than a wrong label: an element can come back "supported" on the
        other lawsuit's documents, which is exactly the confident-and-wrong
        answer this whole layer exists to prevent.
        """
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("two matters")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_Stamm_Luton_v_Kin.txt").write_text(
                "ELIZABETH STAMM and KEITH LUTON v. KIN INTERINSURANCE NEXUS EXCHANGE,\n"
                "Civil Action No. 24-A-01234-5\nFILED IN OFFICE.\nClaim No. HO-4291018\n"
                "COUNT I - BREACH OF CONTRACT. COUNT II - BAD FAITH, the carrier delayed.\n",
                encoding="utf-8")
            (text_dir / "POLICY (1).txt").write_text(
                "THIS POLICY of insurance. Claim No. HO-4291018. Premium paid.\n", encoding="utf-8")
            (text_dir / "denial_letter.txt").write_text(
                "December 2, 2024. Claim No. HO-4291018 denied and refused to pay.\n",
                encoding="utf-8")
            (text_dir / "Stamm_Luton_v_YIA_Complaint_DRAFT.txt").write_text(
                "ELIZABETH STAMM and KEITH LUTON v. YOUR INSURANCE ATTORNEY PLLC,\n"
                "COMPLAINT (draft). LEGAL MALPRACTICE. Counsel missed the deadline.\n",
                encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            whole = {f["theory"] for f in workspace.case_posture(case)}
            self.assertEqual({"breach_of_contract", "bad_faith", "legal_malpractice"}, whole)

            kin, yia = workspace.matters(case)["matters"]
            kin_theories = {f["theory"] for f in workspace.case_posture(case, kin["matter_id"])}
            yia_theories = {f["theory"] for f in workspace.case_posture(case, yia["matter_id"])}
            self.assertEqual({"breach_of_contract", "bad_faith"}, kin_theories)
            self.assertEqual({"legal_malpractice"}, yia_theories)

            # Scoped context carries only that matter's documents.
            scoped = workspace.context(case, question="what happened",
                                       matter=yia["matter_id"])
            self.assertIn("YIA", scoped)
            self.assertNotIn("POLICY (1).txt", scoped)

            # The brief reports each matter with its own posture.
            brief = workspace.case_brief(case, matter=kin["matter_id"])
            self.assertEqual(kin["matter_id"], brief["matter_scope"])
            self.assertEqual(kin_theories, {f["theory"] for f in brief["posture"]})
            self.assertNotIn("Stamm_Luton_v_YIA_Complaint_DRAFT.txt",
                             [d["source"] for d in brief["documents"]])
            per_matter = {m["matter_id"]: {f["theory"] for f in m["posture"]}
                          for m in brief["matters"]["matters"]}
            self.assertEqual(yia_theories, per_matter[yia["matter_id"]])

    def test_drafter_server_is_reachable_only_from_this_machine(self):
        """Serving the brief removes a step; binding it wrong leaks the case.

        0.0.0.0 would expose case files to every device on the network. The
        absence of an Access-Control-Allow-Origin header is what stops another
        open tab reading the response, and the token covers what CORS does not.
        """
        import socket
        import urllib.error
        import urllib.request
        from pai_legal.drafter_server import DrafterServer

        with tempfile.TemporaryDirectory() as temp:
            page = Path(temp) / "drafter.html"
            page.write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
            server = DrafterServer(page)
            try:
                url = server.publish({"generator": "PAi Legal", "posture": [],
                                      "case": {"name": "Kin"}})
                self.assertTrue(url.startswith("http://127.0.0.1:"))
                self.assertEqual("127.0.0.1", server._server.server_address[0])
                self.assertNotEqual(8000, server.port)   # chosen, not hardcoded

                with urllib.request.urlopen(url + "/brief.json", timeout=5) as response:
                    payload = json.loads(response.read())
                    headers = dict(response.headers)
                self.assertEqual("Kin", payload["case"]["name"])
                self.assertNotIn("Access-Control-Allow-Origin", headers)
                self.assertEqual("no-store", headers.get("Cache-Control"))
                self.assertEqual("DENY", headers.get("X-Frame-Options"))
                self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))

                # A guessed path gets nothing.
                base = url.rsplit("/", 1)[0]
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(base + "/guessed/brief.json", timeout=5)
                self.assertEqual(404, caught.exception.code)
                # The server root does not reveal that a case brief is available.
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(base + "/", timeout=5)
                self.assertEqual(404, caught.exception.code)
            finally:
                server.stop()
            self.assertFalse(server.running)
            with self.assertRaises(Exception):
                urllib.request.urlopen(url + "/brief.json", timeout=3)

    def test_klein_bridge_closes(self):
        """Any two channels determine the third; like pairs annihilate."""
        self.assertTrue(parliament.verify_klein_closure())
        C = parliament.Channel
        self.assertIs(parliament.compose(C.A, C.B), C.C)
        self.assertIs(parliament.compose(C.A, C.C), C.B)
        self.assertIs(parliament.compose(C.B, C.C), C.A)
        self.assertIs(parliament.compose(C.A, C.A), C.ZERO)
        self.assertEqual(66, C.A.anchor)
        self.assertEqual(90, C.B.anchor)
        self.assertEqual(120, C.C.anchor)

    def test_a_channel_extracts_amounts(self):
        found = parliament.extract_matter(
            "Total repair cost: $24,300.00 covering 1,200 square feet", "est.txt", 4)
        kinds = {item.kind for item in found}
        self.assertIn("MONEY_BENEFIT", kinds)
        self.assertIn("MEASURE", kinds)
        self.assertEqual(24300.0, next(i.amount for i in found if i.kind == "MONEY_BENEFIT"))
        self.assertEqual("est.txt:4", found[0].cite())

    def test_amounts_are_typed_benefit_versus_extracontractual(self):
        """Bad faith needs harm the carrier's conduct caused on top of the benefit.

        A repair estimate is what the policy already owed. Letting it support
        a bad-faith claim would resolve the theory on the breach's own
        evidence, so ambiguous amounts default to benefit - the reading that
        can never manufacture bad faith.
        """
        self.assertEqual("MONEY_BENEFIT",
                         parliament.classify_amount("Roof replacement estimate: $24,300.00"))
        self.assertEqual("MONEY_EXTRA",
                         parliament.classify_amount("Attorney's fees: $18,400.00"))
        self.assertEqual("MONEY_EXTRA",
                         parliament.classify_amount("Prejudgment interest of $2,150.00"))
        self.assertEqual("MONEY_BENEFIT", parliament.classify_amount("We paid $1,000.00"))

        bad_faith = parliament.THEORY_BY_KEY["bad_faith"]
        harm = bad_faith.element_on(parliament.Channel.A)
        self.assertEqual(("MONEY_EXTRA",), harm.kinds)
        benefit = parliament.Observation(
            parliament.Channel.A, "MONEY_BENEFIT", "$24,300.00", "est.txt", 1)
        self.assertFalse(harm.accepts(benefit))

    def test_a_pleading_asserts_an_element_but_cannot_support_it(self):
        """The weakness the board exists to surface.

        Where the policy and the denial letter fix the loss channel and the
        only figure in the case appears in the complaint itself, the theory
        must report a gap - a pleading alleging a loss is not evidence of it.
        """
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Thin")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_thin.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOMES NOW Plaintiff.\n"
                "COUNT I - BREACH OF CONTRACT. Defendant issued a policy and "
                "refused to pay $50,000.00.\n", encoding="utf-8")
            (text_dir / "policy_excerpt.txt").write_text(
                "THIS POLICY of insurance covers direct physical loss. Premium paid.\n",
                encoding="utf-8")
            (text_dir / "denial_letter.txt").write_text(
                "January 2, 2025. We have denied and refused your claim.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            board = workspace.case_posture(case)
            breach = next(item for item in board if item["theory"] == "breach_of_contract")
            self.assertFalse(breach["resolved"])
            self.assertEqual(66, breach["predicted_anchor"])
            self.assertIn("matter", breach["predicted"].lower())
            loss = next(e for e in breach["elements"] if e["channel"] == "A")
            self.assertFalse(loss["supported"])
            self.assertTrue(loss["asserted_only"])
            self.assertIn("Complaint_thin.txt:3", loss["asserted_at"])
            # Pressure is reported but never promotes a status.
            self.assertIn("status unchanged", breach["pressure_note"].lower())

    def test_posture_closes_when_an_independent_document_supports_the_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Full")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_full.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOUNT I - BREACH OF CONTRACT. "
                "Defendant issued a policy and refused to pay.\n", encoding="utf-8")
            (text_dir / "policy_excerpt.txt").write_text(
                "THIS POLICY of insurance covers direct physical loss. Premium paid.\n",
                encoding="utf-8")
            (text_dir / "denial_letter.txt").write_text(
                "January 2, 2025. We have denied and refused your claim.\n", encoding="utf-8")
            (text_dir / "repair_estimate.txt").write_text(
                "Roof replacement. Total repair cost: $24,300.00\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            breach = next(item for item in workspace.case_posture(case)
                          if item["theory"] == "breach_of_contract")
            self.assertTrue(breach["resolved"])
            loss = next(e for e in breach["elements"] if e["channel"] == "A")
            self.assertTrue(loss["supported"])
            self.assertIn("repair_estimate.txt:1", loss["citations"])

    def test_negated_records_cannot_resolve_a_claim(self):
        """A denial of an element is not evidence that the element exists."""
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Negated")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOUNT I - BREACH OF CONTRACT.\n",
                encoding="utf-8")
            (text_dir / "record.txt").write_text(
                "No contract existed.\nDefendant did not breach any agreement.\n"
                "Damages: $0.00.\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            breach = next(item for item in workspace.case_posture(case)
                          if item["theory"] == "breach_of_contract")
            self.assertFalse(breach["resolved"])
            self.assertFalse(any(element["supported"] for element in breach["elements"]))

    def test_dispositive_order_does_not_manufacture_a_pleaded_theory(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Dismissed")
            text_dir = case.path / "02_text"
            (text_dir / "Order.txt").write_text(
                "ORDER OF THE COURT\nThe bad faith claim is dismissed with prejudice.\n",
                encoding="utf-8")
            workspace.build_reasoning_corpus(case)
            self.assertEqual([], workspace.case_posture(case))

    def test_oversized_first_line_cannot_hide_later_context(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Long OCR")
            text_dir = case.path / "02_text"
            (text_dir / "scan.txt").write_text(
                ("X" * 5000) + "\nA later short line identifies the hearing date.\n",
                encoding="utf-8")
            workspace.build_reasoning_corpus(case)
            context = workspace.context(case, max_characters=500)
            self.assertIn("later short line", context)
            self.assertNotIn("X" * 100, context)

    def test_bad_faith_does_not_close_on_the_policy_benefit_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Benefit only")
            text_dir = case.path / "02_text"
            (text_dir / "Complaint_bf.txt").write_text(
                "COMPLAINT FOR DAMAGES\nCOUNT II - BAD FAITH. The carrier delayed.\n",
                encoding="utf-8")
            (text_dir / "policy.txt").write_text(
                "THIS POLICY of insurance. Premium paid. Claim no. HO-1.\n", encoding="utf-8")
            (text_dir / "estimate.txt").write_text(
                "Roof replacement estimate total: $24,300.00\n", encoding="utf-8")
            workspace.build_reasoning_corpus(case)

            bad_faith = next(item for item in workspace.case_posture(case)
                             if item["theory"] == "bad_faith")
            self.assertFalse(bad_faith["resolved"])
            harm = next(e for e in bad_faith["elements"] if e["channel"] == "A")
            self.assertFalse(harm["supported"])
            self.assertIn("on top of", bad_faith["detail"].lower())

    def test_unsupported_evidence_is_preserved_even_without_extractor(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "video.bin"
            source.write_bytes(b"evidence")
            workspace = Workspace(base / "data")
            case = workspace.create_case("Evidence case")
            result = workspace.ingest(case, [source])[0]
            self.assertTrue(result.original.is_file())
            self.assertTrue(result.filed_copy.is_file())
            self.assertIsNone(result.normalized_text)
            self.assertIn("preserved", result.error.lower())
            self.assertEqual(1, workspace.list_cases()[0].document_count)

    def test_case_notes_audit_authorities_search_and_tension_are_persistent(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Audit case")
            source = Path(temp) / "order.txt"; source.write_text("Georgia court entered judgment. Georgia court entered judgment.", encoding="utf-8")
            workspace.ingest(case, [source])
            self.assertTrue(workspace.search_case(case, "judgment"))
            workspace.pin_claim(case, "The court entered judgment", "SPECULATIVE", ("[order.txt:1]",))
            workspace.pin_claim(case, "The court entered judgment", "EXPLAINED", ("[PSI:17]",))
            self.assertEqual(1, len(workspace.claim_tensions(case)))
            added = workspace.attach_authorities(case, [{"source_id":"17","title":"Stored authority","bracket":"EXPLAINED","float_points":2}])
            self.assertEqual(1, added)
            self.assertEqual(1, len(workspace.attached_authorities(case)))
            self.assertGreaterEqual(len(workspace.events(case)), 3)

    def test_single_document_reprocess_and_archive_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Reprocess case")
            source = Path(temp) / "motion.txt"; source.write_text("Original motion text.", encoding="utf-8")
            result = workspace.ingest(case, [source])[0]
            result.filed_copy.write_text("Corrected motion text. Corrected motion text.", encoding="utf-8")
            rebuilt = workspace.reprocess_document(case, result.filed_copy)
            self.assertIn("pattern_signature", rebuilt)
            self.assertIn("Corrected", Path(rebuilt["text_path"]).read_text(encoding="utf-8"))
            workspace.archive_case(case)
            self.assertFalse(workspace.list_cases())
            restored = workspace.restore_case(case.case_id)
            self.assertEqual(case.case_id, restored.case_id)

    def test_reprocess_rejects_a_file_outside_the_case(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            workspace = Workspace(base / "data")
            case = workspace.create_case("Isolated")
            external = base / "unrelated.pdf"
            external.write_bytes(b"not case evidence")
            with self.assertRaisesRegex(ValueError, "inside this case"):
                workspace.reprocess_document(case, external)

    def test_markdown_and_pdf_exports_preserve_brackets(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "data")
            case = workspace.create_case("Export case")
            workspace.pin_claim(case, "Pinned fact", "UNVERIFIED", ("[doc:1]",))
            markdown = workspace.export_case_package(case, Path(temp) / "case.md", "[[Analysis claim]]")
            pdf = workspace.export_case_package(case, Path(temp) / "case.pdf", "[[Analysis claim]]")
            self.assertIn("[{Pinned fact}]", markdown.read_text(encoding="utf-8"))
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    def test_shared_bracket_parser_drives_summary_and_ignores_sources(self):
        text = "[{One}] [[Two]] {[Three]} [[[Four]]] [PSI:17] [motion.txt:2]"
        parsed = list(brackets.spans(text))
        self.assertEqual(["UNVERIFIED", "SPECULATIVE", "EXPLAINED", "VALIDATED"],
                         [item[2].name for item in parsed])
        self.assertEqual(4, sum(brackets.count_names(text).values()))
        self.assertIn("Pressure observed; status unchanged", brackets.summary(text))
        self.assertEqual(["[PSI:17]", "[motion.txt:2]"],
                         [item[2] for item in brackets.source_spans(text)])

    def test_case_transition_map_is_cached_and_exported(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "estimate.txt"
            source.write_text(
                "Smith v. Acme Insurance Company. January 2, 2025. "
                "Total repair amount $24,300.00. Georgia Court of Appeals.",
                encoding="utf-8",
            )
            workspace = Workspace(base / "data")
            case = workspace.create_case("Smith v. Acme")
            workspace.ingest(case, [source])

            first = workspace.case_transition_map(case)
            second = workspace.case_transition_map(case)
            self.assertEqual(first.replay_signature, second.replay_signature)
            self.assertEqual(first.deterministic_seed, second.deterministic_seed)
            self.assertTrue((case.path / "05_trace" / "case_transition_map.json").is_file())

            destination = workspace.export_case_package(case, base / "record.md")
            exported = destination.read_text(encoding="utf-8")
            self.assertIn("Precognitive Case Map", exported)
            self.assertIn(first.replay_signature, exported)
            self.assertIn("Relational pressure cannot promote a Trust Lock", exported)


class IngestionTests(unittest.TestCase):
    def test_image_uses_bundled_tesseract_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            executable = base / "tesseract.exe"
            executable.write_bytes(b"fixture")
            image = base / "scan.png"
            image.write_bytes(b"fixture")
            extractor = TextExtractor(tesseract=executable)
            completed = __import__("subprocess").CompletedProcess([], 0, "OCR legal text\n", "")
            with patch("pai_legal.ingestion.subprocess.run", return_value=completed) as run:
                result = extractor.extract(image)
            self.assertEqual("tesseract-ocr", result.method)
            self.assertEqual(1, result.ocr_pages)
            self.assertIn("OCR legal text", result.text)
            self.assertEqual("stdout", run.call_args.args[0][2])

    def test_scanned_pdf_automatically_falls_back_to_ocr(self):
        import pymupdf

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            executable = base / "tesseract.exe"
            executable.write_bytes(b"fixture")
            pdf = base / "scan.pdf"
            document = pymupdf.open()
            document.new_page()
            document.save(pdf)
            document.close()
            extractor = TextExtractor(tesseract=executable)
            with patch.object(extractor, "_ocr", return_value="Scanned court order"):
                result = extractor.extract(pdf)
            self.assertEqual("pdf-text+tesseract", result.method)
            self.assertEqual(1, result.pages)
            self.assertEqual(1, result.ocr_pages)
            self.assertIn("<<<PAGE 1>>>", result.text)
            self.assertIn("Scanned court order", result.text)


class CorpusTests(unittest.TestCase):
    def test_sqlite_fts_retrieval_returns_only_stored_record(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "casehold_test.db"
            connection = sqlite3.connect(database)
            connection.executescript("""
                CREATE TABLE docs (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    jurisdiction TEXT,
                    year INTEGER,
                    text TEXT,
                    shard TEXT,
                    source_row INTEGER,
                    float_points INTEGER,
                    mix_points INTEGER,
                    stir_points INTEGER,
                    total_pressure REAL,
                    float_color TEXT,
                    mix_color TEXT,
                    stir_color TEXT,
                    bracket TEXT,
                    pattern_signature TEXT
                );
                CREATE VIRTUAL TABLE titles USING fts5(title, content='docs', content_rowid='id');
                INSERT INTO docs VALUES (
                    1, 'Smith v. Jones — Summary Judgment', 'GA', 2024,
                    'The stored opinion discusses summary judgment.', 'fixture', 17,
                    12, 5, 3, 24.5, 'GREEN', 'YELLOW', 'ORANGE', 'EXPLAINED', 'abc123'
                );
                INSERT INTO titles(titles) VALUES('rebuild');
            """)
            connection.commit()
            connection.close()
            corpus = PSiCorpus({"shards": str(database)})
            results = corpus.search("summary judgment", jurisdiction="GA")
            self.assertEqual(1, len(results))
            self.assertEqual("Smith v. Jones — Summary Judgment", results[0].title)
            self.assertEqual("17", results[0].source_row)
            self.assertEqual((12, 5, 3), (results[0].float_points, results[0].mix_points, results[0].stir_points))
            self.assertEqual("EXPLAINED", results[0].bracket)
            self.assertEqual("abc123", results[0].pattern_signature)

    def test_service_search_is_loopback_authenticated_and_uses_post(self):
        observed = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_POST(self):
                observed["path"] = self.path
                observed["authorization"] = self.headers.get("Authorization")
                size = int(self.headers.get("Content-Length", "0"))
                observed["body"] = json.loads(self.rfile.read(size))
                body = json.dumps({"results": [{"source_id": "17", "title": "Stored"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            results = PSiCorpus({"api_url": url, "api_token": "secret"}).search("privileged fact")
            self.assertEqual("17", results[0].source_id)
            self.assertEqual("/v1/corpus/search", observed["path"])
            self.assertEqual("Bearer secret", observed["authorization"])
            self.assertEqual("privileged fact", observed["body"]["q"])
        finally:
            server.shutdown()
            server.server_close()
        with self.assertRaises(CorpusError):
            PSiCorpus({"api_url": "http://127.0.0.1:8082"})
        with self.assertRaises(CorpusError):
            PSiCorpus({"api_url": "https://example.com", "api_token": "secret"})


class _LFMHandler(BaseHTTPRequestHandler):
    token = "test-session-token"
    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self.send_response(401); self.end_headers(); return
        if self.path in {"/health", "/v1/models"}:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self.send_response(401); self.end_headers(); return
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size))
        content = payload["messages"][1]["content"]
        assert "[motion.txt:2]" in content
        assert "[PSI:1]" in content
        body = json.dumps({"choices": [{"message": {"content": "Supported by [motion.txt:2] and [PSI:1]."}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PrivateAITests(unittest.TestCase):
    def test_openai_compatible_provider_receives_case_and_authority_sources(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _LFMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            client = PrivateAIClient({"api_url": url, "api_key": _LFMHandler.token}, timeout=5)
            answer = client.complete(
                "What supports the filing date?",
                "[motion.txt:2] Filed August 1.",
                [{"source_id": "1", "title": "Stored case", "excerpt": "Stored holding"}],
            )
            self.assertIn("[PSI:1]", answer)
            self.assertTrue(answer.startswith("[["))
        finally:
            server.shutdown()
            server.server_close()

    def test_validated_permission_is_claim_specific(self):
        allowed = enforce_brackets(
            "[[[The order was entered.]]]", validated_claims=["The order was entered."])
        unrelated = enforce_brackets(
            "[[[An unrelated model claim.]]]", validated_claims=["The order was entered."])
        self.assertEqual("[[[The order was entered.]]]", allowed)
        self.assertEqual("[[An unrelated model claim.]]", unrelated)

    def test_private_ai_rejects_unauthenticated_or_remote_endpoints(self):
        with self.assertRaisesRegex(Exception, "authentication token"):
            PrivateAIClient({"api_url": "http://127.0.0.1:9"}, timeout=1).start()
        with self.assertRaisesRegex(Exception, "loopback"):
            PrivateAIClient({"api_url": "https://example.com", "api_key": "x"}, timeout=1).start()

    def test_model_cannot_self_award_validated_status(self):
        self.assertEqual("[[claim]]", enforce_brackets("[[[claim]]]"))


class PrimitiveTests(unittest.TestCase):
    def test_raw_number_demotes_validated_mix_and_preserves_mass_tau(self):
        measured = BracketFloat(10, BracketType.VALIDATED, lineage=("court-record",))
        result = mix(measured, 20)
        self.assertEqual(BracketType.UNVERIFIED, result.bracket_type)
        self.assertEqual(2, result.mass)
        self.assertEqual(1, result.tau)
        self.assertIn("court-record", result.lineage)

    def test_stir_is_deterministic_weighted_reduction(self):
        values = (BracketFloat(10, BracketType.EXPLAINED), BracketFloat(20, BracketType.EXPLAINED))
        result = stir(values, weights=(1, 3))
        self.assertEqual(17.5, float(result))
        self.assertEqual(BracketType.EXPLAINED, result.bracket_type)

    def test_all_canonical_notations_parse(self):
        self.assertEqual(BracketType.UNVERIFIED, bracket_name("[{ }]") )
        self.assertEqual(BracketType.SPECULATIVE, bracket_name("[[ ]]") )
        self.assertEqual(BracketType.EXPLAINED, bracket_name("{[ ]}") )
        self.assertEqual(BracketType.VALIDATED, bracket_name("[[[ ]]]") )

    def test_legal_rpm_creates_float_mix_stir_without_promoting_bracket(self):
        text = "Court of Appeals of Georgia. January 2, 2024. Georgia court cited § 9-11-56. Georgia court cited § 9-11-56."
        state, lock = rpm_process(text, {"year": 2024, "jurisdiction": "Georgia"})
        self.assertGreater(len(state.float), 0)
        self.assertGreater(len(state.mix), 0)
        self.assertGreater(len(state.stir), 0)
        self.assertEqual("UNVERIFIED", lock["bracket"])

    def test_cross_carry_is_bounded_and_amounts_enter_matter_layer(self):
        text = (
            "Smith v. Acme Insurance Company. January 2, 2024. "
            "Total repair amount $24,300.00 covering 1,200 square feet. "
            "Georgia court cited § 9-11-56. Georgia court cited § 9-11-56."
        )
        state, lock = rpm_process(text, {"source": "estimate.txt", "year": 2024})
        record = state_record(state, lock, source="estimate.txt")
        self.assertTrue(any(item[0] == "AMOUNT" for item in state.float.points))
        relation_values = [item[1] for item in state.mix.points] + [item[1] for item in state.stir.points]
        self.assertTrue(relation_values)
        self.assertLess(max(map(len, relation_values)), 300)
        self.assertLess(len(state.mix) + len(state.stir), 100)


class TransitionMapTests(unittest.TestCase):
    @staticmethod
    def record(source: str, bracket: str = "UNVERIFIED") -> dict:
        text = (
            "Smith v. Acme Insurance Company. January 2, 2025. "
            "Total repair amount $24,300.00. Court of Appeals of Georgia. "
            "Smith v. Acme Insurance Company. January 2, 2025."
        )
        state, lock = rpm_process(text, {"source": source, "year": 2025})
        record = state_record(state, lock, source=source)
        record["bracket"] = bracket
        return record

    def test_klein_channels_close(self):
        self.assertTrue(verify_klein_closure())
        self.assertIs(compose(Channel.A, Channel.B), Channel.C)
        self.assertIs(compose(Channel.A, Channel.C), Channel.B)
        self.assertIs(compose(Channel.B, Channel.C), Channel.A)
        self.assertIs(compose(Channel.A, Channel.A), Channel.ZERO)

    def test_recursive_map_replays_identically(self):
        record = self.record("estimate.txt")
        first = build_case_transition_map("CASE-1", "Smith v. Acme", [record])
        second = build_case_transition_map("CASE-1", "Smith v. Acme", [record])
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.replay_signature, second.replay_signature)
        root = first.view()
        self.assertEqual(1, len(root.edges))
        self.assertTrue(root.edges[0].focus_view)
        document = first.view(root.edges[0].focus_view)
        self.assertEqual("root", document.parent)
        self.assertEqual({"FLOAT", "MIX", "STIR"}, {node.kind for node in document.nodes})
        self.assertTrue(all(node.focus_view for node in document.nodes))
        layer = first.view(document.nodes[1].focus_view)
        self.assertEqual(document.id, layer.parent)

    def test_pressure_does_not_promote_a_trust_lock(self):
        explained = self.record("explained.txt", "EXPLAINED")
        unverified = self.record("unverified.txt", "UNVERIFIED")
        # Make pressure visibly large; status must remain the stored lock.
        explained["total_pressure"] = 1_000_000
        unverified["total_pressure"] = 2_000_000
        model = build_case_transition_map("CASE-2", "Guard", [explained, unverified])
        locks = {edge.label: edge.bracket for edge in model.view().edges}
        self.assertEqual("EXPLAINED", locks["explained.txt"])
        self.assertEqual("UNVERIFIED", locks["unverified.txt"])
        judge = next(item for item in model.projections if item.role == "Precedent Judge")
        self.assertEqual("UNVERIFIED", judge.bracket)


class ProfessionalControlTests(unittest.TestCase):
    class Protector:
        description = "test protected store"

        @staticmethod
        def protect(value):
            return b"protected:" + bytes(value)[::-1]

        @staticmethod
        def unprotect(value):
            if not value.startswith(b"protected:"):
                raise ValueError("invalid ciphertext")
            return value[len(b"protected:"):][::-1]

    def test_secret_store_never_writes_plaintext(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SecretStore(Path(temp), protector=self.Protector())
            store.set("psi-token", "highly-confidential")
            self.assertEqual("highly-confidential", store.get("psi-token"))
            self.assertNotIn("highly-confidential", store.path.read_text(encoding="utf-8"))
            self.assertEqual(["psi-token"], store.names())
            self.assertTrue(store.delete("psi-token"))

    def test_os_account_roles_deny_unapproved_case_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = AccessController(root, username="firm\\owner")
            workspace = Workspace(root, access=owner,
                                  secret_store=SecretStore(root, protector=self.Protector()))
            workspace.create_case("Existing")
            workspace.assign_role("firm\\reviewer", "auditor")
            self.assertTrue(workspace.verify_workspace_audit()["valid"])
            reviewer = AccessController(root, username="firm\\reviewer")
            restricted = Workspace(root, access=reviewer,
                                   secret_store=SecretStore(root, protector=self.Protector()))
            self.assertEqual(1, len(restricted.list_cases()))
            with self.assertRaises(AccessDenied):
                restricted.create_case("Unauthorized")

    def test_strict_storage_policy_blocks_writes_without_verified_encryption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = StoragePolicy(root, status_probe=lambda _path:
                                   EncryptionStatus(False, "fixture", "protection off", "X:"))
            policy.set_enforcement(True)
            workspace = Workspace(root, storage_policy=policy,
                                  secret_store=SecretStore(root, protector=self.Protector()))
            with self.assertRaisesRegex(PermissionError, "encrypted workspace"):
                workspace.create_case("Blocked")

    def test_keyed_audit_chain_detects_tampering_and_refuses_to_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = Workspace(root, secret_store=SecretStore(root, protector=self.Protector()))
            case = workspace.create_case("Audited")
            workspace.pin_claim(case, "The motion was filed", "UNVERIFIED")
            verified = workspace.verify_audit(case)
            self.assertTrue(verified["valid"])
            self.assertEqual(2, verified["events"])

            path = case.path / "audit" / "epistemic_events.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            rolled_back = workspace.verify_audit(case)
            self.assertFalse(rolled_back["valid"])
            self.assertIn("rollback", " ".join(rolled_back["errors"]).lower())

            path.write_text("\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")
            rows[0]["payload"]["name"] = "altered after the fact"
            path.write_text("\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")
            self.assertFalse(workspace.verify_audit(case)["valid"])
            with self.assertRaisesRegex(RuntimeError, "refusing to append"):
                workspace.append_event(case, "should_not_append", {})

    def test_retention_and_legal_hold_control_disposition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = Workspace(root, secret_store=SecretStore(root, protector=self.Protector()))
            case = workspace.create_case("Retention")
            workspace.set_retention(case, "2000-01-01", "Approved firm retention policy")
            self.assertTrue(workspace.disposition_status(case)["eligible"])
            workspace.place_legal_hold(case, "Threatened related litigation")
            held = workspace.disposition_status(case)
            self.assertFalse(held["eligible"])
            self.assertTrue(held["legal_hold"])
            workspace.release_legal_hold(case, "Written release approved by responsible lawyer")
            self.assertTrue(workspace.disposition_status(case)["eligible"])

    def test_conflict_screening_matches_normalized_entities_across_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = Workspace(root, secret_store=SecretStore(root, protector=self.Protector()))
            existing = workspace.create_case("Smith v. Acme LLC")
            hits = workspace.conflict_check(["Acme Incorporated"])
            self.assertEqual(1, len(hits))
            self.assertEqual(existing.case_id, hits[0]["case_id"])
            self.assertEqual("exact", hits[0]["confidence"])

    def test_encrypted_backup_round_trip_and_authentication(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source_root = base / "source"
            source_workspace = Workspace(
                source_root, secret_store=SecretStore(source_root, protector=self.Protector()))
            case = source_workspace.create_case("Backup")
            evidence = base / "evidence.txt"
            evidence.write_text("Privileged client material.", encoding="utf-8")
            source_workspace.ingest(case, [evidence])
            backup = source_workspace.backup_case(
                case, base / "case.pailbackup", "a strong backup passphrase")
            self.assertTrue(backup.read_bytes().startswith(b"PAILBKP1"))
            self.assertNotIn(b"Privileged client material", backup.read_bytes())

            restore_root = base / "restore"
            restored_workspace = Workspace(
                restore_root, secret_store=SecretStore(restore_root, protector=self.Protector()))
            restored = restored_workspace.restore_case_backup(backup, "a strong backup passphrase")
            self.assertEqual(case.case_id, restored.case_id)
            restored_originals = list((restored.path / "01_originals").glob("evidence*.txt"))
            self.assertEqual("Privileged client material.", restored_originals[0].read_text(encoding="utf-8"))
            self.assertTrue(restored_workspace.verify_audit(restored)["valid"])
            self.assertTrue(restored_workspace.verify_evidence_integrity(restored)["valid"])
            restored_originals[0].write_text("altered", encoding="utf-8")
            self.assertFalse(restored_workspace.verify_evidence_integrity(restored)["valid"])

            wrong_root = base / "wrong"
            wrong_workspace = Workspace(
                wrong_root, secret_store=SecretStore(wrong_root, protector=self.Protector()))
            with self.assertRaisesRegex(ValueError, "authentication failed"):
                wrong_workspace.restore_case_backup(backup, "the wrong passphrase")

    def test_federal_and_georgia_rule_packs_flag_mechanical_filing_risks(self):
        identifiers = {item["id"] for item in available_rule_packs()}
        self.assertEqual({"GA-SUPERIOR-CIVIL", "US-FEDERAL-CIVIL"}, identifiers)
        federal = validate_filing(
            "UNITED STATES DISTRICT COURT\nSmith v. Jones\nCivil Action No. 1:26-cv-1\n"
            "SSN 123-45-6789\nRespectfully submitted /s/ Smith",
            "federal", "complaint")
        codes = {item["code"] for item in federal["findings"]}
        self.assertIn("FRCP-5.2-SSN", codes)
        self.assertFalse(federal["passed"])

        georgia = validate_filing(
            "In the Superior Court of Fulton County, Georgia\nSmith v. Jones\n"
            "Civil Action No. [NEEDED: assigned]\nRespectfully submitted /s/ Smith",
            "GA", "complaint", {"county": "Fulton"})
        ga_codes = {item["code"] for item in georgia["findings"]}
        self.assertIn("GA-CASE-FILING-FORM", ga_codes)
        self.assertTrue(georgia["passed"])


class ModeTests(unittest.TestCase):
    def report(self, analysis: bool, corpus: bool) -> CapabilityReport:
        return CapabilityReport({
            Capability.WORKSPACE: CapabilityStatus(Capability.WORKSPACE, True, "ready"),
            Capability.ANALYSIS: CapabilityStatus(Capability.ANALYSIS, analysis, "analysis"),
            Capability.CORPUS: CapabilityStatus(Capability.CORPUS, corpus, "corpus"),
        })

    def test_all_four_modes(self):
        self.assertTrue(self.report(False, False).mode.startswith("Workspace"))
        self.assertTrue(self.report(True, False).mode.startswith("Analysis"))
        self.assertTrue(self.report(False, True).mode.startswith("Research"))
        self.assertTrue(self.report(True, True).mode.startswith("Full"))


class ModelSelectionTests(unittest.TestCase):
    def profile(self, ram: float, available: float, disk: float) -> HardwareProfile:
        return HardwareProfile(ram, available, disk, 8, "AMD64")

    def test_recommends_strongest_vetted_model_that_safely_fits(self):
        model = recommend_model(self.profile(32, 24, 100))
        self.assertIsNotNone(model)
        self.assertEqual("qwen3-8b", model.key)

    def test_storage_reserve_can_reject_otherwise_compatible_model(self):
        models = compatible_models(self.profile(64, 48, 4))
        self.assertFalse(models)

    def test_downloaded_model_must_match_its_published_digest(self):
        class Response:
            status = 200
            headers = {"Content-Length": "7"}

            def __init__(self):
                import io
                self.body = io.BytesIO(b"hostile")

            def read(self, size=-1):
                return self.body.read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        model = ModelCandidate(
            "fixture", "Fixture", "owner/repo", "model.gguf", 1, 1, 1024, 1,
            revision="a" * 40, sha256="0" * 64)
        with tempfile.TemporaryDirectory() as temp:
            with patch("pai_legal.models.urllib.request.urlopen", return_value=Response()):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    download_model(model, Path(temp))
            self.assertFalse((Path(temp) / "model.gguf").exists())
            self.assertFalse((Path(temp) / "model.gguf.part").exists())


class StandaloneCapabilityTests(unittest.TestCase):
    def test_analysis_uses_pai_legal_installation_not_an_external_product(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / "model.gguf"; model.write_bytes(b"model")
            runtime = root / "llama-server.exe"; runtime.write_bytes(b"runtime")
            config = root / "PAiLegal" / "config" / "ai_installation.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"model_label": "fixture", "model_path": str(model), "runtime_path": str(runtime), "context": 8192}), encoding="utf-8")
            with patch.dict("os.environ", {"LOCALAPPDATA": str(root), "PAI_LEGAL_AI_URL": "http://127.0.0.1:1"}, clear=False):
                status = detect_analysis()
            self.assertTrue(status.available)
            self.assertIn("fixture", status.summary)

    def test_psi_service_token_can_come_from_the_dpapi_vault(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _LFMHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                local = Path(temp)
                SecretStore(local / "PAiLegal").set("psi_legal_api_token", _LFMHandler.token)
                with patch.dict("os.environ", {
                    "LOCALAPPDATA": str(local),
                    "PSI_LEGAL_URL": f"http://127.0.0.1:{server.server_port}",
                    "PSI_LEGAL_TOKEN": "",
                }, clear=False):
                    status = detect_corpus()
                self.assertTrue(status.available)
                self.assertEqual(_LFMHandler.token, status.resources["api_token"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
