"""Tests for PAC Work-State Diff functionality."""

import tempfile
import unittest
from pathlib import Path

from pac.checkpoint.models import Checkpoint, ProjectInfo, TaskInfo, Decision, Evidence, SourceAgent
from pac.checkpoint.storage import CheckpointStorage
from pac.checkpoint.errors import CheckpointNotFoundError, CheckpointValidationError
from pac.diff import diff_checkpoints, diff_checkpoint_files


class TestDiff(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.cp_a = Checkpoint(
            version="1.0",
            project=ProjectInfo(name="test-project", commit="1111111111111111111111111111111111111111", dirty=False),
            task=TaskInfo(objective="Implement Sector S4", status="in_progress"),
            completed=["Defined models"],
            remaining=["Implement engine", "Add tests"],
            changed_files=["src/model.py"],
            next_action="Implement engine",
            evidence=[
                Evidence(claim="Models exist", source="pytest", status="VERIFIED", detail="Pass"),
                Evidence(claim="Engine status", source="agent", status="AGENT_REPORTED"),
            ],
            source_agent=SourceAgent(name="AgentA"),
            created_at="2026-09-24T20:00:00Z",
            decisions=[Decision(decision="Use dataclasses", reason="Standard python library")],
            constraints=["Do not break S3"],
        )

        self.cp_b = Checkpoint(
            version="1.0",
            project=ProjectInfo(name="test-project", commit="2222222222222222222222222222222222222222", dirty=True),
            task=TaskInfo(objective="Implement Sector S5", status="completed"),
            completed=["Defined models", "Implemented engine"],
            remaining=["Add tests"],
            changed_files=["src/model.py", "src/engine.py"],
            next_action="Add tests",
            evidence=[
                Evidence(claim="Models exist", source="pytest", status="VERIFIED", detail="Pass"),
                Evidence(claim="Engine status", source="pytest", status="VERIFIED", detail="Pass"),
            ],
            source_agent=SourceAgent(name="AgentB"),
            created_at="2026-09-24T22:00:00Z",
            decisions=[Decision(decision="Use dataclasses", reason="Standard python library"), Decision(decision="Add diff module", reason="Required by S5")],
            constraints=["Do not break S3", "Keep diff local-first"],
        )

        self.path_a = self.root / "cp_a.json"
        self.path_b = self.root / "cp_b.json"
        CheckpointStorage(self.path_a).save(self.cp_a)
        CheckpointStorage(self.path_b).save(self.cp_b)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_11_identical_checkpoints(self):
        output = diff_checkpoints(self.cp_a, self.cp_a)
        self.assertIn("No work-state changes detected", output)

    def test_12_changed_objective(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("OBJECTIVE", output)
        self.assertIn("- FROM: Implement Sector S4", output)
        self.assertIn("+ TO:   Implement Sector S5", output)

    def test_13_changed_status(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("STATUS", output)
        self.assertIn("- FROM: in_progress", output)
        self.assertIn("+ TO:   completed", output)

    def test_14_completed_item_added(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("COMPLETED", output)
        self.assertIn("+ Implemented engine", output)

    def test_15_completed_item_removed(self):
        cp_c = Checkpoint(
            version="1.0",
            project=self.cp_a.project,
            task=self.cp_a.task,
            completed=[],
            remaining=self.cp_a.remaining,
            changed_files=self.cp_a.changed_files,
            next_action=self.cp_a.next_action,
            evidence=self.cp_a.evidence,
            source_agent=self.cp_a.source_agent,
            created_at=self.cp_a.created_at,
        )
        output = diff_checkpoints(self.cp_a, cp_c)
        self.assertIn("COMPLETED", output)
        self.assertIn("- Defined models", output)

    def test_16_remaining_item_added_removed(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("REMAINING", output)
        self.assertIn("- Implement engine", output)

    def test_17_decisions_changed(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("DECISIONS", output)
        self.assertIn("+ Add diff module (Reason: Required by S5)", output)

    def test_18_constraints_changed(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("CONSTRAINTS", output)
        self.assertIn("+ Keep diff local-first", output)

    def test_19_changed_files_changed(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("CHANGED FILES", output)
        self.assertIn("+ src/engine.py", output)

    def test_20_next_action_changed(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("NEXT ACTION", output)
        self.assertIn("FROM: Implement engine", output)
        self.assertIn("TO:   Add tests", output)

    def test_21_evidence_changed(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("EVIDENCE", output)
        self.assertIn("~ [AGENT_REPORTED -> VERIFIED] Engine status", output)

    def test_22_git_state_changed(self):
        output = diff_checkpoints(self.cp_a, self.cp_b)
        self.assertIn("GIT STATE", output)
        self.assertIn("FROM: Commit: 11111111, Dirty: False", output)
        self.assertIn("TO:   Commit: 22222222, Dirty: True", output)

    def test_23_invalid_checkpoint_a(self):
        missing_a = self.root / "missing_a.json"
        with self.assertRaises(CheckpointNotFoundError):
            diff_checkpoint_files(missing_a, self.path_b)

    def test_24_invalid_checkpoint_b(self):
        missing_b = self.root / "missing_b.json"
        with self.assertRaises(CheckpointNotFoundError):
            diff_checkpoint_files(self.path_a, missing_b)

    def test_25_deterministic_output(self):
        out1 = diff_checkpoint_files(self.path_a, self.path_b)
        out2 = diff_checkpoint_files(self.path_a, self.path_b)
        self.assertEqual(out1, out2)


if __name__ == "__main__":
    unittest.main()
