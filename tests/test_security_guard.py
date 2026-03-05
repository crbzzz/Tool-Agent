import tempfile
import unittest
from pathlib import Path

from rag.security.guard import SecurityError, SecurityGuard
from rag.security.policy import PermissionPolicy


class TestSecurityGuard(unittest.TestCase):
    def test_safe_mode_blocks_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            policy = PermissionPolicy(access_mode="safe", workspace_root=str(root), allowed_roots=[str(root)])
            guard = SecurityGuard(policy)

            outside = (root.parent / "outside.txt").resolve()
            with self.assertRaises(SecurityError):
                guard.check_path_allowed(str(outside), action="fs_read_file")

    def test_denylist_blocks_env_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            policy = PermissionPolicy(access_mode="safe", workspace_root=str(root), allowed_roots=[str(root)])
            guard = SecurityGuard(policy)

            denied = (root / ".env").resolve()
            with self.assertRaises(SecurityError):
                guard.check_path_allowed(str(denied), action="fs_read_file")

    def test_require_confirmation(self):
        policy = PermissionPolicy()
        guard = SecurityGuard(policy)

        try:
            guard.require_confirmation("fs_delete_path", user_confirmation=None)
            self.fail("Expected SecurityError")
        except SecurityError as exc:
            self.assertTrue(exc.requires_confirmation)

    def test_high_risk_batch_requires_confirmation(self):
        policy = PermissionPolicy(max_files_per_run=10, max_upload_mb_per_run=1)
        guard = SecurityGuard(policy)

        try:
            guard.check_batch("send_email", file_count=11, total_bytes=0)
            self.fail("Expected SecurityError")
        except SecurityError as exc:
            self.assertTrue(exc.requires_confirmation)
            self.assertIn("High-risk batch", str(exc))
