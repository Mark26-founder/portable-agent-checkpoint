"""Capture Engine orchestrator for PAC."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from pac.capture.git import inspect_git_repository, GitState
from pac.capture.context import TaskContext
from pac.capture.redact import redact_string, redact_structure
from pac.checkpoint.models import (
    Checkpoint,
    ProjectInfo,
    TaskInfo,
    Decision,
    Evidence,
    SourceAgent,
    SUPPORTED_VERSION,
)
from pac.checkpoint.storage import CheckpointStorage
from pac.checkpoint.errors import CheckpointValidationError


def capture_checkpoint(
    project_root: Path,
    task_context: Optional[TaskContext] = None,
    output_path: Optional[Path] = None,
    explicit_task_override: Optional[str] = None,
    explicit_next_override: Optional[str] = None,
    explicit_evidence: Optional[List[Evidence]] = None,
) -> Tuple[Checkpoint, Path]:
    """Captures project state and builds a validated Checkpoint.

    Returns a tuple of (Checkpoint instance, saved Path).
    """
    project_root = project_root.resolve()

    # 1. Inspect Git state
    git_state = inspect_git_repository(project_root)

    # 2. Setup project info
    project_name = project_root.name or "unknown-project"
    project_info = ProjectInfo(
        name=project_name,
        commit=git_state.commit,
        dirty=git_state.dirty,
    )

    # 3. Process task context
    ctx = task_context or TaskContext()

    objective = explicit_task_override.strip() if explicit_task_override and explicit_task_override.strip() else ctx.objective
    next_action = explicit_next_override.strip() if explicit_next_override and explicit_next_override.strip() else ctx.next_action

    task_info = TaskInfo(
        objective=redact_string(objective),
        status=ctx.status,
    )

    completed = [redact_string(item) for item in ctx.completed]
    remaining = [redact_string(item) for item in ctx.remaining]
    constraints = [redact_string(item) for item in ctx.constraints]
    next_action_redacted = redact_string(next_action)

    decisions = [
        Decision(
            decision=redact_string(d.decision),
            reason=redact_string(d.reason),
        )
        for d in ctx.decisions
    ]

    source_agent = SourceAgent(name=redact_string(ctx.source_agent_name))

    # 4. Formulate evidence entries
    evidence_items: List[Evidence] = []

    # System-observed facts (OBSERVED status)
    if git_state.is_git_repo:
        evidence_items.append(
            Evidence(
                claim=f"Repository working tree dirty status is {git_state.dirty}",
                source="git status",
                status="OBSERVED",
                detail=f"Changed files count: {len(git_state.changed_files)}",
            )
        )
        if git_state.commit != "NONE":
            evidence_items.append(
                Evidence(
                    claim=f"Current commit is {git_state.commit[:8]}",
                    source="git rev-parse HEAD",
                    status="OBSERVED",
                    detail=f"Full commit: {git_state.commit}",
                )
            )
    else:
        evidence_items.append(
            Evidence(
                claim="Project is not a Git repository",
                source="git status",
                status="OBSERVED",
                detail="git rev-parse --is-inside-work-tree returned false or failed",
            )
        )

    # Add agent-reported claims if context was explicitly provided
    if task_context is not None:
        evidence_items.append(
            Evidence(
                claim=f"Agent context provided for objective: {task_info.objective}",
                source=f"agent input ({source_agent.name})",
                status="AGENT_REPORTED",
                detail=f"Context input provided {len(completed)} completed sub-tasks and {len(remaining)} remaining.",
            )
        )

    # Append any explicit extra evidence items passed into function
    if explicit_evidence:
        for ev in explicit_evidence:
            evidence_items.append(
                Evidence(
                    claim=redact_string(ev.claim),
                    source=redact_string(ev.source),
                    status=ev.status,
                    detail=redact_string(ev.detail) if ev.detail else None,
                )
            )

    # 5. Timestamp (ISO-8601 UTC)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 6. Build Checkpoint domain object
    checkpoint = Checkpoint(
        version=SUPPORTED_VERSION,
        project=project_info,
        task=task_info,
        completed=completed,
        remaining=remaining,
        changed_files=git_state.changed_files,
        next_action=next_action_redacted,
        evidence=evidence_items,
        source_agent=source_agent,
        created_at=created_at,
        decisions=decisions,
        constraints=constraints,
    )

    # 7. Validate checkpoint against S2 schema rules
    checkpoint.validate()

    # 8. Save checkpoint to storage (active location)
    save_path = output_path if output_path else project_root / ".ai" / "checkpoint.json"
    storage = CheckpointStorage(save_path)
    storage.save(checkpoint)

    # 9. Archive to history store (.ai/checkpoints/<id>.json)
    try:
        from pac.history import CheckpointHistoryStore
        history_store = CheckpointHistoryStore(project_root)
        history_store.archive_checkpoint(checkpoint)
    except Exception:
        # Saving to history is non-fatal if root is custom or read-only
        pass

    return checkpoint, save_path

