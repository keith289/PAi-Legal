import json
import tempfile
import urllib.request
import unittest
from pathlib import Path

from pai_legal.workspace import Workspace


class CompanionServerTests(unittest.TestCase):
    def test_companion_server_rest_api(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Workspace(Path(td))
            case = workspace.create_case("Test Case")

            # Start companion REST server on loopback
            status = workspace.start_companion_server(host="127.0.0.1", port=8099)
            self.assertTrue(status["running"])
            token = status["pairing_token"]
            url = status["url"]

            try:
                # 1. Check status (unauthenticated)
                req = urllib.request.Request(f"{url}/api/status")
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(data["status"], "online")

                # 2. List cases (authenticated)
                req = urllib.request.Request(
                    f"{url}/api/cases",
                    headers={"Authorization": f"Bearer {token}"}
                )
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    cases = data["cases"]
                    self.assertEqual(len(cases), 1)
                    self.assertEqual(cases[0]["case_id"], case.case_id)

                # 3. Upload evidence from companion app
                upload_payload = json.dumps({
                    "filename": "mobile_photo_notes.txt",
                    "text": "Site inspection photo taken on mobile device at 10:00 AM."
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{url}/api/cases/{case.case_id}/evidence",
                    data=upload_payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(data["status"], "ok")

                # 4. List files and read uploaded file
                req = urllib.request.Request(
                    f"{url}/api/cases/{case.case_id}/files",
                    headers={"Authorization": f"Bearer {token}"}
                )
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    files = data["files"]
                    self.assertTrue(any(f["stem"] == "mobile_photo_notes" for f in files))

                req = urllib.request.Request(
                    f"{url}/api/cases/{case.case_id}/files/mobile_photo_notes.txt",
                    headers={"Authorization": f"Bearer {token}"}
                )
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("Site inspection photo", data["content"])

            finally:
                workspace.stop_companion_server()


if __name__ == "__main__":
    unittest.main()
