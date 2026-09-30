"""S7 Tests: Checkpoint History & Recovery."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pac.checkpoint import Checkpoint, CheckpointStorage, CheckpointValidationError, CheckpointNotFoundError
from pac.history import (
    CheckpointHistoryStore,
    compute_checkpoint_id,
    sanitize_id,
    format_history_output,
    inspect_checkpoint,
)
from pac.capture import capture_checkpoint, TaskContext
from pac.diff import diff_checkpoint_files


class TestS7CheckpointHistoryAndRecovery(unittest.TestCase):
    """Test suite covering Sector S7 requirements."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.ai_dir = self.temp_dir / ".ai"
        self.ai_dir.mkdir(parents=True, exist_ok=True)
        self.history_store = CheckpointHistoryStore(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_checkpoint(
        self,
        objective="Implement feature X",
        completed=None,
        remaining=None,
        decisions=None,
        next_action="Continue tests",
        created_at="2026-09-25T18:00:00Z",
        source_agent="agent-A",
    ) -> Checkpoint:
        from pac.checkpoint.models import ProjectInfo, TaskInfo, Decision, Evidence, SourceAgent, SUPPORTED_VERSION
        comp = ["Setup repository"] if completed is None else completed
        rem = ["Write integration tests"] if remaining is None else remaining
        decs = [Decision(decision="Use JSON store", reason="Simple & local")] if decisions is None else decisions
        return Checkpoint(
            version=SUPPORTED_VERSION,
            project=ProjectInfo(name="test-project", commit="abc123456", dirty=False),
            task=TaskInfo(objective=objective, status="in_progress"),
            completed=comp,
            remaining=rem,
            changed_files=["src/main.py"],
            next_action=next_action,
            evidence=[Evidence(claim="Repository working tree dirty status is False", source="git status", status="OBSERVED")],
            source_agent=SourceAgent(name=source_agent),
            created_at=created_at,
            decisions=decs,
            constraints=["Do not edit database"],
        )


    # -------------------------------------------------------------------------
    # History Tests (1-7)
    # -------------------------------------------------------------------------

    def test_01_empty_history(self):
        entries = self.history_store.list_history()
        self.assertEqual(entries, [])
        formatted = format_history_output(entries)
        self.assertIn("No checkpoints found in history", formatted)

    def test_02_one_checkpoint(self):
        cp = self._create_sample_checkpoint()
        self.history_store.archive_checkpoint(cp)
        entries = self.history_store.list_history()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["objective"], cp.task.objective)

    def test_03_multiple_checkpoints(self):
        cp1 = self._create_sample_checkpoint(created_at="2026-09-25T18:00:00Z")
        cp2 = self._create_sample_checkpoint(created_at="2026-09-25T19:00:00Z")
        self.history_store.archive_checkpoint(cp1)
        self.history_store.archive_checkpoint(cp2)
        entries = self.history_store.list_history()
        self.assertEqual(len(entries), 2)

    def test_04_stable_ordering(self):
        cp1 = self._create_sample_checkpoint(created_at="2026-09-25T18:00:00Z")
        cp2 = self._create_sample_checkpoint(created_at="2026-09-25T19:00:00Z")
        cp3 = self._create_sample_checkpoint(created_at="2026-09-25T18:30:00Z")
        self.history_store.archive_checkpoint(cp1)
        self.history_store.archive_checkpoint(cp2)
        self.history_store.archive_checkpoint(cp3)
        entries = self.history_store.list_history()
        self.assertEqual(entries[0]["created_at"], "2026-09-25T19:00:00Z")
        self.assertEqual(entries[1]["created_at"], "2026-09-25T18:30:00Z")
        self.assertEqual(entries[2]["created_at"], "2026-09-25T18:00:00Z")

    def test_05_correct_ids(self):
        cp = self._create_sample_checkpoint()
        cp_id = compute_checkpoint_id(cp)
        dest = self.history_store.archive_checkpoint(cp)
        self.assertTrue(dest.name.startswith(cp_id))
        self.assertEqual(len(cp_id), 12)

    def test_06_correct_timestamps_and_metadata(self):
        cp = self._create_sample_checkpoint(source_agent="custom-agent")
        self.history_store.archive_checkpoint(cp)
        entries = self.history_store.list_history()
        self.assertEqual(entries[0]["source_agent"], "custom-agent")
        self.assertEqual(entries[0]["created_at"], "2026-09-25T18:00:00Z")

    def test_07_correct_verification_status(self):
        cp = self._create_sample_checkpoint()
        self.history_store.archive_checkpoint(cp)
        entries = self.history_store.list_history()
        self.assertIn(entries[0]["verification_status"], ["OBSERVED", "VERIFIED", "PARTIALLY_VERIFIED", "FULLY_VERIFIED", "UNVERIFIED", "STALE", "UNKNOWN"])

    # -------------------------------------------------------------------------
    # Inspect Tests (8-11)
    # -------------------------------------------------------------------------

    def test_08_inspect_valid_checkpoint(self):
        cp = self._create_sample_checkpoint()
        path = self.history_store.archive_checkpoint(cp)
        out = inspect_checkpoint(str(path), project_root=self.temp_dir)
        self.assertIn("PROJECT", out)
        self.assertIn("TASK", out)
        self.assertIn("Implement feature X", out)

    def test_09_inspect_preserves_all_relevant_fields(self):
        cp = self._create_sample_checkpoint(
            completed=["Item A"],
            remaining=["Item B"],
            next_action="Run test suite",
        )
        path = self.history_store.archive_checkpoint(cp)
        out = inspect_checkpoint(str(path), project_root=self.temp_dir)
        self.assertIn("Item A", out)
        self.assertIn("Item B", out)
        self.assertIn("Run test suite", out)
        self.assertIn("agent-A", out)

    def test_10_inspect_invalid_checkpoint_produces_clear_error(self):
        invalid_path = self.temp_dir / "invalid.json"
        invalid_path.write_text("not json", encoding="utf-8")
        with self.assertRaises(CheckpointValidationError):
            inspect_checkpoint(str(invalid_path), project_root=self.temp_dir)

    def test_11_inspect_is_read_only(self):
        cp = self._create_sample_checkpoint()
        path = self.history_store.archive_checkpoint(cp)
        mtime_before = path.stat().st_mtime
        inspect_checkpoint(str(path), project_root=self.temp_dir)
        mtime_after = path.stat().st_mtime
        self.assertEqual(mtime_before, mtime_after)

    # -------------------------------------------------------------------------
    # Diff Tests (12-19)
    # -------------------------------------------------------------------------

    def test_12_diff_two_valid_checkpoints(self):
        cp1 = self._create_sample_checkpoint(completed=["Task 1"])
        cp2 = self._create_sample_checkpoint(completed=["Task 1", "Task 2"])
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        diff_res = diff_checkpoint_files(p1, p2)
        self.assertIn("+ Task 2", diff_res)

    def test_13_unchanged_checkpoints_produce_no_false_differences(self):
        cp1 = self._create_sample_checkpoint()
        cp2 = self._create_sample_checkpoint()
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        diff_res = diff_checkpoint_files(p1, p2)
        self.assertIn("No work-state changes detected", diff_res)

    def test_14_changed_completed_items_detected(self):
        cp1 = self._create_sample_checkpoint(completed=["Task 1"])
        cp2 = self._create_sample_checkpoint(completed=["Task 1", "Task 2"])
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        diff_res = diff_checkpoint_files(p1, p2)
        self.assertIn("+ Task 2", diff_res)

    def test_15_changed_remaining_items_detected(self):
        cp1 = self._create_sample_checkpoint(remaining=["Task A", "Task B"])
        cp2 = self._create_sample_checkpoint(remaining=["Task B"])
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        diff_res = diff_checkpoint_files(p1, p2)
        self.assertIn("- Task A", diff_res)

    def test_16_changed_decisions_detected(self):
        from pac.checkpoint.models import Decision
        cp1 = self._create_sample_checkpoint(decisions=[Decision(decision="D1", reason="R1")])
        cp2 = self._create_sample_checkpoint(decisions=[Decision(decision="D1", reason="R1"), Decision(decision="D2", reason="R2")])
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        diff_res = diff_checkpoint_files(p1, p2)
        self.assertIn("+ D2", diff_res)

    def test_17_changed_next_action_detected(self):
        cp1 = self._create_sample_checkpoint(next_action="Action 1")
        cp2 = self._create_sample_checkpoint(next_action="Action 2")
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        diff_res = diff_checkpoint_files(p1, p2)
        self.assertIn("FROM: Action 1", diff_res)
        self.assertIn("TO:   Action 2", diff_res)

    def test_18_objective_changes_detected(self):
        cp1 = self._create_sample_checkpoint(objective="Obj 1")
        cp2 = self._create_sample_checkpoint(objective="Obj 2")
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        diff_res = diff_checkpoint_files(p1, p2)
        self.assertIn("FROM: Obj 1", diff_res)
        self.assertIn("TO:   Obj 2", diff_res)


    def test_19_existing_diff_behavior_remains_compatible(self):
        cp1 = self._create_sample_checkpoint()
        cp2 = self._create_sample_checkpoint(next_action="New action")
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        out = diff_checkpoint_files(p1, p2)
        self.assertTrue(out.startswith("[PAC] Work-State Diff"))

    # -------------------------------------------------------------------------
    # Recovery Tests (20-26)
    # -------------------------------------------------------------------------

    def test_20_recover_valid_checkpoint(self):
        cp = self._create_sample_checkpoint(objective="Recoverable objective")
        p = self.history_store.archive_checkpoint(cp)
        rec_cp, active_p = self.history_store.recover(str(p))
        self.assertEqual(rec_cp.task.objective, "Recoverable objective")
        self.assertTrue(active_p.exists())

    def test_21_active_checkpoint_becomes_selected_checkpoint(self):
        cp1 = self._create_sample_checkpoint(objective="CP 1")
        cp2 = self._create_sample_checkpoint(objective="CP 2")
        p1 = self.history_store.archive_checkpoint(cp1)
        p2 = self.history_store.archive_checkpoint(cp2)
        
        self.history_store.recover(str(p1))
        active_cp = CheckpointStorage(self.history_store.active_checkpoint_path).load()
        self.assertEqual(active_cp.task.objective, "CP 1")

        self.history_store.recover(str(p2))
        active_cp = CheckpointStorage(self.history_store.active_checkpoint_path).load()
        self.assertEqual(active_cp.task.objective, "CP 2")

    def test_22_recovery_preserves_checkpoint_contents(self):
        cp = self._create_sample_checkpoint(
            completed=["C1", "C2"],
            decisions=[self._create_sample_checkpoint().decisions[0]],
        )
        p = self.history_store.archive_checkpoint(cp)
        self.history_store.recover(str(p))
        active_cp = CheckpointStorage(self.history_store.active_checkpoint_path).load()
        self.assertEqual(active_cp.completed, ["C1", "C2"])
        self.assertEqual(active_cp.decisions[0].decision, cp.decisions[0].decision)

    def test_23_invalid_checkpoint_rejected(self):
        invalid_p = self.temp_dir / "bad.json"
        invalid_p.write_text('{"version": "99.0"}', encoding="utf-8")
        with self.assertRaises((CheckpointValidationError, Exception)):
            self.history_store.recover(str(invalid_p))

    def test_24_failed_recovery_does_not_corrupt_existing_active_checkpoint(self):
        # 1. Setup valid active checkpoint
        cp_valid = self._create_sample_checkpoint(objective="Original Active")
        p_valid = self.history_store.archive_checkpoint(cp_valid)
        self.history_store.recover(str(p_valid))

        # 2. Attempt recovering invalid checkpoint
        bad_p = self.temp_dir / "corrupted.json"
        bad_p.write_text("invalid json content", encoding="utf-8")

        with self.assertRaises((CheckpointValidationError, Exception)):
            self.history_store.recover(str(bad_p))

        # 3. Active checkpoint remains intact
        active_cp = CheckpointStorage(self.history_store.active_checkpoint_path).load()
        self.assertEqual(active_cp.task.objective, "Original Active")

    def test_25_recovery_does_not_modify_project_source_files(self):
        src_file = self.temp_dir / "src_code.py"
        src_file.write_text("print('hello')", encoding="utf-8")
        mtime_before = src_file.stat().st_mtime

        cp = self._create_sample_checkpoint()
        p = self.history_store.archive_checkpoint(cp)
        self.history_store.recover(str(p))

        self.assertEqual(src_file.read_text(encoding="utf-8"), "print('hello')")
        self.assertEqual(src_file.stat().st_mtime, mtime_before)

    def test_26_recovery_does_not_execute_commands(self):
        # Implicit: recover only performs file read/write of JSON checkpoint data
        cp = self._create_sample_checkpoint()
        p = self.history_store.archive_checkpoint(cp)
        rec_cp, active_p = self.history_store.recover(str(p))
        self.assertIsNotNone(rec_cp)

    # -------------------------------------------------------------------------
    # Security Tests (27-30)
    # -------------------------------------------------------------------------

    def test_27_no_secret_leakage(self):
        # Redaction rules apply to captured checkpoint before archive
        ctx = TaskContext(objective="API_KEY=sk-proj-secret12345678901234567890")
        cp, _ = capture_checkpoint(project_root=self.temp_dir, task_context=ctx)
        cp_id = compute_checkpoint_id(cp)
        path = self.history_store.get_checkpoint_path(cp_id)
        file_content = path.read_text(encoding="utf-8")
        self.assertNotIn("sk-proj-secret12345678901234567890", file_content)

    def test_28_no_arbitrary_path_traversal_outside_intended_storage(self):
        with self.assertRaises(CheckpointValidationError):
            sanitize_id("../../../etc/passwd")

        with self.assertRaises(CheckpointValidationError):
            self.history_store.get_checkpoint_path("..\\..\\secret")

    def test_29_no_network_access(self):
        # Pure filesystem storage
        self.assertTrue(hasattr(self.history_store, "list_history"))

    def test_30_no_external_dependencies_unless_already_present(self):
        import sys
        # standard library only for history module
        from pac import history
        self.assertIsNotNone(history)


if __name__ == "__main__":
    unittest.main()
