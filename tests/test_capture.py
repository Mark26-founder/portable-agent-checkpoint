"""Unit tests for S3 Capture Engine (Standard Library unittest)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ is on python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pac.capture import (
    inspect_git_repository,
    capture_checkpoint,
    TaskContext,
    redact_string,
)
from pac.checkpoint import CheckpointStorage, Checkpoint
from pac.checkpoint.errors import CheckpointValidationError


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


class TestCaptureEngine(unittest.TestCase):

    # 1 & 2. Capture inside a Git repository & correct commit collection
    def test_capture_git_repo_commit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "README.md", "# Test Repo")

            git_state = inspect_git_repository(repo)
            self.assertTrue(git_state.is_git_repo)
            self.assertNotEqual(git_state.commit, "NONE")
            self.assertEqual(len(git_state.commit), 40)
            self.assertFalse(git_state.dirty)

    # 3. Correct dirty/clean state
    def test_git_dirty_state(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "foo.py", "print(1)")

            git_state_clean = inspect_git_repository(repo)
            self.assertFalse(git_state_clean.dirty)

            # Modify file
            (repo / "foo.py").write_text("print(2)", encoding="utf-8")
            git_state_dirty = inspect_git_repository(repo)
            self.assertTrue(git_state_dirty.dirty)

    # 4 & 5. Changed-file collection & relative file paths
    def test_changed_files_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "src/main.py", "code")

            # Add new file and modify existing
            (repo / "src/main.py").write_text("modified code", encoding="utf-8")
            test_file = repo / "tests" / "test_main.py"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("test code", encoding="utf-8")

            git_state = inspect_git_repository(repo)
            self.assertIn("src/main.py", git_state.changed_files)
            self.assertIn("tests/test_main.py", git_state.changed_files)
            # Paths must be relative and posix forward-slashed
            for path_str in git_state.changed_files:
                self.assertFalse(os.path.isabs(path_str))
                self.assertNotIn("\\", path_str)

    # 6. Capture with task context
    def test_capture_with_task_context(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.txt", "init")

            ctx = TaskContext(
                objective="Add auth module",
                status="in_progress",
                completed=["Created JWT module"],
                remaining=["Add middleware"],
                source_agent_name="claude-3-7-sonnet",
            )

            cp, out_path = capture_checkpoint(repo, task_context=ctx)
            self.assertEqual(cp.task.objective, "Add auth module")
            self.assertEqual(cp.completed, ["Created JWT module"])
            self.assertEqual(cp.remaining, ["Add middleware"])
            self.assertEqual(cp.source_agent.name, "claude-3-7-sonnet")

    # 7. Capture without task context
    def test_capture_without_task_context(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.txt", "init")

            cp, out_path = capture_checkpoint(repo, task_context=None)
            self.assertEqual(cp.task.objective, "Unspecified development task")
            self.assertEqual(cp.source_agent.name, "unknown")

    # 8. Agent-provided information remains distinguishable from system evidence
    def test_evidence_distinction(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.txt", "init")

            ctx = TaskContext(objective="Test Objective")
            cp, _ = capture_checkpoint(repo, task_context=ctx)

            observed_statuses = [e.status for e in cp.evidence if e.source.startswith("git")]
            agent_statuses = [e.status for e in cp.evidence if e.source.startswith("agent")]

            self.assertTrue(all(s == "OBSERVED" for s in observed_statuses))
            self.assertTrue(all(s == "AGENT_REPORTED" for s in agent_statuses))

    # 9. Missing Git repository is handled
    def test_missing_git_repository(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_repo = Path(tmp_dir)
            git_state = inspect_git_repository(non_repo)

            self.assertFalse(git_state.is_git_repo)
            self.assertEqual(git_state.commit, "NONE")
            self.assertFalse(git_state.dirty)

            cp, _ = capture_checkpoint(non_repo)
            self.assertEqual(cp.project.commit, "NONE")
            self.assertFalse(cp.project.dirty)

    # 10. Invalid task-context file is handled
    def test_invalid_task_context_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_ctx_file = Path(tmp_dir) / "invalid.json"
            bad_ctx_file.write_text("{ broken json ...", encoding="utf-8")

            with self.assertRaises(CheckpointValidationError):
                TaskContext.load_from_file(bad_ctx_file)

    # 11 & 12. Capture creates .ai/checkpoint.json & generated checkpoint passes S2 validation
    def test_capture_creates_and_validates_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "file.py", "val")

            cp, out_path = capture_checkpoint(repo)

            self.assertTrue(out_path.exists())
            self.assertEqual(out_path, repo / ".ai" / "checkpoint.json")

            # Load via S2 CheckpointStorage to verify S2 compliance
            storage = CheckpointStorage(out_path)
            loaded_cp = storage.load()
            loaded_cp.validate()  # Passes validation

    # 13. Secrets are not intentionally collected
    def test_secrets_redacted(self):
        secret_str = "Use API key api_key = 'sk-12345678901234567890' for authentication"
        redacted = redact_string(secret_str)
        self.assertNotIn("sk-12345678901234567890", redacted)

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "a.py", "a")

            ctx = TaskContext(
                objective="sk-ant-123456789012345678901234",
                completed=["api_key = 'super_secret_password_123'"],
            )

            cp, _ = capture_checkpoint(repo, task_context=ctx)
            self.assertNotIn("sk-ant-123456789012345678901234", cp.task.objective)
            self.assertNotIn("super_secret_password_123", cp.completed[0])

    # 14. Capture does not modify repository files
    def test_capture_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "source.py", "# Original Code")

            before_stat = (repo / "source.py").stat()

            capture_checkpoint(repo)

            after_stat = (repo / "source.py").stat()
            self.assertEqual(before_stat.st_mtime, after_stat.st_mtime)
            self.assertEqual((repo / "source.py").read_text(encoding="utf-8"), "# Original Code")


if __name__ == "__main__":
    unittest.main()
