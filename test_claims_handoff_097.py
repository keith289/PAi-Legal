import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pai_legal.claims_handoff import (
    handoff_summary, link_claims_workspace, merge_projection_into_case_sources,
    project_claims_graph, read_legal_extensions, record_legal_extension,
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HandoffTests(unittest.TestCase):
    def make_claims(self, root: Path):
        (root / "pai_legal").mkdir(parents=True)
        (root / "audit").mkdir()
        (root / "pai_case_manifest.json").write_text(json.dumps({
            "schema": "pai.shared-case-workspace", "schema_version": 1,
            "workspace_id": "ws-test-123", "products": ["pai-claims", "pai-legal"],
            "folders": {"paiLegal": "pai_legal"},
            "files": {"claim": "claim.json", "case_graph": "case_graph.json"},
        }), encoding="utf-8")
        claim = {"claim_id": "claim-1", "name": "Smith Roof Claim", "state_revision": "rev-1", "updated_at": "2026-08-31T00:00:00+00:00"}
        (root / "claim.json").write_text(json.dumps(claim, indent=2), encoding="utf-8")
        claim_hash = sha(root / "claim.json")
        graph = {
            "schema": "pai.case-graph", "schema_version": 2, "source_product": "pai-claims", "source_version": "1.3.2",
            "state_revision": "rev-1", "updated_at": "2026-08-31T00:00:00+00:00",
            "handoff": {"ready": True, "writer_version": "1.3.2", "state_revision": "rev-1", "claim_file_sha256": claim_hash},
            "version": 1,
            "nodes": [
                {
                    "id": "quantity:roof:1", "kind": "quantity", "statement": "Roof area is 32 squares",
                    "bracket": "VALIDATED", "channel": "matter_k66", "reason": "Independent measurement",
                    "sourceEvidenceIds": ["ev-1"], "provenanceRoots": ["adjuster-measurement"],
                    "history": [
                        {"action": "created", "toBracket": "SPECULATIVE", "reason": "photo inference"},
                        {"action": "promoted", "fromBracket": "SPECULATIVE", "toBracket": "VALIDATED", "reason": "measurement"},
                    ],
                },
                {
                    "id": "cause:roof:1", "kind": "cause", "statement": "Wind caused the opening",
                    "bracket": "CONTRADICTED", "channel": "relation_k90", "reason": "Carrier disputes cause",
                    "sourceEvidenceIds": ["ev-2"], "provenanceRoots": ["carrier-letter"],
                    "history": [
                        {"action": "created", "toBracket": "EXPLAINED", "reason": "engineer report"},
                        {"action": "contradicted", "fromBracket": "EXPLAINED", "toBracket": "CONTRADICTED", "reason": "carrier denial"},
                    ],
                },
            ],
            "edges": [
                {"id": "edge-1", "fromNodeId": "cause:roof:1", "toNodeId": "quantity:roof:1", "kind": "related_to",
                 "bracket": "EXPLAINED", "reason": "same roof", "sourceEvidenceIds": [], "provenanceRoots": [], "history": []}
            ],
        }
        (root / "case_graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")

    def test_handoff_never_rewrites_claims_graph(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            claims = base / "claims"; claims.mkdir()
            legal = base / "legal"; legal.mkdir()
            self.make_claims(claims)
            before = sha(claims / "case_graph.json")
            record = link_claims_workspace(legal, claims)
            after = sha(claims / "case_graph.json")
            self.assertEqual(before, after)
            self.assertTrue(Path(record["overlay_path"]).is_dir())
            self.assertTrue(handoff_summary(Path(record["overlay_path"]))["linked"])

    def test_atomic_bracket_provenance_and_history_survive_projection(self):
        with tempfile.TemporaryDirectory() as td:
            claims = Path(td); self.make_claims(claims)
            records = project_claims_graph(claims)
            quantity = next(r for r in records if r.get("claim_node_id") == "quantity:roof:1")
            self.assertEqual(quantity["source_bracket"], "VALIDATED")
            self.assertEqual(quantity["provenanceRoots"], ["adjuster-measurement"])
            self.assertEqual(len(quantity["history"]), 2)
            cause = next(r for r in records if r.get("claim_node_id") == "cause:roof:1")
            self.assertEqual(cause["source_bracket"], "CONTRADICTED")
            self.assertEqual(cause["bracket"], "EXPLAINED")
            self.assertTrue(cause["contradicted"])

    def test_legal_extensions_are_separate(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); claims = base / "claims"; claims.mkdir(); legal = base / "legal"; legal.mkdir()
            self.make_claims(claims)
            record = link_claims_workspace(legal, claims)
            overlay = Path(record["overlay_path"])
            before = sha(claims / "case_graph.json")
            node = record_legal_extension(
                overlay, "Carrier failed to pay the full covered amount", "EXPLAINED",
                ["[CLAIMS:quantity:roof:1]"], "legal_proposition",
            )
            self.assertEqual(node["sourceClaimsNodeIds"], ["quantity:roof:1"])
            self.assertEqual(before, sha(claims / "case_graph.json"))
            self.assertEqual(len(read_legal_extensions(overlay)["nodes"]), 1)
            count = merge_projection_into_case_sources(overlay)
            self.assertEqual(count, 3)

    def test_stale_131_graph_is_refused_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            claims = Path(td); self.make_claims(claims)
            graph_path = claims / "case_graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["source_version"] = "1.3.1"
            graph["handoff"] = {"ready": False, "writer_version": "1.3.1"}
            graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not handoff-ready"):
                project_claims_graph(claims)

    def test_revision_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            claims = Path(td); self.make_claims(claims)
            graph_path = claims / "case_graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["state_revision"] = "older-revision"
            graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "same persisted revision"):
                project_claims_graph(claims)

    def test_claim_hash_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            claims = Path(td); self.make_claims(claims)
            claim_path = claims / "claim.json"
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            claim["name"] = "Changed after graph write"
            claim_path.write_text(json.dumps(claim, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "persisted claim and graph do not match"):
                project_claims_graph(claims)


if __name__ == "__main__":
    unittest.main()
