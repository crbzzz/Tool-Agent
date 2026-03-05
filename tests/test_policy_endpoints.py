import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from rag.api.main import app
from rag.state.audit_log import append_audit


class TestPolicyAndAuditEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name).resolve()
        self.client = TestClient(app)

        self.policy_state_path = self.tmpdir / "policy_state.json"
        self.audit_path = self.tmpdir / "audit.jsonl"

        self.env_patch = patch.dict(
            os.environ,
            {
                "WORKSPACE_ROOT": str(self.tmpdir),
                "ALLOWED_ROOTS": str(self.tmpdir),
                "ACCESS_MODE": "safe",
                "SECURITY_POLICY_STATE_PATH": str(self.policy_state_path),
                "SECURITY_AUDIT_PATH": str(self.audit_path),
            },
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self._tmp.cleanup()

    def test_get_policy(self):
        r = self.client.get("/policy")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        policy = payload.get("policy")
        self.assertIsInstance(policy, dict)
        self.assertEqual(policy.get("access_mode"), "safe")
        self.assertEqual(Path(policy.get("workspace_root")).resolve(), self.tmpdir)

    def test_set_policy_mode_requires_confirmation(self):
        r = self.client.post("/policy/mode", json={"mode": "full_disk"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Confirmation required", (r.json() or {}).get("detail", ""))

    def test_set_policy_mode_persists_override(self):
        r = self.client.post(
            "/policy/mode",
            json={"mode": "full_disk", "user_confirmation": True},
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload["policy"]["access_mode"], "full_disk")

        r2 = self.client.get("/policy")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["policy"]["access_mode"], "full_disk")

    def test_audit_recent_reads_entries(self):
        append_audit(action="unit_test", status="ok", extra={"k": "v"})

        r = self.client.get("/audit/recent?limit=10")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        entries = payload.get("entries")
        self.assertIsInstance(entries, list)
        self.assertTrue(any(e.get("action") == "unit_test" for e in entries))
