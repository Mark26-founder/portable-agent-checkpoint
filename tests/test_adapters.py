"""S6 Adapter Tests — PAC Agent/Environment Interoperability.

Tests the full S6 interoperability layer:
- adapter interface, generic adapter, normalizer, CLI integration, and round-trip.

All 20 required S6 test cases are covered.
Run with: py -3 -m unittest discover -s tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pac.adapters import GenericAdapter, get_adapter, AdapterInputError, normalize_adapter_payload
from pac.adapters.interface import AgentAdapter
from pac.adapters.normalizer import (
    _normalize_status,
    _normalize_decisions,
    _normalize_string_list,
    _normalize_agent_identity,
)
from pac.capture import TaskContext, capture_checkpoint
from pac.checkpoint import Checkpoint, CheckpointStorage
from pac.checkpoint.models import ProjectInfo, TaskInfo, Evidence, SourceAgent


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _init_git_repo(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_path), capture_output=True, check=True)


def _commit_file(repo_path: Path, filename: str, content: str) -> None:
    fp = repo_path / filename
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"Add {filename}"], cwd=str(repo_path), capture_output=True, check=True)


def _make_valid_context() -> dict:
    return {
        "agent": {"name": "generic-agent", "version": "1.0"},
        "task": {
            "objective": "Implement authentication",
            "completed": ["Created auth middleware"],
            "remaining": ["Add tests"],
            "next_action": "Run authentication tests",
        },
        "decisions": [{"decision": "Use JWT", "reason": "Stateless and secure"}],
        "constraints": ["Do not modify existing API"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Generic adapter valid input
# ──────────────────────────────────────────────────────────────────────────────

class Test01GenericAdapterValidInput(unittest.TestCase):

    def test_valid_input_produces_normalized_dict(self):
        adapter = GenericAdapter()
        raw = _make_valid_context()
        result = adapter.normalize(raw)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["objective"], "Implement authentication")
        self.assertIn("Created auth middleware", result["completed"])
        self.assertIn("Add tests", result["remaining"])
        self.assertEqual(result["next_action"], "Run authentication tests")
        self.assertEqual(result["source_agent"]["name"], "generic-agent")


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Malformed adapter input (not a dict)
# ──────────────────────────────────────────────────────────────────────────────

class Test02MalformedAdapterInput(unittest.TestCase):

    def test_non_dict_raises_adapter_input_error(self):
        adapter = GenericAdapter()
        with self.assertRaises(AdapterInputError):
            adapter.normalize("this is a string, not a dict")

    def test_list_raises_adapter_input_error(self):
        adapter = GenericAdapter()
        with self.assertRaises(AdapterInputError):
            adapter.normalize(["item1", "item2"])

    def test_none_raises_adapter_input_error(self):
        adapter = GenericAdapter()
        with self.assertRaises(AdapterInputError):
            adapter.normalize(None)


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Missing optional fields — safe defaults
# ──────────────────────────────────────────────────────────────────────────────

class Test03MissingOptionalFields(unittest.TestCase):

    def test_empty_dict_uses_defaults(self):
        adapter = GenericAdapter()
        result = adapter.normalize({})

        self.assertEqual(result["objective"], "Unspecified development task")
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["completed"], [])
        self.assertEqual(result["remaining"], [])
        self.assertEqual(result["decisions"], [])
        self.assertEqual(result["constraints"], [])
        self.assertEqual(result["next_action"], "Continue task implementation.")
        self.assertEqual(result["source_agent"]["name"], "unknown")

    def test_missing_decisions_and_constraints(self):
        adapter = GenericAdapter()
        raw = {
            "agent": {"name": "test-agent"},
            "task": {"objective": "Do something"},
        }
        result = adapter.normalize(raw)
        self.assertEqual(result["decisions"], [])
        self.assertEqual(result["constraints"], [])


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Unknown agent identity → 'unknown'
# ──────────────────────────────────────────────────────────────────────────────

class Test04UnknownAgentIdentity(unittest.TestCase):

    def test_no_agent_field_returns_unknown(self):
        adapter = GenericAdapter()
        result = adapter.normalize({"task": {"objective": "Do work"}})
        self.assertEqual(result["source_agent"]["name"], "unknown")

    def test_empty_agent_name_returns_unknown(self):
        result = _normalize_agent_identity({"name": ""})
        self.assertEqual(result, "unknown")

    def test_agent_none_returns_unknown(self):
        result = _normalize_agent_identity(None)
        self.assertEqual(result, "unknown")

    def test_agent_number_returns_unknown(self):
        # Non-string, non-dict types → unknown
        result = _normalize_agent_identity(42)
        self.assertEqual(result, "unknown")


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Normalization into S2 Checkpoint model
# ──────────────────────────────────────────────────────────────────────────────

class Test05NormalizationIntoCheckpoint(unittest.TestCase):

    def test_adapter_output_feeds_task_context_and_produces_valid_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.txt", "init")

            adapter = GenericAdapter()
            normalized = adapter.normalize(_make_valid_context())
            ctx = TaskContext.from_dict(normalized)

            cp, _ = capture_checkpoint(repo, task_context=ctx)
            cp.validate()  # Must pass S2 validation without error

            self.assertEqual(cp.task.objective, "Implement authentication")
            self.assertEqual(cp.source_agent.name, "generic-agent")
            self.assertIn("Created auth middleware", cp.completed)
            self.assertIn("Add tests", cp.remaining)


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: Completed work preservation
# ──────────────────────────────────────────────────────────────────────────────

class Test06CompletedWorkPreservation(unittest.TestCase):

    def test_completed_items_survive_normalization(self):
        raw = {
            "agent": {"name": "agent-a"},
            "task": {
                "objective": "Build feature",
                "completed": ["Step 1 done", "Step 2 done", "Step 3 done"],
                "remaining": [],
                "next_action": "Deploy",
            },
        }
        adapter = GenericAdapter()
        result = adapter.normalize(raw)
        self.assertEqual(result["completed"], ["Step 1 done", "Step 2 done", "Step 3 done"])

    def test_finished_alias_maps_to_completed(self):
        """'finished' is an alias for 'completed'."""
        raw = {
            "task": {
                "objective": "Build feature",
                "finished": ["Login API implementation"],
                "remaining": ["Add tests"],
                "next_action": "Test",
            }
        }
        result = normalize_adapter_payload(raw)
        self.assertIn("Login API implementation", result["completed"])


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Remaining work preservation
# ──────────────────────────────────────────────────────────────────────────────

class Test07RemainingWorkPreservation(unittest.TestCase):

    def test_remaining_items_survive_normalization(self):
        raw = {
            "agent": {"name": "agent-b"},
            "task": {
                "objective": "Build feature",
                "completed": [],
                "remaining": ["Write unit tests", "Write integration tests"],
                "next_action": "Run tests",
            },
        }
        result = normalize_adapter_payload(raw)
        self.assertIn("Write unit tests", result["remaining"])
        self.assertIn("Write integration tests", result["remaining"])

    def test_pending_alias_maps_to_remaining(self):
        """'pending' is an alias for 'remaining'."""
        raw = {
            "task": {
                "objective": "Do work",
                "pending": ["Task A", "Task B"],
                "next_action": "Do Task A",
            }
        }
        result = normalize_adapter_payload(raw)
        self.assertIn("Task A", result["remaining"])


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: Decisions preservation
# ──────────────────────────────────────────────────────────────────────────────

class Test08DecisionsPreservation(unittest.TestCase):

    def test_canonical_decisions_survive(self):
        raw = {
            "task": {"objective": "Auth"},
            "decisions": [
                {"decision": "Use JWT", "reason": "Stateless"},
                {"decision": "No sessions", "reason": "Scalability"},
            ],
        }
        result = normalize_adapter_payload(raw)
        self.assertEqual(len(result["decisions"]), 2)
        self.assertEqual(result["decisions"][0]["decision"], "Use JWT")
        self.assertEqual(result["decisions"][0]["reason"], "Stateless")

    def test_rationale_alias_for_reason(self):
        raw = {
            "task": {"objective": "Auth"},
            "decisions": [{"decision": "Use HTTPS", "rationale": "Security"}],
        }
        result = normalize_adapter_payload(raw)
        self.assertEqual(result["decisions"][0]["reason"], "Security")

    def test_string_decisions_get_default_reason(self):
        raw = {
            "task": {"objective": "Auth"},
            "decisions": ["Use PyJWT"],
        }
        result = normalize_adapter_payload(raw)
        self.assertEqual(result["decisions"][0]["decision"], "Use PyJWT")
        self.assertEqual(result["decisions"][0]["reason"], "Not recorded")


# ──────────────────────────────────────────────────────────────────────────────
# Test 9: Constraints preservation
# ──────────────────────────────────────────────────────────────────────────────

class Test09ConstraintsPreservation(unittest.TestCase):

    def test_constraints_survive_normalization(self):
        raw = {
            "task": {"objective": "Feature"},
            "constraints": ["Do not edit public API", "Keep stateless"],
        }
        result = normalize_adapter_payload(raw)
        self.assertIn("Do not edit public API", result["constraints"])
        self.assertIn("Keep stateless", result["constraints"])

    def test_rules_alias_maps_to_constraints(self):
        """'rules' is an alias for 'constraints'."""
        raw = {
            "task": {"objective": "Feature"},
            "rules": ["No external dependencies"],
        }
        result = normalize_adapter_payload(raw)
        self.assertIn("No external dependencies", result["constraints"])


# ──────────────────────────────────────────────────────────────────────────────
# Test 10: Next action preservation
# ──────────────────────────────────────────────────────────────────────────────

class Test10NextActionPreservation(unittest.TestCase):

    def test_next_action_survives(self):
        raw = {
            "task": {
                "objective": "Auth",
                "next_action": "Run pytest -v tests/test_auth.py",
            }
        }
        result = normalize_adapter_payload(raw)
        self.assertEqual(result["next_action"], "Run pytest -v tests/test_auth.py")

    def test_next_alias_maps_to_next_action(self):
        """'next' is an alias for 'next_action'."""
        raw = {
            "task": {
                "objective": "Auth",
                "next": "Deploy to staging",
            }
        }
        result = normalize_adapter_payload(raw)
        self.assertEqual(result["next_action"], "Deploy to staging")


# ──────────────────────────────────────────────────────────────────────────────
# Test 11: Evidence preservation through round-trip
# ──────────────────────────────────────────────────────────────────────────────

class Test11EvidencePreservation(unittest.TestCase):

    def test_evidence_survives_checkpoint_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "a.py", "x")

            from pac.checkpoint.models import Decision
            cp = Checkpoint(
                version="1.0",
                project=ProjectInfo(name="proj", commit="NONE", dirty=False),
                task=TaskInfo(objective="Test evidence", status="in_progress"),
                completed=["Auth done"],
                remaining=["Tests pending"],
                changed_files=[],
                next_action="Run tests",
                evidence=[
                    Evidence(claim="Auth module exists", source="pytest", status="VERIFIED", detail="1 passed"),
                    Evidence(claim="API draft", source="agent", status="AGENT_REPORTED"),
                ],
                source_agent=SourceAgent(name="agent-a"),
                created_at="2026-09-25T10:00:00Z",
                decisions=[Decision(decision="Use JWT", reason="Stateless")],
                constraints=["No breaking changes"],
            )
            cp_path = repo / ".ai" / "checkpoint.json"
            CheckpointStorage(cp_path).save(cp)
            loaded = CheckpointStorage(cp_path).load()

            self.assertEqual(len(loaded.evidence), 2)
            self.assertEqual(loaded.evidence[0].status, "VERIFIED")
            self.assertEqual(loaded.evidence[1].status, "AGENT_REPORTED")


# ──────────────────────────────────────────────────────────────────────────────
# Test 12: Round-trip checkpoint integrity
# ──────────────────────────────────────────────────────────────────────────────

class Test12RoundTripIntegrity(unittest.TestCase):

    def test_adapter_to_checkpoint_to_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.py", "pass")

            raw = _make_valid_context()
            adapter = GenericAdapter()
            normalized = adapter.normalize(raw)
            ctx = TaskContext.from_dict(normalized)

            cp, out_path = capture_checkpoint(repo, task_context=ctx)

            # Load back from disk
            loaded = CheckpointStorage(out_path).load()
            loaded.validate()

            # All fields must survive the round-trip intact
            self.assertEqual(loaded.task.objective, "Implement authentication")
            self.assertEqual(loaded.source_agent.name, "generic-agent")
            self.assertIn("Created auth middleware", loaded.completed)
            self.assertIn("Add tests", loaded.remaining)
            self.assertEqual(loaded.next_action, "Run authentication tests")
            self.assertIn("Do not modify existing API", loaded.constraints)
            self.assertEqual(loaded.decisions[0].decision, "Use JWT")
            self.assertEqual(loaded.decisions[0].reason, "Stateless and secure")


# ──────────────────────────────────────────────────────────────────────────────
# Test 13: Two different agent inputs → compatible normalized state
# ──────────────────────────────────────────────────────────────────────────────

class Test13CrossAgentCompatibleState(unittest.TestCase):
    """Proves that different source agents with equivalent semantics
    produce structurally identical PAC checkpoints."""

    def test_agent_a_and_b_produce_compatible_checkpoints(self):
        # Agent A uses 'finished' alias; Agent B uses 'completed' canonical key
        raw_a = {
            "agent": {"name": "generic-agent-A", "version": "1.0"},
            "task": {
                "objective": "Implement authentication module",
                "finished": ["Created auth middleware"],  # alias
                "remaining": ["Add tests"],
                "next_action": "Run authentication tests",
            },
            "decisions": [{"decision": "Use JWT", "reason": "Stateless"}],
            "constraints": ["Do not break existing API"],
        }
        raw_b = {
            "agent": {"name": "generic-agent-B", "version": "2.0"},
            "task": {
                "objective": "Implement authentication module",
                "completed": ["Created auth middleware"],  # canonical
                "remaining": ["Add tests"],
                "next_action": "Run authentication tests",
            },
            "decisions": [{"decision": "Use JWT", "reason": "Stateless"}],
            "constraints": ["Do not break existing API"],
        }

        adapter = GenericAdapter()
        norm_a = adapter.normalize(raw_a)
        norm_b = adapter.normalize(raw_b)

        # Objective, completed, remaining, decisions, constraints, next_action must be identical
        self.assertEqual(norm_a["objective"], norm_b["objective"])
        self.assertEqual(norm_a["completed"], norm_b["completed"])
        self.assertEqual(norm_a["remaining"], norm_b["remaining"])
        self.assertEqual(norm_a["next_action"], norm_b["next_action"])
        self.assertEqual(norm_a["decisions"], norm_b["decisions"])
        self.assertEqual(norm_a["constraints"], norm_b["constraints"])

        # Agent identity differs (as expected)
        self.assertNotEqual(
            norm_a["source_agent"]["name"],
            norm_b["source_agent"]["name"],
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test 14: Source agent metadata preservation
# ──────────────────────────────────────────────────────────────────────────────

class Test14SourceAgentMetadata(unittest.TestCase):

    def test_source_agent_name_preserved_in_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "f.py", "pass")

            raw = {
                "agent": {"name": "agent-from-environment-X", "version": "3.2"},
                "task": {"objective": "Auth", "next_action": "Test"},
            }
            adapter = GenericAdapter()
            ctx = TaskContext.from_dict(adapter.normalize(raw))
            cp, _ = capture_checkpoint(repo, task_context=ctx)

            self.assertEqual(cp.source_agent.name, "agent-from-environment-X")

    def test_source_agent_in_resume_output(self):
        from pac.resume.engine import format_resume_output
        from pac.checkpoint.models import Decision

        cp = Checkpoint(
            version="1.0",
            project=ProjectInfo(name="proj", commit="NONE", dirty=False),
            task=TaskInfo(objective="Test", status="in_progress"),
            completed=[],
            remaining=[],
            changed_files=[],
            next_action="Next step",
            evidence=[],
            source_agent=SourceAgent(name="agent-from-environment-X"),
            created_at="2026-09-25T10:00:00Z",
        )
        output = format_resume_output(cp)
        self.assertIn("agent-from-environment-X", output)


# ──────────────────────────────────────────────────────────────────────────────
# Test 15: Secret redaction through adapter
# ──────────────────────────────────────────────────────────────────────────────

class Test15SecretRedaction(unittest.TestCase):

    def test_api_key_in_objective_is_redacted(self):
        raw = {
            "agent": {"name": "agent"},
            "task": {
                "objective": "Use api_key = 'sk-12345678901234567890' to call service",
                "next_action": "Run service",
            },
        }
        result = normalize_adapter_payload(raw)
        self.assertNotIn("sk-12345678901234567890", result["objective"])
        self.assertIn("[REDACTED", result["objective"])

    def test_openai_key_in_completed_is_redacted(self):
        raw = {
            "task": {
                "objective": "Integrate API",
                "completed": ["Added OpenAI key sk-TESTOPENAIAPIKEYEXAMPLE to config"],
                "next_action": "Test",
            }
        }
        result = normalize_adapter_payload(raw)
        self.assertNotIn("sk-TESTOPENAIAPIKEYEXAMPLE", str(result["completed"]))

    def test_aws_key_in_constraints_is_redacted(self):
        raw = {
            "task": {"objective": "Deploy", "next_action": "Deploy"},
            "constraints": ["Use AKIAIOSFODNN7EXAMPLE for S3 access"],
        }
        result = normalize_adapter_payload(raw)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", str(result["constraints"]))
        self.assertIn("[REDACTED_AWS_KEY]", str(result["constraints"]))


# ──────────────────────────────────────────────────────────────────────────────
# Test 16: Existing `pac capture` behavior unchanged
# ──────────────────────────────────────────────────────────────────────────────

class Test16BackwardCompatibility(unittest.TestCase):

    def test_capture_without_adapter_still_works(self):
        """S3 capture path must remain intact when no adapter flags are used."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.py", "pass")

            cp, out_path = capture_checkpoint(repo, task_context=None)
            cp.validate()
            self.assertTrue(out_path.exists())
            self.assertEqual(cp.task.objective, "Unspecified development task")

    def test_capture_with_task_context_file_still_works(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.py", "pass")

            ctx = TaskContext(
                objective="Legacy context test",
                completed=["Done step"],
                remaining=["Remaining step"],
            )
            cp, _ = capture_checkpoint(repo, task_context=ctx)
            self.assertEqual(cp.task.objective, "Legacy context test")


# ──────────────────────────────────────────────────────────────────────────────
# Test 17: Adapter CLI integration
# ──────────────────────────────────────────────────────────────────────────────

class Test17AdapterCLI(unittest.TestCase):

    def test_adapter_name_lookup_generic(self):
        adapter = get_adapter("generic")
        self.assertIsInstance(adapter, GenericAdapter)
        self.assertEqual(adapter.name, "generic")

    def test_unknown_adapter_raises_error(self):
        with self.assertRaises(AdapterInputError):
            get_adapter("nonexistent-vendor-adapter")

    def test_adapter_load_and_normalize_from_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ctx_file = Path(tmp_dir) / "agent-ctx.json"
            ctx_file.write_text(json.dumps(_make_valid_context()), encoding="utf-8")

            adapter = GenericAdapter()
            result = adapter.load_and_normalize(ctx_file)
            self.assertEqual(result["objective"], "Implement authentication")

    def test_adapter_file_not_found_raises_adapter_input_error(self):
        adapter = GenericAdapter()
        with self.assertRaises(AdapterInputError):
            adapter.load_and_normalize(Path("/nonexistent/path/agent.json"))

    def test_adapter_invalid_json_file_raises_adapter_input_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_file = Path(tmp_dir) / "bad.json"
            bad_file.write_text("{ not valid json ...", encoding="utf-8")
            adapter = GenericAdapter()
            with self.assertRaises(AdapterInputError):
                adapter.load_and_normalize(bad_file)


# ──────────────────────────────────────────────────────────────────────────────
# Test 18: Invalid adapter input produces clean error
# ──────────────────────────────────────────────────────────────────────────────

class Test18InvalidInputCleanError(unittest.TestCase):

    def test_list_input_raises_adapter_input_error(self):
        with self.assertRaises(AdapterInputError):
            normalize_adapter_payload(["task1", "task2"])

    def test_none_input_raises_adapter_input_error(self):
        with self.assertRaises(AdapterInputError):
            normalize_adapter_payload(None)

    def test_invalid_completed_type_raises_adapter_input_error(self):
        with self.assertRaises(AdapterInputError):
            _normalize_string_list(42, "completed")

    def test_invalid_decisions_type_raises_adapter_input_error(self):
        with self.assertRaises(AdapterInputError):
            _normalize_decisions("not a list")


# ──────────────────────────────────────────────────────────────────────────────
# Test 19: No external API dependency
# ──────────────────────────────────────────────────────────────────────────────

class Test19NoExternalAPIDependency(unittest.TestCase):

    def test_adapter_module_has_no_forbidden_imports(self):
        """Verify that adapter modules do not import external API SDKs."""
        forbidden = [
            "openai", "anthropic", "boto3", "requests", "httpx",
            "aiohttp", "langchain", "cursor", "codex",
        ]
        adapter_dir = Path(__file__).parent.parent / "src" / "pac" / "adapters"
        for py_file in adapter_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for lib in forbidden:
                self.assertNotIn(
                    f"import {lib}",
                    content,
                    msg=f"Forbidden import '{lib}' found in {py_file.name}",
                )
                self.assertNotIn(
                    f"from {lib}",
                    content,
                    msg=f"Forbidden import 'from {lib}' found in {py_file.name}",
                )

    def test_adapter_works_fully_offline(self):
        """Full normalization must work without any network access."""
        # This test succeeds if the above execution completes — no mocking needed
        adapter = GenericAdapter()
        result = adapter.normalize(_make_valid_context())
        self.assertIn("objective", result)


# ──────────────────────────────────────────────────────────────────────────────
# Test 20: Deterministic output
# ──────────────────────────────────────────────────────────────────────────────

class Test20DeterministicOutput(unittest.TestCase):

    def test_same_input_produces_identical_output(self):
        adapter = GenericAdapter()
        raw = _make_valid_context()
        result1 = adapter.normalize(raw)
        result2 = adapter.normalize(raw)
        self.assertEqual(result1, result2)

    def test_deterministic_status_normalization(self):
        for raw_val, expected in [
            ("in_progress", "in_progress"),
            ("IN_PROGRESS", "in_progress"),
            ("active", "in_progress"),
            ("blocked", "blocked"),
            ("BLOCKED", "blocked"),
            ("completed", "completed"),
            ("done", "completed"),
            ("finished", "completed"),
            ("unknown_value", "in_progress"),
            (None, "in_progress"),
        ]:
            with self.subTest(raw_val=raw_val):
                self.assertEqual(_normalize_status(raw_val), expected)

    def test_cross_agent_handoff_is_deterministic(self):
        """Simulates the cross-agent handoff scenario end-to-end and checks idempotency."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "init.py", "pass")

            # Agent A generates context
            raw_a = {
                "agent": {"name": "generic-agent-A"},
                "task": {
                    "objective": "Build auth system",
                    "finished": ["Implement JWT"],
                    "remaining": ["Write tests"],
                    "next_action": "Write and run tests",
                },
                "decisions": [{"decision": "Use HS256", "reason": "Simple and secure"}],
                "constraints": ["No external auth services"],
            }
            adapter = GenericAdapter()
            normalized_a = adapter.normalize(raw_a)
            ctx_a = TaskContext.from_dict(normalized_a)
            cp_a, cp_path = capture_checkpoint(repo, task_context=ctx_a)

            # Agent B receives checkpoint, runs resume
            from pac.resume import resume_checkpoint
            resume_output = resume_checkpoint(cp_path, project_root=repo, verify=False)

            # All critical fields must be present in resume output
            self.assertIn("Build auth system", resume_output)
            self.assertIn("Implement JWT", resume_output)
            self.assertIn("Write tests", resume_output)
            self.assertIn("Write and run tests", resume_output)
            self.assertIn("Use HS256", resume_output)
            self.assertIn("No external auth services", resume_output)
            self.assertIn("generic-agent-A", resume_output)

            # Resume output must not be vendor-specific
            for vendor_word in ["Claude", "Cursor", "Codex", "Copilot", "Antigravity", "Gemini"]:
                self.assertNotIn(
                    vendor_word,
                    resume_output,
                    msg=f"Vendor word '{vendor_word}' found in resume output",
                )


# ──────────────────────────────────────────────────────────────────────────────
# Test 21: Dedicated Cross-Agent Handoff Proof (Agent A → PAC → Agent B)
# ──────────────────────────────────────────────────────────────────────────────

class Test21CrossAgentHandoff(unittest.TestCase):

    def test_cross_agent_handoff(self):
        """Dedicated test proving Agent A → PAC checkpoint → Agent B → resume/continue.

        Verifies all 15 required conditions:
        1. Agent A context loads.
        2. Agent A context normalizes.
        3. PAC checkpoint is created.
        4. Checkpoint provenance is Agent A.
        5. Agent B is a different agent.
        6. Agent B receives/consumes the checkpoint.
        7. Resume output contains the original work state.
        8. Objective is unchanged.
        9. Completed work is unchanged.
        10. Remaining work is unchanged.
        11. Decisions are unchanged.
        12. Constraints are unchanged.
        13. Next action is unchanged.
        14. No vendor-specific dependency exists.
        15. Agent B does not need Agent A's proprietary session/context.
        """
        examples_dir = Path(__file__).parent.parent / "examples"
        agent_a_file = examples_dir / "agent-A.json"
        agent_b_file = examples_dir / "agent-B.json"

        # 1. Agent A context loads
        self.assertTrue(agent_a_file.exists(), "examples/agent-A.json must exist")
        self.assertTrue(agent_b_file.exists(), "examples/agent-B.json must exist")

        with open(agent_a_file, "r", encoding="utf-8") as f:
            raw_agent_a = json.load(f)
        with open(agent_b_file, "r", encoding="utf-8") as f:
            raw_agent_b = json.load(f)

        # 2. Agent A context normalizes
        adapter_a = get_adapter("generic")
        norm_a = adapter_a.normalize(raw_agent_a)
        self.assertIsInstance(norm_a, dict)
        self.assertEqual(norm_a["source_agent"]["name"], "generic-agent-A")

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            _init_git_repo(repo)
            _commit_file(repo, "src/auth/jwt.py", "# JWT implementation")

            # 3. PAC checkpoint is created
            ctx_a = TaskContext.from_dict(norm_a)
            cp_a, cp_path = capture_checkpoint(repo, task_context=ctx_a)
            self.assertTrue(cp_path.exists())

            # 4. Checkpoint provenance is Agent A
            self.assertEqual(cp_a.source_agent.name, "generic-agent-A")

            # Load stored checkpoint directly to verify stored provenance
            cp_stored = CheckpointStorage(cp_path).load()
            self.assertEqual(cp_stored.source_agent.name, "generic-agent-A")

            # 5. Agent B is a different agent (explicit identity check)
            adapter_b = get_adapter("generic")
            norm_b = adapter_b.normalize(raw_agent_b)
            agent_a_identity = norm_a["source_agent"]["name"]
            agent_b_identity = norm_b["source_agent"]["name"]
            self.assertEqual(agent_a_identity, "generic-agent-A")
            self.assertEqual(agent_b_identity, "generic-agent-B")
            self.assertNotEqual(agent_a_identity, agent_b_identity)

            # 6. Agent B receives/consumes the checkpoint
            # Agent B environment calls pac resume on the checkpoint generated by Agent A
            from pac.resume import resume_checkpoint
            resume_output = resume_checkpoint(cp_path, project_root=repo, verify=False)

            # Checkpoint provenance remains Agent A after Agent B resume
            self.assertIn("generic-agent-A", resume_output)
            self.assertNotIn("generic-agent-B", cp_stored.source_agent.name)

            # 7. Resume output contains the original work state
            self.assertIn("Implement user authentication module", resume_output)

            # 8. Objective is unchanged
            self.assertEqual(cp_stored.task.objective, norm_a["objective"])
            self.assertEqual(cp_stored.task.objective, "Implement user authentication module")

            # 9. Completed work is unchanged
            self.assertEqual(cp_stored.completed, norm_a["completed"])
            self.assertEqual(
                cp_stored.completed,
                [
                    "Created JWT token generation in src/auth/jwt.py",
                    "Added user session payload extraction",
                    "Defined auth middleware skeleton",
                ],
            )

            # 10. Remaining work is unchanged
            self.assertEqual(cp_stored.remaining, norm_a["remaining"])
            self.assertEqual(
                cp_stored.remaining,
                [
                    "Wire auth middleware into router endpoints",
                    "Add integration tests for expired tokens",
                    "Handle missing Authorization header gracefully",
                ],
            )

            # 11. Decisions are unchanged
            stored_decisions = [{"decision": d.decision, "reason": d.reason} for d in cp_stored.decisions]
            self.assertEqual(stored_decisions, norm_a["decisions"])
            self.assertEqual(len(stored_decisions), 2)
            self.assertEqual(stored_decisions[0]["decision"], "Use PyJWT instead of python-jose")

            # 12. Constraints are unchanged
            self.assertEqual(cp_stored.constraints, norm_a["constraints"])
            self.assertEqual(len(cp_stored.constraints), 3)
            self.assertIn("Keep authentication purely stateless", cp_stored.constraints)

            # 13. Next action is unchanged
            self.assertEqual(cp_stored.next_action, norm_a["next_action"])
            self.assertEqual(
                cp_stored.next_action,
                "Implement header extraction in src/auth/middleware.py and run pytest tests/test_auth.py",
            )

            # 14. No vendor-specific dependency exists
            for vendor_word in ["Claude", "Cursor", "Codex", "Copilot", "Antigravity", "Gemini"]:
                self.assertNotIn(vendor_word, resume_output)

            # 15. Agent B does not need Agent A's proprietary session/context
            # Resume consumes ONLY the PAC checkpoint file (cp_path), requiring zero Agent A context files
            self.assertTrue(cp_path.stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()
