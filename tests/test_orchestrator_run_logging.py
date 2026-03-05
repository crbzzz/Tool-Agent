import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag.agent.orchestrator import AgentOrchestrator
from rag.agent.tool_registry import ToolRegistry
from rag.state import runs


class _FakeMistralClient:
    def __init__(self):
        self.calls = 0

    def complete_with_role_fallback(self, agent_id, messages):
        self.calls += 1
        # First response: request a tool call.
        if self.calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {"name": "dummy_tool", "arguments": {"path": "C:/secret.txt", "token": "abcd"}},
                                }
                            ],
                        }
                    }
                ]
            }

        # Second response: final answer.
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "{\"type\":\"text\",\"answer\":\"done\",\"blocks\":[{\"type\":\"text\",\"content\":\"done\"}],\"sources\":[],\"grounded\":true}",
                    }
                }
            ]
        }


class TestOrchestratorRunLogging(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name).resolve()
        self.db_path = self.tmpdir / "runs.sqlite"

        self.env_patch = patch.dict(
            os.environ,
            {
                "RUNS_DB_PATH": str(self.db_path),
                "WORKSPACE_ROOT": str(self.tmpdir),
                "ALLOWED_ROOTS": str(self.tmpdir),
                "ACCESS_MODE": "safe",
                "OBS_REDACT_PATTERNS": "token",
            },
            clear=False,
        )
        self.env_patch.start()

        runs._STORE = None  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        self.env_patch.stop()
        self._tmp.cleanup()

    def test_tool_trace_written(self):
        def dummy_tool(args):
            return {"ok": True, "data": {"items": [1, 2, 3]}, "error": None}

        orch = AgentOrchestrator(
            mistral_client=_FakeMistralClient(),
            agent_id="agent",
            registry=ToolRegistry(tools={"dummy_tool": dummy_tool}),
            max_tool_steps=2,
        )

        result, _updated = orch.run_with_messages([
            {"role": "system", "content": "policy"},
            {"role": "user", "content": "hi"},
        ], user_id="u1")

        self.assertTrue(result.run_id)

        run = runs.get_run(result.run_id)
        self.assertIsNotNone(run)
        tool_calls = run.get("tool_calls")
        self.assertIsInstance(tool_calls, list)
        self.assertGreaterEqual(len(tool_calls), 1)

        tc0 = tool_calls[0]
        self.assertEqual(tc0.get("tool_name"), "dummy_tool")
        # Ensure args_summary is redacted (token, and path shape).
        self.assertIn("<redacted>", (tc0.get("args_summary") or ""))
