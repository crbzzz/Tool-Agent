import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from rag.api.main import app
from rag.state import runs


class TestRunsEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name).resolve()
        self.client = TestClient(app)

        self.db_path = self.tmpdir / "runs.sqlite"

        self.env_patch = patch.dict(
            os.environ,
            {
                "RUNS_DB_PATH": str(self.db_path),
                "WORKSPACE_ROOT": str(self.tmpdir),
                "ALLOWED_ROOTS": str(self.tmpdir),
                "ACCESS_MODE": "safe",
            },
            clear=False,
        )
        self.env_patch.start()

        # Reset singleton store between tests.
        runs._STORE = None  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        self.env_patch.stop()
        self._tmp.cleanup()

    def test_recent_and_get_run(self):
        run_id = runs.start_run(user_id="u1", input_summary="hello")
        runs.finish_run(run_id, status="success", error_message=None, output_type="text", grounded=True)

        r = self.client.get("/runs/recent?limit=50")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        items = payload.get("runs")
        self.assertIsInstance(items, list)
        self.assertTrue(any(x.get("run_id") == run_id for x in items))

        r2 = self.client.get(f"/runs/{run_id}")
        self.assertEqual(r2.status_code, 200)
        payload2 = r2.json()
        self.assertTrue(payload2.get("ok"))
        self.assertEqual(payload2.get("run", {}).get("run_id"), run_id)
        self.assertIsInstance(payload2.get("run", {}).get("tool_calls"), list)

    def test_limit_works(self):
        ids = []
        for i in range(3):
            rid = runs.start_run(user_id="u", input_summary=f"m{i}")
            runs.finish_run(rid, status="success", error_message=None, output_type="text", grounded=None)
            ids.append(rid)

        r = self.client.get("/runs/recent?limit=2")
        self.assertEqual(r.status_code, 200)
        items = r.json().get("runs")
        self.assertEqual(len(items), 2)

    def test_stats_summary(self):
        rid = runs.start_run(user_id="u", input_summary="x")
        runs.finish_run(rid, status="error", error_message="token=abcd", output_type="text", grounded=None)

        r = self.client.get("/stats/summary?days=7")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        stats = payload.get("stats")
        self.assertIsInstance(stats, dict)
        self.assertIn("total_runs", stats)
        self.assertIn("success_rate", stats)
        self.assertIn("error_rate", stats)
