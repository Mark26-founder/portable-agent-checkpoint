"""Checkpoint History & Storage Lifecycle Engine for S7."""

import hashlib
import json
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from pac.checkpoint.models import Checkpoint
from pac.checkpoint.storage import CheckpointStorage
from pac.checkpoint.errors import CheckpointValidationError, CheckpointNotFoundError
from pac.verify import verify_checkpoint, VerificationResult


def compute_checkpoint_id(checkpoint: Checkpoint) -> str:
    """Computes a deterministic, unique, safe ID for a Checkpoint.
    
    Formula: SHA-256 hash of project, created_at, task, completed, remaining, next_action, decisions, and source_agent (first 12 chars).
    """
    dec_str = ",".join(f"{d.decision}:{d.reason}" for d in checkpoint.decisions)
    raw_key = f"{checkpoint.project.name}:{checkpoint.created_at}:{checkpoint.task.objective}:{checkpoint.next_action}:{','.join(checkpoint.completed)}:{','.join(checkpoint.remaining)}:{dec_str}:{checkpoint.source_agent.name}"
    full_sha = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return full_sha[:12]




def sanitize_id(checkpoint_id: str) -> str:
    """Ensures a checkpoint ID is safe for filesystem use and prevents path traversal."""
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        raise CheckpointValidationError("Checkpoint ID must be a non-empty string.")
    
    # Strip extension if passed
    clean_id = checkpoint_id
    if clean_id.endswith(".json"):
        clean_id = clean_id[:-5]
    
    # Check for path traversal characters
    if ".." in clean_id or "/" in clean_id or "\\" in clean_id or ":" in clean_id:
        raise CheckpointValidationError(f"Invalid checkpoint ID or path traversal detected: '{checkpoint_id}'")
    
    # Ensure ID contains only alphanumeric, hyphen, underscore, or period
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", clean_id):
        raise CheckpointValidationError(f"Invalid characters in checkpoint ID: '{checkpoint_id}'")
    
    return clean_id


class CheckpointHistoryStore:
    """Manages checkpoint history and lifecycle in .ai/checkpoints/ directory."""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = (project_root or Path.cwd()).resolve()
        self.ai_dir = self.project_root / ".ai"
        self.checkpoints_dir = self.ai_dir / "checkpoints"
        self.active_checkpoint_path = self.ai_dir / "checkpoint.json"

    def get_checkpoint_path(self, checkpoint_id: str) -> Path:
        """Returns path to a specific checkpoint in history store after sanitization."""
        clean_id = sanitize_id(checkpoint_id)
        cp_path = (self.checkpoints_dir / f"{clean_id}.json").resolve()
        # Verify resolved path is strictly within self.checkpoints_dir
        try:
            cp_path.relative_to(self.checkpoints_dir.resolve())
        except ValueError:
            raise CheckpointValidationError(f"Path traversal outside checkpoints directory: '{checkpoint_id}'")
        return cp_path

    def resolve_checkpoint_path(self, path_or_id: str) -> Path:
        """Resolves a string path or checkpoint ID to a file Path."""
        if not path_or_id or not path_or_id.strip():
            raise CheckpointNotFoundError("Checkpoint path or ID cannot be empty.")

        path_obj = Path(path_or_id)
        
        # 1. Direct file path check
        if path_obj.exists() and path_obj.is_file():
            return path_obj.resolve()
        
        # 2. Look in .ai/checkpoints/<id>.json
        try:
            hist_path = self.get_checkpoint_path(path_or_id)
            if hist_path.exists():
                return hist_path
        except CheckpointValidationError:
            pass

        # 3. Look in .ai/checkpoints/<path_or_id> if given with .json
        if not path_or_id.endswith(".json"):
            try:
                hist_path_json = self.get_checkpoint_path(f"{path_or_id}.json")
                if hist_path_json.exists():
                    return hist_path_json
            except CheckpointValidationError:
                pass

        raise CheckpointNotFoundError(f"Checkpoint not found for ID or path: '{path_or_id}'")

    def archive_checkpoint(self, checkpoint: Checkpoint) -> Path:
        """Saves a checkpoint into .ai/checkpoints/<checkpoint-id>.json."""
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        cp_id = compute_checkpoint_id(checkpoint)
        dest_path = self.get_checkpoint_path(cp_id)
        storage = CheckpointStorage(dest_path)
        storage.save(checkpoint)
        return dest_path

    def list_history(self) -> List[Dict[str, Any]]:
        """Lists all checkpoints in .ai/checkpoints/ ordered deterministically (created_at desc, id desc)."""
        if not self.checkpoints_dir.exists():
            return []

        entries: List[Dict[str, Any]] = []

        for item in self.checkpoints_dir.glob("*.json"):
            if item.is_file():
                try:
                    storage = CheckpointStorage(item)
                    cp = storage.load()
                    cp_id = item.stem
                    
                    # Run lightweight verification check without mutating
                    ver_status = "UNKNOWN"
                    try:
                        ver_res = verify_checkpoint(item, project_root=self.project_root, update_checkpoint=False)
                        ver_status = ver_res.overall_status
                    except Exception:
                        ver_status = "UNKNOWN"

                    entries.append({
                        "id": cp_id,
                        "file_name": item.name,
                        "path": item,
                        "created_at": cp.created_at,
                        "objective": cp.task.objective,
                        "source_agent": cp.source_agent.name,
                        "verification_status": ver_status,
                        "checkpoint": cp,
                    })
                except Exception:
                    # Ignore invalid or corrupted non-checkpoint files gracefully in history listing
                    continue


        # Sort deterministically: created_at descending, then id descending
        entries.sort(key=lambda x: (x["created_at"], x["id"]), reverse=True)
        return entries

    def recover(self, checkpoint_path_or_id: str) -> Tuple[Checkpoint, Path]:
        """Recovers a specified checkpoint as active checkpoint (.ai/checkpoint.json).
        
        Performs conservative atomic recovery. Validates target first.
        Does NOT touch git or project source files.
        """
        target_path = self.resolve_checkpoint_path(checkpoint_path_or_id)
        
        # Load & strictly validate target checkpoint
        storage = CheckpointStorage(target_path)
        checkpoint = storage.load()
        checkpoint.validate()  # Fails if invalid/unsupported

        # Ensure .ai directory exists
        self.ai_dir.mkdir(parents=True, exist_ok=True)

        # Prepare atomic save to .ai/checkpoint.json
        tmp_active = self.ai_dir / "checkpoint.json.tmp"
        try:
            tmp_storage = CheckpointStorage(tmp_active)
            tmp_storage.save(checkpoint)
            # Atomic replace
            tmp_active.replace(self.active_checkpoint_path)
        except Exception as e:
            if tmp_active.exists():
                try:
                    tmp_active.unlink()
                except Exception:
                    pass
            raise CheckpointValidationError(f"Failed to recover checkpoint atomically: {e}")

        return checkpoint, self.active_checkpoint_path


