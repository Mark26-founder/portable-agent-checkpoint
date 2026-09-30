"""S9 Tests: Benchmark Harness."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pac.benchmark.tasks import ALL_TASKS, TASK_1, TASK_2, TASK_3, BenchmarkTask
from pac.benchmark.runner import (
    _setup_workspace,
    _capture_pac_checkpoint,
    _simulate_baseline,
    _simulate_pac,
    run_benchmark,
    format_results_report,
    results_to_dict,
    ACTION_RECONSTRUCTION,
    ACTION_PRODUCTIVE,
)
from pac.checkpoint.storage import CheckpointStorage
from pac.resume import format_resume_output


class TestBenchmarkTasks(unittest.TestCase):
    """Validate task definitions are structurally complete."""

    def test_all_tasks_defined(self):
        self.assertEqual(len(ALL_TASKS), 3)

    def test_each_task_has_required_fields(self):
        for task in ALL_TASKS:
            self.assertTrue(task.task_id, f"task_id missing on {task}")
            self.assertTrue(task.objective, f"objective missing on {task.task_id}")
            self.assertTrue(task.agent_a_work, f"agent_a_work missing on {task.task_id}")
            self.assertTrue(task.agent_a_files, f"agent_a_files missing on {task.task_id}")
            self.assertTrue(task.agent_a_decisions, f"decisions missing on {task.task_id}")
            self.assertTrue(task.agent_a_constraints, f"constraints missing on {task.task_id}")
            self.assertTrue(task.remaining, f"remaining missing on {task.task_id}")
            self.assertTrue(task.next_action, f"next_action missing on {task.task_id}")
            self.assertTrue(task.correct_first_action, f"correct_first_action missing on {task.task_id}")
            self.assertTrue(task.reconstruction_signals, f"reconstruction_signals missing on {task.task_id}")

    def test_each_task_has_multiple_files(self):
        for task in ALL_TASKS:
            self.assertGreaterEqual(len(task.agent_a_files), 2,
                                    f"{task.task_id} should have >= 2 files for meaningful reconstruction")

    def test_each_task_has_multiple_decisions(self):
        for task in ALL_TASKS:
            self.assertGreaterEqual(len(task.agent_a_decisions), 2,
                                    f"{task.task_id} should have >= 2 architectural decisions")

    def test_each_task_has_reconstruction_signals(self):
        for task in ALL_TASKS:
            self.assertGreaterEqual(len(task.reconstruction_signals), 3,
                                    f"{task.task_id} should have >= 3 reconstruction signals")

    def test_task_ids_are_unique(self):
        ids = [t.task_id for t in ALL_TASKS]
        self.assertEqual(len(ids), len(set(ids)), "All task IDs must be unique")


class TestWorkspaceSetup(unittest.TestCase):
    """Validate workspace setup creates correct file structure."""

    def test_workspace_creates_all_task_files(self):
        for task in ALL_TASKS:
            workspace = _setup_workspace(task)
            try:
                for f in task.agent_a_files:
                    target = workspace / f.path
                    self.assertTrue(target.exists(), f"{f.path} not created in workspace for {task.task_id}")
                    self.assertTrue(target.is_file())
            finally:
                shutil.rmtree(workspace, ignore_errors=True)

    def test_workspace_files_have_content(self):
        workspace = _setup_workspace(TASK_1)
        try:
            for f in TASK_1.agent_a_files:
                target = workspace / f.path
                content = target.read_text(encoding="utf-8")
                self.assertEqual(content, f.content)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_ai_dir_created(self):
        workspace = _setup_workspace(TASK_1)
        try:
            self.assertTrue((workspace / ".ai").is_dir())
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


class TestCheckpointCapture(unittest.TestCase):
    """Validate PAC checkpoint capture for benchmark tasks."""

    def test_checkpoint_captures_all_completed_work(self):
        workspace = _setup_workspace(TASK_1)
        try:
            cp_path = _capture_pac_checkpoint(TASK_1, workspace)
            cp = CheckpointStorage(cp_path).load()
            for item in TASK_1.agent_a_work:
                self.assertIn(item, cp.completed)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_checkpoint_captures_remaining_tasks(self):
        workspace = _setup_workspace(TASK_2)
        try:
            cp_path = _capture_pac_checkpoint(TASK_2, workspace)
            cp = CheckpointStorage(cp_path).load()
            for item in TASK_2.remaining:
                self.assertIn(item, cp.remaining)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_checkpoint_captures_decisions(self):
        workspace = _setup_workspace(TASK_3)
        try:
            cp_path = _capture_pac_checkpoint(TASK_3, workspace)
            cp = CheckpointStorage(cp_path).load()
            decision_texts = [d.decision for d in cp.decisions]
            for dec in TASK_3.agent_a_decisions:
                self.assertIn(dec["decision"], decision_texts)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_checkpoint_captures_constraints(self):
        workspace = _setup_workspace(TASK_1)
        try:
            cp_path = _capture_pac_checkpoint(TASK_1, workspace)
            cp = CheckpointStorage(cp_path).load()
            for c in TASK_1.agent_a_constraints:
                self.assertIn(c, cp.constraints)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_checkpoint_captures_next_action(self):
        workspace = _setup_workspace(TASK_2)
        try:
            cp_path = _capture_pac_checkpoint(TASK_2, workspace)
            cp = CheckpointStorage(cp_path).load()
            self.assertEqual(cp.next_action, TASK_2.next_action)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_checkpoint_captures_changed_files(self):
        workspace = _setup_workspace(TASK_1)
        try:
            cp_path = _capture_pac_checkpoint(TASK_1, workspace)
            cp = CheckpointStorage(cp_path).load()
            for f in TASK_1.agent_a_files:
                self.assertIn(f.path, cp.changed_files)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


class TestResumeOutput(unittest.TestCase):
    """Validate pac resume output for benchmark tasks."""

    def _get_resume(self, task: BenchmarkTask) -> str:
        workspace = _setup_workspace(task)
        try:
            cp_path = _capture_pac_checkpoint(task, workspace)
            cp = CheckpointStorage(cp_path).load()
            return format_resume_output(cp)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_resume_contains_objective(self):
        resume = self._get_resume(TASK_1)
        self.assertIn(TASK_1.objective[:40], resume)

    def test_resume_contains_next_action(self):
        resume = self._get_resume(TASK_2)
        self.assertIn(TASK_2.next_action[:40], resume)

    def test_resume_contains_completed_work(self):
        resume = self._get_resume(TASK_3)
        self.assertIn(TASK_3.agent_a_work[0][:30], resume)

    def test_resume_contains_decisions(self):
        resume = self._get_resume(TASK_1)
        decision_text = TASK_1.agent_a_decisions[0]["decision"][:30]
        self.assertIn(decision_text, resume)

    def test_resume_contains_constraints(self):
        resume = self._get_resume(TASK_2)
        self.assertIn(TASK_2.agent_a_constraints[0][:30], resume)

    def test_resume_is_under_1000_tokens(self):
        for task in ALL_TASKS:
            resume = self._get_resume(task)
            # Conservative estimate: 4 chars per token
            est_tokens = len(resume) // 4
            self.assertLess(est_tokens, 1000,
                            f"Resume for {task.task_id} exceeds 1000 token estimate ({est_tokens})")

    def test_resume_labels_evidence_status(self):
        resume = self._get_resume(TASK_1)
        # At least one evidence status label should appear
        self.assertTrue(
            any(status in resume for status in ["[AGENT_REPORTED]", "[OBSERVED]", "[VERIFIED]", "[STALE]"]),
            "Resume must label evidence statuses"
        )


class TestConditionSimulation(unittest.TestCase):
    """Validate the protocol-level simulation produces correct action sequences."""

    def _get_pac_resume(self, task: BenchmarkTask) -> str:
        workspace = _setup_workspace(task)
        try:
            cp_path = _capture_pac_checkpoint(task, workspace)
            cp = CheckpointStorage(cp_path).load()
            return format_resume_output(cp)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_baseline_has_more_reconstruction_than_pac(self):
        for task in ALL_TASKS:
            resume = self._get_pac_resume(task)
            baseline = _simulate_baseline(task)
            pac = _simulate_pac(task, resume)
            self.assertGreater(baseline.reconstruction_count, pac.reconstruction_count,
                               f"{task.task_id}: baseline reconstruction must exceed PAC")

    def test_baseline_reaches_productive_action_later(self):
        for task in ALL_TASKS:
            resume = self._get_pac_resume(task)
            baseline = _simulate_baseline(task)
            pac = _simulate_pac(task, resume)
            self.assertGreater(baseline.steps_before_first_productive,
                               pac.steps_before_first_productive,
                               f"{task.task_id}: baseline should take more steps before productive action")

    def test_both_conditions_reach_productive_action(self):
        for task in ALL_TASKS:
            resume = self._get_pac_resume(task)
            baseline = _simulate_baseline(task)
            pac = _simulate_pac(task, resume)
            self.assertGreater(baseline.productive_count, 0,
                               f"{task.task_id}: baseline must reach a productive action")
            self.assertGreater(pac.productive_count, 0,
                               f"{task.task_id}: PAC condition must reach a productive action")

    def test_pac_productive_action_matches_correct_first_action(self):
        for task in ALL_TASKS:
            resume = self._get_pac_resume(task)
            pac = _simulate_pac(task, resume)
            first_prod = next(a for a in pac.actions if a.action_type == ACTION_PRODUCTIVE)
            self.assertIn(task.correct_first_action[:40], first_prod.description,
                          f"{task.task_id}: PAC first productive action must match task definition")

    def test_pac_resume_token_estimate_recorded(self):
        for task in ALL_TASKS:
            resume = self._get_pac_resume(task)
            pac = _simulate_pac(task, resume)
            self.assertGreater(pac.resume_output_tokens_est, 0)
            self.assertGreater(pac.resume_output_lines, 0)


class TestBenchmarkRunner(unittest.TestCase):
    """Integration tests for the full benchmark run."""

    def test_run_benchmark_returns_result_for_each_task(self):
        results = run_benchmark(ALL_TASKS)
        self.assertEqual(len(results), len(ALL_TASKS))

    def test_each_result_has_correct_task_id(self):
        results = run_benchmark(ALL_TASKS)
        result_ids = {r.task_id for r in results}
        task_ids = {t.task_id for t in ALL_TASKS}
        self.assertEqual(result_ids, task_ids)

    def test_all_results_show_pac_advantage(self):
        results = run_benchmark(ALL_TASKS)
        for r in results:
            self.assertGreater(r.reconstruction_reduction, 0,
                               f"{r.task_id}: PAC must reduce reconstruction vs baseline")
            self.assertGreater(r.steps_to_productive_reduction, 0,
                               f"{r.task_id}: PAC must reduce steps-to-productive vs baseline")

    def test_format_results_report_is_non_empty(self):
        results = run_benchmark(ALL_TASKS)
        report = format_results_report(results)
        self.assertIn("PAC S9 BENCHMARK RESULTS", report)
        self.assertIn("AGGREGATE", report)
        self.assertIn("PROTOCOL-LEVEL", report)

    def test_results_to_dict_is_serializable(self):
        results = run_benchmark(ALL_TASKS)
        data = results_to_dict(results)
        # Must be JSON-serializable
        serialized = json.dumps(data)
        self.assertIsInstance(serialized, str)
        self.assertIn("reconstruction_reduction_pct", serialized)

    def test_report_classifies_evidence_quality(self):
        results = run_benchmark(ALL_TASKS)
        report = format_results_report(results)
        self.assertIn("CALCULATED", report)
        self.assertIn("INFERRED", report)
        self.assertIn("UNKNOWN", report)

    def test_report_does_not_claim_universal_validity(self):
        results = run_benchmark(ALL_TASKS)
        report = format_results_report(results)
        # Must not contain fabricated universal claim
        self.assertNotIn("improves developer productivity by", report.lower())
        self.assertNotIn("proven to", report.lower())


if __name__ == "__main__":
    unittest.main()
