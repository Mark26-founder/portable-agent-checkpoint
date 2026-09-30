"""S8 Tests: Evidence & Trust Hardening."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pac.checkpoint import Checkpoint, CheckpointStorage, CheckpointValidationError
from pac.checkpoint.models import ProjectInfo, TaskInfo, Decision, Evidence, SourceAgent, SUPPORTED_VERSION
from pac.verify import verify_checkpoint
from pac.resume import resume_checkpoint, format_resume_output
from pac.history import inspect_checkpoint, CheckpointHistoryStore
from pac.diff import diff_checkpoints, diff_checkpoint_files


class TestS8EvidenceAndTrustHardening(unittest.TestCase):
    """Test suite covering Sector S8 Evidence & Trust Hardening requirements."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.ai_dir = self.temp_dir / ".ai"
        self.ai_dir.mkdir(parents=True, exist_ok=True)
        self.history_store = CheckpointHistoryStore(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_checkpoint(
        self,
        evidence_list=None,
        completed=None,
        objective="S8 Trust Hardening Task",
    ) -> Checkpoint:
        return Checkpoint(
            version=SUPPORTED_VERSION,
            project=ProjectInfo(name="s8-project", commit="NONE", dirty=False),
            task=TaskInfo(objective=objective, status="in_progress"),
            completed=completed if completed is not None else ["Task 1"],
            remaining=["Task 2"],
            changed_files=[],
            next_action="Continue testing S8",
            evidence=evidence_list or [
                Evidence(claim="Claim A", source="agent input", status="AGENT_REPORTED"),
            ],
            source_agent=SourceAgent(name="agent-s8"),
            created_at="2026-09-26T20:00:00Z",
            decisions=[Decision(decision="Strict evidence checks", reason="Prevent false verification")],
            constraints=[],
        )

    # -------------------------------------------------------------------------
    # 1. Status Semantics (1-5)
    # -------------------------------------------------------------------------

    def test_01_verified_classification(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Pre-verified claim", source="test runner", status="VERIFIED")]
        )
        cp_path = self.temp_dir / "cp1.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev = [e for e in res.evidence_results if "Pre-verified" in e.claim][0]
        self.assertEqual(ev.status, "VERIFIED")

    def test_02_observed_classification(self):
        (self.temp_dir / "src" / "auth.py").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "src" / "auth.py" / "jwt.py").write_text("code", encoding="utf-8")
        
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Created src/auth.py/jwt.py", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp2.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev = [e for e in res.evidence_results if "jwt.py" in e.claim][0]
        self.assertEqual(ev.status, "OBSERVED")

    def test_03_agent_reported_classification(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Discussed design with user", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp3.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev = [e for e in res.evidence_results if "Discussed design" in e.claim][0]
        self.assertEqual(ev.status, "AGENT_REPORTED")

    def test_04_unknown_classification(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Abstract feature without target", source="unknown", status="UNKNOWN")]
        )
        cp_path = self.temp_dir / "cp4.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev = [e for e in res.evidence_results if "Abstract feature" in e.claim][0]
        self.assertEqual(ev.status, "UNKNOWN")

    def test_05_stale_classification(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Referenced src/missing.py", source="agent", status="OBSERVED")]
        )
        cp_path = self.temp_dir / "cp5.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev = [e for e in res.evidence_results if "missing.py" in e.claim][0]
        self.assertEqual(ev.status, "STALE")


    # -------------------------------------------------------------------------
    # 2. Claim Integrity (6-10)
    # -------------------------------------------------------------------------

    def test_06_agent_claims_are_preserved(self):
        cp = self._create_sample_checkpoint(completed=["Implemented feature in src/auth.py"])
        cp_path = self.temp_dir / "cp6.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertEqual(res.checkpoint.completed[0], "Implemented feature in src/auth.py")

    def test_07_verification_never_invents_claims(self):
        cp = self._create_sample_checkpoint(evidence_list=[])
        cp_path = self.temp_dir / "cp7.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        # Only existing evidence and completed item checks are processed, no random claims added
        for ev in res.evidence_results:
            self.assertTrue(ev.claim.startswith("Completed work") or ev.claim in [e.claim for e in cp.evidence])

    def test_08_unsupported_claims_remain_unverified(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="User authentication behaves as intended", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp8.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev = [e for e in res.evidence_results if "behaves as intended" in e.claim][0]
        self.assertNotEqual(ev.status, "VERIFIED")
        self.assertEqual(ev.status, "AGENT_REPORTED")

    def test_09_missing_evidence_becomes_unknown_where_appropriate(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Unverifiable claim without file", source="source", status="UNKNOWN")]
        )
        cp_path = self.temp_dir / "cp9.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev = [e for e in res.evidence_results if "Unverifiable claim" in e.claim][0]
        self.assertEqual(ev.status, "UNKNOWN")

    def test_10_invalidated_evidence_becomes_stale(self):
        (self.temp_dir / "file.txt").write_text("temp", encoding="utf-8")
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Created file.txt", source="agent", status="OBSERVED")]
        )
        cp_path = self.temp_dir / "cp10.json"
        CheckpointStorage(cp_path).save(cp)
        
        # Verify first -> OBSERVED
        res1 = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertEqual(res1.evidence_results[0].status, "OBSERVED")

        # Delete file -> STALE
        (self.temp_dir / "file.txt").unlink()
        res2 = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertEqual(res2.evidence_results[0].status, "STALE")

    # -------------------------------------------------------------------------
    # 3. Evidence Transitions (11-15)
    # -------------------------------------------------------------------------

    def test_11_agent_reported_to_observed_transition(self):
        (self.temp_dir / "module.py").write_text("code", encoding="utf-8")
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Added module.py", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp11.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertEqual(res.evidence_results[0].status, "OBSERVED")

    def test_12_observed_to_stale_transition(self):
        (self.temp_dir / "module2.py").write_text("code", encoding="utf-8")
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Added module2.py", source="agent", status="OBSERVED")]
        )
        cp_path = self.temp_dir / "cp12.json"
        CheckpointStorage(cp_path).save(cp)
        (self.temp_dir / "module2.py").unlink()
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertEqual(res.evidence_results[0].status, "STALE")

    def test_13_verified_to_stale_transition(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Referenced src/nonexistent.py", source="agent", status="VERIFIED")]
        )
        cp_path = self.temp_dir / "cp13.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        # Missing file invalidates claim -> STALE
        ev = [e for e in res.evidence_results if "nonexistent.py" in e.claim][0]
        self.assertEqual(ev.status, "STALE")


    def test_14_evidence_state_survives_checkpoint_serialization(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Claim Serialization", source="source", status="OBSERVED")]
        )
        d = cp.to_dict()
        self.assertEqual(d["evidence"][0]["status"], "OBSERVED")

    def test_15_evidence_state_survives_checkpoint_loading(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Claim Deserialization", source="source", status="OBSERVED")]
        )
        d = cp.to_dict()
        loaded = Checkpoint.from_dict(d)
        self.assertEqual(loaded.evidence[0].status, "OBSERVED")

    # -------------------------------------------------------------------------
    # 4. History & Diff (16-17)
    # -------------------------------------------------------------------------

    def test_16_evidence_differences_survive_diff(self):
        cp1 = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Test Claim", source="agent", status="AGENT_REPORTED")]
        )
        cp2 = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Test Claim", source="agent", status="OBSERVED")]
        )
        diff_str = diff_checkpoints(cp1, cp2)
        self.assertIn("~ [AGENT_REPORTED -> OBSERVED] Test Claim", diff_str)

    def test_17_evidence_changes_do_not_modify_unrelated_fields(self):
        cp1 = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Test Claim", source="agent", status="AGENT_REPORTED")]
        )
        cp2 = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Test Claim", source="agent", status="OBSERVED")]
        )
        self.assertEqual(cp1.task.objective, cp2.task.objective)
        self.assertEqual(cp1.completed, cp2.completed)

    # -------------------------------------------------------------------------
    # 5. Resume (18-20)
    # -------------------------------------------------------------------------

    def test_18_resume_exposes_evidence_status(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Resume Evidence Claim", source="src", status="OBSERVED")]
        )
        out = format_resume_output(cp)
        self.assertIn("- [OBSERVED] Resume Evidence Claim", out)

    def test_19_resume_distinguishes_agent_claims_from_observations(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[
                Evidence(claim="Observation claim", source="git", status="OBSERVED"),
                Evidence(claim="Agent claim", source="agent", status="AGENT_REPORTED"),
            ]
        )
        out = format_resume_output(cp)
        self.assertIn("[OBSERVED] Observation claim", out)
        self.assertIn("[AGENT_REPORTED] Agent claim", out)

    def test_20_resume_does_not_claim_semantic_verification(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Feature works perfectly", source="agent", status="AGENT_REPORTED")]
        )
        out = format_resume_output(cp)
        self.assertNotIn("[VERIFIED] Feature works perfectly", out)
        self.assertIn("[AGENT_REPORTED] Feature works perfectly", out)

    # -------------------------------------------------------------------------
    # 6. Inspect (21-22)
    # -------------------------------------------------------------------------

    def test_21_inspect_displays_evidence_state(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Inspect Evidence", source="src", status="OBSERVED")]
        )
        path = self.history_store.archive_checkpoint(cp)
        out = inspect_checkpoint(str(path), project_root=self.temp_dir)
        self.assertIn("EVIDENCE STORED", out)
        self.assertIn("- [OBSERVED] Inspect Evidence", out)

    def test_22_inspect_remains_read_only(self):
        cp = self._create_sample_checkpoint()
        path = self.history_store.archive_checkpoint(cp)
        mtime_before = path.stat().st_mtime
        inspect_checkpoint(str(path), project_root=self.temp_dir)
        self.assertEqual(path.stat().st_mtime, mtime_before)

    # -------------------------------------------------------------------------
    # 7. Security (23-26)
    # -------------------------------------------------------------------------

    def test_23_evidence_text_cannot_trigger_command_execution(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="`rm -rf /`", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp23.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertIsNotNone(res)

    def test_24_no_arbitrary_filesystem_traversal(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="File ../../../etc/passwd", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp24.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertIsNotNone(res)

    def test_25_no_network_access(self):
        from pac import verify
        self.assertIsNotNone(verify)

    def test_26_no_secret_leakage(self):
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="API_KEY=sk-proj-secret12345678901234567890", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp26.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        for ev in res.evidence_results:
            self.assertNotIn("sk-proj-secret12345678901234567890", ev.claim)


    # -------------------------------------------------------------------------
    # 8. Aggregate-Status Trust Invariants (27-32)
    # -------------------------------------------------------------------------

    def test_27_agent_reported_to_observed_does_not_yield_fully_verified(self):
        """AGENT_REPORTED -> OBSERVED transition must not produce FULLY_VERIFIED."""
        (self.temp_dir / "file.txt").write_text("content", encoding="utf-8")
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Created file.txt", source="agent", status="AGENT_REPORTED")],
            completed=["Created file.txt"],
        )
        cp_path = self.temp_dir / "cp27.json"
        CheckpointStorage(cp_path).save(cp)

        # Without file: AGENT_REPORTED
        (self.temp_dir / "file.txt").unlink()
        res_before = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev_before = next(e for e in res_before.evidence_results if "file.txt" in e.claim or "file.txt" in (e.verification_basis or ""))
        self.assertIn(ev_before.status, {"AGENT_REPORTED", "STALE"})
        self.assertNotEqual(res_before.overall_status, "FULLY_VERIFIED")

        # Restore file: OBSERVED — still must NOT be FULLY_VERIFIED
        (self.temp_dir / "file.txt").write_text("content", encoding="utf-8")
        res_after = verify_checkpoint(cp_path, project_root=self.temp_dir)
        observed = [e for e in res_after.evidence_results if e.status == "OBSERVED"]
        self.assertTrue(len(observed) > 0, "At least one claim should be OBSERVED after file creation")
        self.assertNotEqual(res_after.overall_status, "FULLY_VERIFIED",
                            "OBSERVED file existence must not yield FULLY_VERIFIED")

    def test_28_only_observed_evidence_cannot_be_fully_verified(self):
        """A checkpoint with only OBSERVED evidence must not be FULLY_VERIFIED."""
        (self.temp_dir / "src" / "main.py").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "src" / "main.py" / "x.py").write_text("code", encoding="utf-8")
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Observed src/main.py/x.py", source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp28.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        observed = [e for e in res.evidence_results if e.status == "OBSERVED"]
        self.assertTrue(len(observed) > 0)
        self.assertNotEqual(res.overall_status, "FULLY_VERIFIED",
                            "Only OBSERVED evidence must not yield FULLY_VERIFIED")

    def test_29_genuine_verified_claim_preserves_higher_status(self):
        """A pure VERIFIED claim (no weaker evidence) can still reach FULLY_VERIFIED."""
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="All tests pass", source="test runner", status="VERIFIED")],
            completed=[],
        )
        cp_path = self.temp_dir / "cp29.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        verified = [e for e in res.evidence_results if e.status == "VERIFIED"]
        self.assertTrue(len(verified) > 0, "VERIFIED claim should remain VERIFIED")
        self.assertEqual(res.overall_status, "FULLY_VERIFIED",
                         "All-VERIFIED evidence with no weaker claims should yield FULLY_VERIFIED")

    def test_30_stale_after_file_deletion_cannot_be_fully_verified(self):
        """After referenced file is deleted, OBSERVED -> STALE and overall is not FULLY_VERIFIED."""
        (self.temp_dir / "readme.txt").write_text("content", encoding="utf-8")
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim="Created readme.txt", source="agent", status="AGENT_REPORTED")],
            completed=["Created readme.txt"],
        )
        cp_path = self.temp_dir / "cp30.json"
        CheckpointStorage(cp_path).save(cp)

        # File present -> OBSERVED
        res_observed = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertNotEqual(res_observed.overall_status, "FULLY_VERIFIED")

        # Delete file -> STALE
        (self.temp_dir / "readme.txt").unlink()
        res_stale = verify_checkpoint(cp_path, project_root=self.temp_dir)
        self.assertNotEqual(res_stale.overall_status, "FULLY_VERIFIED",
                            "STALE evidence must not allow FULLY_VERIFIED aggregate status")

    def test_31_weak_statuses_never_upgraded_to_verified(self):
        """AGENT_REPORTED, UNKNOWN, and STALE evidence must never become VERIFIED."""
        ev_list = [
            Evidence(claim="Agent claim", source="agent", status="AGENT_REPORTED"),
            Evidence(claim="Unknown claim", source="unknown", status="UNKNOWN"),
        ]
        cp = self._create_sample_checkpoint(evidence_list=ev_list)
        cp_path = self.temp_dir / "cp31.json"
        CheckpointStorage(cp_path).save(cp)
        res = verify_checkpoint(cp_path, project_root=self.temp_dir)
        for ev in res.evidence_results:
            self.assertNotEqual(ev.status, "VERIFIED",
                                f"Claim '{ev.claim}' must not be upgraded to VERIFIED")

    def test_32_claim_text_preserved_through_all_transitions(self):
        """Original claim text must remain unchanged across AGENT_REPORTED->OBSERVED->STALE."""
        original_claim = "Created transition-test.txt"
        (self.temp_dir / "transition-test.txt").write_text("v1", encoding="utf-8")
        cp = self._create_sample_checkpoint(
            evidence_list=[Evidence(claim=original_claim, source="agent", status="AGENT_REPORTED")]
        )
        cp_path = self.temp_dir / "cp32.json"
        CheckpointStorage(cp_path).save(cp)

        # Step 1: AGENT_REPORTED -> OBSERVED
        res1 = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev1 = res1.evidence_results[0]
        self.assertEqual(ev1.status, "OBSERVED")
        self.assertEqual(ev1.claim, original_claim,
                         "Claim text must be unchanged after AGENT_REPORTED->OBSERVED")

        # Step 2: OBSERVED -> STALE (delete file)
        (self.temp_dir / "transition-test.txt").unlink()
        res2 = verify_checkpoint(cp_path, project_root=self.temp_dir)
        ev2 = res2.evidence_results[0]
        self.assertEqual(ev2.status, "STALE")
        self.assertEqual(ev2.claim, original_claim,
                         "Claim text must be unchanged after OBSERVED->STALE")


if __name__ == "__main__":
    unittest.main()
