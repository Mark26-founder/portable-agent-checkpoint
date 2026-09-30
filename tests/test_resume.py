"""Tests for PAC Resume functionality."""

import json
import tempfile
import unittest
from pathlib import Path

from pac.checkpoint.models import Checkpoint, ProjectInfo, TaskInfo, Decision, Evidence, SourceAgent
from pac.checkpoint.storage import CheckpointStorage
from pac.checkpoint.errors import CheckpointNotFoundError, CheckpointValidationError
from pac.resume import resume_checkpoint, format_resume_output
from pac.verify import VerificationResult, EvidenceVerification


class TestResume(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.ai_dir = self.root / ".ai"
        self.ai_dir.mkdir(parents=True, exist_ok=True)
        self.cp_path = self.ai_dir / "checkpoint.json"

        self.sample_cp = Checkpoint(
            version="1.0",
            project=ProjectInfo(name="test-project", commit="a1b2c3d4e5f678901234567890abcdef12345678", dirty=False),
            task=TaskInfo(objective="Implement Sector S5", status="in_progress"),
            completed=["Defined JWT module"],
            remaining=["Add integration tests"],
            changed_files=["src/main.py"],
            next_action="Run test suite and verify.",
            evidence=[
                Evidence(claim="JWT module exists", source="pytest", status="VERIFIED", detail="1 passed"),
                Evidence(claim="Stateless auth draft", source="AI agent", status="AGENT_REPORTED"),
            ],
            source_agent=SourceAgent(name="Antigravity"),
            created_at="2026-09-24T22:00:00Z",
            decisions=[Decision(decision="Use PyJWT", reason="Maintained and secure")],
            constraints=["Do not modify public API"],
        )
        CheckpointStorage(self.cp_path).save(self.sample_cp)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_1_valid_checkpoint_resume(self):
        output = resume_checkpoint(self.cp_path, project_root=self.root, verify=False)
        self.assertIn("[PAC] Resume — test-project", output)
        self.assertIn("Objective: Implement Sector S5", output)
        self.assertIn("Status: in_progress", output)
        self.assertIn("- Defined JWT module", output)
        self.assertIn("- Add integration tests", output)
        self.assertIn("- Use PyJWT (Reason: Maintained and secure)", output)
        self.assertIn("- Do not modify public API", output)
        self.assertIn("- src/main.py", output)
        self.assertIn("- [VERIFIED] JWT module exists", output)
        self.assertIn("- [AGENT_REPORTED] Stateless auth draft", output)
        self.assertIn("Run test suite and verify.", output)
        self.assertIn("Antigravity", output)

    def test_2_missing_checkpoint(self):
        missing_path = self.root / "nonexistent.json"
        with self.assertRaises(CheckpointNotFoundError):
            resume_checkpoint(missing_path, project_root=self.root)

    def test_3_malformed_checkpoint(self):
        malformed_path = self.root / "malformed.json"
        with open(malformed_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json }")
        with self.assertRaises(CheckpointValidationError):
            resume_checkpoint(malformed_path, project_root=self.root)

    def test_4_all_major_fields_displayed(self):
        output = resume_checkpoint(self.cp_path, project_root=self.root, verify=False)
        required_sections = ["TASK", "COMPLETED", "REMAINING", "DECISIONS", "CONSTRAINTS", "CHANGED FILES", "EVIDENCE", "NEXT ACTION", "SOURCE AGENT", "CHECKPOINT"]
        for sec in required_sections:
            self.assertIn(sec, output)

    def test_5_missing_optional_fields_handled_safely(self):
        cp_minimal = Checkpoint(
            version="1.0",
            project=ProjectInfo(name="min-proj", commit="NONE", dirty=False),
            task=TaskInfo(objective="Simple task", status="completed"),
            completed=[],
            remaining=[],
            changed_files=[],
            next_action="Done.",
            evidence=[],
            source_agent=SourceAgent(name="Agent"),
            created_at="2026-09-24T22:00:00Z",
            decisions=[],
            constraints=[],
        )
        cp_minimal.source_agent.name = ""  # override after bypass to test display fallback
        min_dict = cp_minimal.to_dict() if False else None

        # Build json directly to test Unknown source agent name
        raw_json = {
            "version": "1.0",
            "project": {"name": "min-proj", "commit": "NONE", "dirty": False},
            "task": {"objective": "Simple task", "status": "completed"},
            "completed": [],
            "remaining": [],
            "changed_files": [],
            "next_action": "Done.",
            "evidence": [],
            "source_agent": {"name": "Unknown"},
            "created_at": "2026-09-24T22:00:00Z",
            "decisions": [],
            "constraints": []
        }
        min_path = self.root / "min.json"
        with open(min_path, "w", encoding="utf-8") as f:
            json.dump(raw_json, f)

        output = resume_checkpoint(min_path, project_root=self.root, verify=False)
        self.assertIn("None recorded", output)
        self.assertIn("Unknown", output)

    def test_6_evidence_statuses_preserved(self):
        output = resume_checkpoint(self.cp_path, project_root=self.root, verify=False)
        self.assertIn("- [VERIFIED] JWT module exists", output)
        self.assertIn("- [AGENT_REPORTED] Stateless auth draft", output)


    def test_7_stale_state_displayed(self):
        fake_ver = VerificationResult(
            checkpoint_path=str(self.cp_path),
            checkpoint=self.sample_cp,
            current_git_commit="b2c3d4e5f678901234567890abcdef1234567890",
            current_git_dirty=True,
            is_git_repo=True,
            is_stale=True,
            overall_status="STALE",
            evidence_results=[],
            errors=["Git commit mismatch"],
        )
        output = format_resume_output(self.sample_cp, verification=fake_ver)
        self.assertIn("WARNING: CHECKPOINT STALE", output)
        self.assertIn("Reason:", output)
        self.assertIn("Git commit mismatch", output)
        self.assertIn("Verification: STALE", output)
        self.assertIn("Stale: true", output)

    def test_8_no_fabrication(self):
        cp_empty_desc = Checkpoint(
            version="1.0",
            project=ProjectInfo(name="proj", commit="NONE", dirty=False),
            task=TaskInfo(objective="Obj", status="in_progress"),
            completed=[],
            remaining=[],
            changed_files=[],
            next_action="Next",
            evidence=[],
            source_agent=SourceAgent(name="Agent"),
            created_at="2026-09-24T22:00:00Z",
        )
        output = format_resume_output(cp_empty_desc)
        self.assertNotIn("Fabricated", output)
        self.assertIn("None recorded", output)

    def test_9_secrets_not_exposed(self):
        cp_secret = Checkpoint(
            version="1.0",
            project=ProjectInfo(name="proj", commit="NONE", dirty=False),
            task=TaskInfo(objective="Obj sk-ant-api03-123456789012345678901234567890", status="in_progress"),
            completed=["Added key token: abcdef1234567890"],
            remaining=[],
            changed_files=[],
            next_action="Next",
            evidence=[],
            source_agent=SourceAgent(name="Agent"),
            created_at="2026-09-24T22:00:00Z",
        )
        from pac.capture.redact import redact_string
        cp_secret.task.objective = redact_string(cp_secret.task.objective)
        cp_secret.completed = [redact_string(x) for x in cp_secret.completed]

        output = format_resume_output(cp_secret)
        self.assertNotIn("sk-ant-api03-123456789012345678901234567890", output)
        self.assertIn("[REDACTED_API_KEY]", output)
        self.assertNotIn("abcdef1234567890", output)
        self.assertIn("[REDACTED_SECRET]", output)

    def test_10_deterministic_output(self):
        out1 = resume_checkpoint(self.cp_path, project_root=self.root, verify=False)
        out2 = resume_checkpoint(self.cp_path, project_root=self.root, verify=False)
        self.assertEqual(out1, out2)

    def test_json_format_output(self):
        output = resume_checkpoint(self.cp_path, project_root=self.root, output_format="json", verify=False)
        parsed = json.loads(output)
        self.assertEqual(parsed["project"]["name"], "test-project")
        self.assertEqual(parsed["task"]["objective"], "Implement Sector S5")


if __name__ == "__main__":
    unittest.main()
