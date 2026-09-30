"""Unit tests for S4 Verification Engine (Standard Library unittest)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ is on python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pac.capture import capture_checkpoint, TaskContext, inspect_git_repository
from pac.checkpoint import CheckpointStorage, Checkpoint
from pac.checkpoint.errors import CheckpointValidationError, CheckpointNotFoundError
from pac.verify import verify_checkpoint, VerificationResult


def _init_git_repo(repo_path: Path) -> None:
    """Helper to initialize a real git repository in temp directory."""
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_path), capture_output=True, check=True)


def _commit_file(repo_path: Path, filename: str, content: str) -> None:
    """Helper to write and commit a file in temp git repo."""
    file_path = repo_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"Add {filename}"], cwd=str(repo_path), capture_output=True, check=True)


class TestVerificationEngine(unittest.TestCase):

    # 1. Valid checkpoint verification
    def test_valid_checkpoint_verification(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "src/auth.py", "# Auth code")

            cp, cp_path = capture_checkpoint(repo)
            res = verify_checkpoint(cp_path, project_root=repo)

            self.assertIsInstance(res, VerificationResult)
            self.assertFalse(res.is_stale)
            self.assertIn(res.overall_status, {"FULLY_VERIFIED", "PARTIALLY_VERIFIED"})

    # 2 & 13. Invalid / malformed checkpoint failure
    def test_invalid_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cp_file = Path(tmp_dir) / "invalid.json"
            cp_file.write_text('{"version": "1.0", "project": "not_an_object"}', encoding="utf-8")

            with self.assertRaises(CheckpointValidationError):
                verify_checkpoint(cp_file, project_root=Path(tmp_dir))

    # 3. Matching commit
    def test_matching_commit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "README.md", "# Test")

            cp, cp_path = capture_checkpoint(repo)
            res = verify_checkpoint(cp_path, project_root=repo)

            self.assertFalse(res.is_stale)
            self.assertEqual(res.current_git_commit, cp.project.commit)

    # 4. Changed commit (staleness trigger)
    def test_changed_commit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "v1.txt", "v1")

            cp, cp_path = capture_checkpoint(repo)

            # Make a new commit
            _commit_file(repo, "v2.txt", "v2")

            res = verify_checkpoint(cp_path, project_root=repo)
            self.assertTrue(res.is_stale)
            self.assertEqual(res.overall_status, "STALE")

    # 5. Matching clean/dirty state
    def test_matching_clean_dirty_state(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "main.py", "print(1)")

            # Create dirty state before capture
            (repo / "main.py").write_text("print(2)", encoding="utf-8")
            cp, cp_path = capture_checkpoint(repo)

            # Verification while working tree remains dirty in same state
            res = verify_checkpoint(cp_path, project_root=repo)
            self.assertFalse(res.is_stale)
            self.assertTrue(res.current_git_dirty)

    # 6 & 8. Changed-file mismatch / referenced missing file
    def test_changed_file_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "file1.py", "f1")

            # Create uncommitted file
            (repo / "file2.py").write_text("f2", encoding="utf-8")
            cp, cp_path = capture_checkpoint(repo)
            self.assertIn("file2.py", cp.changed_files)

            # Delete the file before verification
            (repo / "file2.py").unlink()

            res = verify_checkpoint(cp_path, project_root=repo)
            self.assertTrue(res.is_stale)
            self.assertEqual(res.overall_status, "STALE")

    # 7. Referenced existing file (OBSERVED conversion)
    def test_referenced_existing_file_verified(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "src/calculator.py", "def add(a,b): return a+b")

            ctx = TaskContext(
                objective="Add calculator module",
                completed=["Created calculator service in src/calculator.py"],
            )
            cp, cp_path = capture_checkpoint(repo, task_context=ctx)

            res = verify_checkpoint(cp_path, project_root=repo)
            observed_claims = [e for e in res.evidence_results if e.status == "OBSERVED"]
            self.assertTrue(len(observed_claims) > 0)
            self.assertTrue(any("src/calculator.py" in e.claim or "src/calculator.py" in (e.verification_basis or "") for e in observed_claims))

    # 9. AGENT_REPORTED evidence remains distinct when unverifiable
    def test_agent_reported_remains_distinct(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "README.md", "# Test")

            ctx = TaskContext(
                objective="Theoretical design task",
                completed=["Discussed architectural approach with user"],
            )
            cp, cp_path = capture_checkpoint(repo, task_context=ctx)

            res = verify_checkpoint(cp_path, project_root=repo)
            agent_reported = [e for e in res.evidence_results if e.status == "AGENT_REPORTED"]
            self.assertTrue(len(agent_reported) > 0)

    # 10. OBSERVED evidence has concrete basis
    def test_verified_evidence_has_concrete_basis(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "src/app.py", "app = True")

            ctx = TaskContext(
                completed=["Implemented application entrypoint in src/app.py"]
            )
            cp, cp_path = capture_checkpoint(repo, task_context=ctx)

            res = verify_checkpoint(cp_path, project_root=repo)
            observed_items = [e for e in res.evidence_results if e.status == "OBSERVED"]
            for v in observed_items:
                self.assertIsNotNone(v.verification_basis)
                self.assertTrue(len(v.verification_basis) > 0)


    # 11. Stale checkpoint detection
    def test_stale_checkpoint_detection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "base.txt", "base")

            cp, cp_path = capture_checkpoint(repo)

            # Modify repository state
            (repo / "base.txt").write_text("modified base", encoding="utf-8")

            res = verify_checkpoint(cp_path, project_root=repo)
            self.assertTrue(res.is_stale)

    # 12. Missing Git repository
    def test_missing_git_repository(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_repo = Path(tmp_dir)
            cp, cp_path = capture_checkpoint(non_repo)

            res = verify_checkpoint(cp_path, project_root=non_repo)
            self.assertFalse(res.is_git_repo)
            self.assertFalse(res.is_stale)

    # 14. Security/redaction preservation
    def test_security_redaction_preservation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.txt", "init")

            ctx = TaskContext(
                objective="api_key = 'sk-123456789012345678901234'",
                completed=["Fixed auth in src/init.txt"],
            )
            cp, cp_path = capture_checkpoint(repo, task_context=ctx)

            res = verify_checkpoint(cp_path, project_root=repo)
            for ev in res.evidence_results:
                self.assertNotIn("sk-123456789012345678901234", ev.claim)

    # 15. Original checkpoint is not corrupted on verification failure
    def test_original_checkpoint_not_corrupted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.txt", "init")

            cp, cp_path = capture_checkpoint(repo)
            original_content = cp_path.read_text(encoding="utf-8")

            # Cause staleness by creating file
            _commit_file(repo, "new.txt", "new")

            res = verify_checkpoint(cp_path, project_root=repo, update_checkpoint=False)
            self.assertTrue(res.is_stale)

            after_content = cp_path.read_text(encoding="utf-8")
            self.assertEqual(original_content, after_content)

    # 16 & 17. CLI success & operational error handling
    def test_cli_verification_execution(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "main.py", "main")

            cp, cp_path = capture_checkpoint(repo)

            # Test subprocess execution of CLI verify
            proc = subprocess.run(
                [sys.executable, "-m", "pac.cli", "verify", str(cp_path)],
                cwd=str(repo),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("Verification Status:", proc.stdout)

            # Test CLI error on non-existent checkpoint
            proc_err = subprocess.run(
                [sys.executable, "-m", "pac.cli", "verify", "non_existent.json"],
                cwd=str(repo),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_err.returncode, 1)
            self.assertIn("[PAC ERROR]", proc_err.stderr)


if __name__ == "__main__":
    unittest.main()