def format_history_output(history_entries: List[Dict[str, Any]]) -> str:
    """Formats history entries into deterministic text table output."""
    lines = []
    lines.append("PAC CHECKPOINT HISTORY")
    lines.append("")

    if not history_entries:
        lines.append("No checkpoints found in history (.ai/checkpoints/).")
        return "\n".join(lines)

    lines.append(f"{'ID':<14} {'CREATED':<20} {'STATUS':<20} {'AGENT':<15} {'OBJECTIVE'}")
    lines.append("-" * 90)

    for entry in history_entries:
        cp_id = entry["id"]
        created = entry["created_at"].replace("T", " ")[:16]  # e.g. 2026-09-25 18:10
        status = entry["verification_status"]
        agent = entry["source_agent"][:14]
        obj = entry["objective"]
        if len(obj) > 30:
            obj = obj[:27] + "..."

        lines.append(f"{cp_id:<14} {created:<20} {status:<20} {agent:<15} {obj}")

    return "\n".join(lines)


def inspect_checkpoint(
    checkpoint_path_or_id: str,
    project_root: Optional[Path] = None,
) -> str:
    """Inspects stored checkpoint state cleanly without modifying anything or running commands."""
    store = CheckpointHistoryStore(project_root)
    cp_path = store.resolve_checkpoint_path(checkpoint_path_or_id)

    storage = CheckpointStorage(cp_path)
    checkpoint = storage.load()
    checkpoint.validate()

    cp_id = compute_checkpoint_id(checkpoint)

    lines = []
    lines.append(f"[PAC INSPECT] Checkpoint {cp_id}")
    lines.append(f"File: {cp_path.name}")
    lines.append("")
    lines.append("PROJECT")
    lines.append(f"Name: {checkpoint.project.name}")
    git_commit = checkpoint.project.commit[:8] if checkpoint.project.commit != "NONE" else "NONE"
    lines.append(f"Git Commit: {git_commit} (Dirty: {checkpoint.project.dirty})")
    lines.append("")

    lines.append("TASK")
    lines.append(f"Objective: {checkpoint.task.objective}")
    lines.append(f"Status: {checkpoint.task.status}")
    lines.append("")

    lines.append("COMPLETED")
    if checkpoint.completed:
        for item in checkpoint.completed:
            lines.append(f"- {item}")
    else:
        lines.append("None recorded")
    lines.append("")

    lines.append("REMAINING")
    if checkpoint.remaining:
        for item in checkpoint.remaining:
            lines.append(f"- {item}")
    else:
        lines.append("None recorded")
    lines.append("")

    lines.append("DECISIONS")
    if checkpoint.decisions:
        for d in checkpoint.decisions:
            lines.append(f"- {d.decision} (Reason: {d.reason})")
    else:
        lines.append("None recorded")
    lines.append("")

    lines.append("CONSTRAINTS")
    if checkpoint.constraints:
        for c in checkpoint.constraints:
            lines.append(f"- {c}")
    else:
        lines.append("None recorded")
    lines.append("")

    lines.append("CHANGED FILES")
    if checkpoint.changed_files:
        for f in checkpoint.changed_files:
            lines.append(f"- {f}")
    else:
        lines.append("None recorded")
    lines.append("")

    lines.append("EVIDENCE STORED")
    if checkpoint.evidence:
        for e in checkpoint.evidence:
            lines.append(f"- [{e.status}] {e.claim} (Source: {e.source})")
    else:
        lines.append("None recorded")
    lines.append("")

    lines.append("NEXT ACTION")
    lines.append(checkpoint.next_action if checkpoint.next_action else "None recorded")
    lines.append("")

    lines.append("METADATA")
    lines.append(f"Source Agent: {checkpoint.source_agent.name}")
    lines.append(f"Created At: {checkpoint.created_at}")
    lines.append(f"Schema Version: {checkpoint.version}")

    return "\n".join(lines)
