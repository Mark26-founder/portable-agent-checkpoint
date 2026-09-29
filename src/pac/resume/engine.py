"""PAC Resume Engine."""

from pathlib import Path
from typing import Optional, Union, Dict, Any
import json

from pac.checkpoint import CheckpointStorage, CheckpointNotFoundError, CheckpointValidationError, UnsupportedVersionError
from pac.checkpoint.models import Checkpoint
from pac.verify import verify_checkpoint, VerificationResult


def format_resume_output(
    checkpoint: Checkpoint,
    verification: Optional[VerificationResult] = None,
    output_format: str = "markdown"
) -> str:
    """Formats a checkpoint object and optional verification result into a resume text.
    
    Output answering the 5 core questions:
    1. What am I working on? (Project, Objective, Status)
    2. What has already been done? (Completed)
    3. What remains? (Remaining)
    4. What important constraints/decisions must I know? (Decisions, Constraints)
    5. What should I do next? (Next Action)
    """
    if output_format == "json":
        data: Dict[str, Any] = {
            "project": {
                "name": checkpoint.project.name,
                "commit": checkpoint.project.commit,
                "dirty": checkpoint.project.dirty,
            },
            "task": {
                "objective": checkpoint.task.objective,
                "status": checkpoint.task.status,
            },
            "completed": checkpoint.completed if checkpoint.completed else [],
            "remaining": checkpoint.remaining if checkpoint.remaining else [],
            "decisions": [
                {"decision": d.decision, "reason": d.reason} for d in checkpoint.decisions
            ] if checkpoint.decisions else [],
            "constraints": checkpoint.constraints if checkpoint.constraints else [],
            "changed_files": checkpoint.changed_files if checkpoint.changed_files else [],
            "evidence": [
                {
                    "claim": e.claim,
                    "source": e.source,
                    "status": e.status,
                    "detail": e.detail,
                }
                for e in checkpoint.evidence
            ],
            "next_action": checkpoint.next_action,
            "source_agent": checkpoint.source_agent.name,
            "created_at": checkpoint.created_at,
        }
        if verification:
            data["verification"] = {
                "overall_status": verification.overall_status,
                "is_stale": verification.is_stale,
                "current_git_commit": verification.current_git_commit,
                "current_git_dirty": verification.current_git_dirty,
            }
        return json.dumps(data, indent=2)

    # Markdown format
    lines = []

    # Warning Header if Stale
    if verification and verification.is_stale:
        lines.append("WARNING: CHECKPOINT STALE")
        lines.append("")
        lines.append("Reason:")
        if verification.errors:
            for err in verification.errors:
                lines.append(f"- {err}")
        else:
            lines.append("Current Git state or workspace files differ from checkpoint capture state.")
        lines.append("")
        lines.append("Resume information may not represent the current workspace.")
        lines.append("")

    lines.append(f"[PAC] Resume — {checkpoint.project.name}")
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

    lines.append("EVIDENCE")
    if checkpoint.evidence:
        # Use verification evidence status if available, else checkpoint evidence status
        ver_map = {}
        if verification:
            for ev_res in verification.evidence_results:
                ver_map[ev_res.claim] = ev_res.status

        for e in checkpoint.evidence:
            st = ver_map.get(e.claim, e.status)
            lines.append(f"- [{st}] {e.claim} (Source: {e.source})")
    else:
        lines.append("None recorded")
    lines.append("")


    lines.append("NEXT ACTION")
    lines.append(checkpoint.next_action if checkpoint.next_action else "None recorded")
    lines.append("")

    lines.append("SOURCE AGENT")
    lines.append(checkpoint.source_agent.name if checkpoint.source_agent and checkpoint.source_agent.name else "Unknown")
    lines.append("")

    lines.append("CHECKPOINT")
    lines.append(f"Created: {checkpoint.created_at}")
    git_commit_short = checkpoint.project.commit[:8] if checkpoint.project.commit != "NONE" else "NONE"
    git_str = f"Commit: {git_commit_short}, Dirty: {checkpoint.project.dirty}"
    lines.append(f"Git: {git_str}")

    if verification:
        lines.append(f"Verification: {verification.overall_status}")
        if verification.is_stale:
            lines.append("Stale: true")

    return "\n".join(lines)


def resume_checkpoint(
    checkpoint_path: Path,
    project_root: Optional[Path] = None,
    output_format: str = "markdown",
    verify: bool = True,
) -> str:
    """Reads a checkpoint file, performs verification integration, and returns formatted resume summary."""
    cp_path = checkpoint_path.resolve()
    if not cp_path.exists():
        raise CheckpointNotFoundError(f"Checkpoint file not found: {cp_path}")

    storage = CheckpointStorage(cp_path)
    checkpoint = storage.load()
    checkpoint.validate()

    verification_res: Optional[VerificationResult] = None
    if verify:
        try:
            root = project_root if project_root else cp_path.parent
            if root.name == ".ai":
                root = root.parent
            verification_res = verify_checkpoint(cp_path, project_root=root, update_checkpoint=False)
        except Exception:
            # If verification fails unexpectedly (e.g. non-git repo edge cases), proceed cleanly without verification info
            verification_res = None

    return format_resume_output(checkpoint, verification=verification_res, output_format=output_format)
