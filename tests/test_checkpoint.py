"""Unit tests for PAC S2 Core Checkpoint Engine (Standard Library unittest)."""

import json
import os
import sys
from pathlib import Path
import tempfile
import unittest

# Ensure src/ is on python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pac.checkpoint.models import (
    ProjectInfo,
    TaskInfo,
    Decision,
    Evidence,
    SourceAgent,
    Checkpoint,
)
from pac.checkpoint.errors import (
    CheckpointValidationError,
    UnsupportedVersionError,
    CheckpointNotFoundError,
)
from pac.checkpoint.storage import CheckpointStorage


def make_valid_checkpoint() -> Checkpoint:
    return Checkpoint(
        version="1.0",
        project=ProjectInfo(
            name="portable-agent-checkpoint",
            commit="a1b2c3d4e5f678901234567890abcdef12345678",
            dirty=True,
        ),
        task=TaskInfo(
            objective="Implement user authentication middleware",
            status="in_progress",
        ),
        completed=[
            "Defined JWT token verification functions in auth/jwt.py",
            "Added user session payload extraction",
        ],
        remaining=[
            "Wire auth middleware into router endpoints",
            "Add integration test for expired tokens",
        ],
        decisions=[
            Decision(
                decision="Use PyJWT instead of python-jose",
                reason="python-jose is unmaintained and has known security vulnerabilities.",
            )
        ],
        constraints=[
            "Do not change existing endpoint signature for /api/v1/status",
            "Keep authentication purely stateless",
        ],
        changed_files=[
            "src/auth/jwt.py",
            "tests/test_jwt.py",
        ],
        next_action="Implement header extraction in src/auth/middleware.py and run pytest.",
        evidence=[
            Evidence(
                claim="JWT token generation unit tests pass",
                source="pytest tests/test_jwt.py",
                status="VERIFIED",
                detail="8 passed in 0.42s",
            ),
            Evidence(
                claim="Middleware handles missing headers gracefully",
                source="AI agent",
                status="AGENT_REPORTED",
                detail="Drafted logic in conversation but test file not yet executed",
            ),
        ],
        source_agent=SourceAgent(name="antigravity-agent"),
        created_at="2026-09-22T21:38:00Z",
    )


class TestCheckpointEngine(unittest.TestCase):

    # 1. Valid checkpoint creation
    def test_valid_checkpoint_creation(self):
        cp = make_valid_checkpoint()
        self.assertEqual(cp.version, "1.0")
        self.assertEqual(cp.project.name, "portable-agent-checkpoint")

    # 2. Valid checkpoint validation
    def test_valid_checkpoint_validation(self):
        cp = make_valid_checkpoint()
        cp.validate()  # should not raise

    # 3. Missing required field
    def test_missing_required_field(self):
        cp = make_valid_checkpoint()
        cp.next_action = ""  # invalid empty string
        with self.assertRaises(CheckpointValidationError) as cm:
            cp.validate()
        self.assertIn("next_action", str(cm.exception))

    # 4. Invalid field type
    def test_invalid_field_type(self):
        cp = make_valid_checkpoint()
        cp.completed = "not a list"  # type: ignore
        with self.assertRaises(CheckpointValidationError) as cm:
            cp.validate()
        self.assertIn("completed must be a list", str(cm.exception))

    # 5. Invalid task status
    def test_invalid_task_status(self):
        cp = make_valid_checkpoint()
        cp.task.status = "invalid_status"
        with self.assertRaises(CheckpointValidationError) as cm:
            cp.validate()
        self.assertIn("task.status must be one of", str(cm.exception))

    # 6. Invalid evidence status
    def test_invalid_evidence_status(self):
        cp = make_valid_checkpoint()
        cp.evidence[0].status = "PASSED"
        with self.assertRaises(CheckpointValidationError) as cm:
            cp.validate()
        self.assertIn("evidence[].status must be one of", str(cm.exception))

    # 7. JSON serialization
    def test_json_serialization(self):
        cp = make_valid_checkpoint()
        d = cp.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["version"], "1.0")
        self.assertEqual(d["project"]["name"], "portable-agent-checkpoint")

    # 8. JSON loading
    def test_json_loading(self):
        cp = make_valid_checkpoint()
        d = cp.to_dict()
        cp_loaded = Checkpoint.from_dict(d)
        self.assertEqual(cp_loaded.version, cp.version)
        self.assertEqual(cp_loaded.project.name, cp.project.name)

    # 9 & 10. Save and load checkpoint
    def test_save_and_load_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cp_file = Path(tmp_dir) / ".ai" / "checkpoint.json"
            storage = CheckpointStorage(cp_file)

            cp_orig = make_valid_checkpoint()
            storage.save(cp_orig)

            self.assertTrue(cp_file.exists())

            cp_loaded = storage.load()
            self.assertEqual(cp_loaded.version, cp_orig.version)
            self.assertEqual(cp_loaded.task.objective, cp_orig.task.objective)

    # 11. Missing checkpoint file
    def test_missing_checkpoint_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cp_file = Path(tmp_dir) / "non_existent.json"
            storage = CheckpointStorage(cp_file)
            with self.assertRaises(CheckpointNotFoundError):
                storage.load()

    # 12. Unsupported checkpoint version
    def test_unsupported_checkpoint_version(self):
        cp = make_valid_checkpoint()
        cp.version = "99.0"
        with self.assertRaises(UnsupportedVersionError):
            cp.validate()

    # 13. Creation of .ai storage directory when required
    def test_creation_of_ai_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir) / "sub_dir" / ".ai"
            cp_file = target_dir / "checkpoint.json"
            self.assertFalse(target_dir.exists())

            storage = CheckpointStorage(cp_file)
            cp = make_valid_checkpoint()
            storage.save(cp)

            self.assertTrue(target_dir.exists())
            self.assertTrue(cp_file.exists())

    # 14. Round-trip consistency
    def test_roundtrip_consistency(self):
        cp_orig = make_valid_checkpoint()
        dict_repr = cp_orig.to_dict()
        json_repr = json.dumps(dict_repr)
        loaded_dict = json.loads(json_repr)
        cp_reconstructed = Checkpoint.from_dict(loaded_dict)

        self.assertEqual(cp_reconstructed.to_dict(), dict_repr)


if __name__ == "__main__":
    unittest.main()
