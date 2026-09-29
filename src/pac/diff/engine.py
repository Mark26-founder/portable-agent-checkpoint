"""PAC Work-State Diff Engine."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
import json

from pac.checkpoint import CheckpointStorage, CheckpointNotFoundError, CheckpointValidationError
from pac.checkpoint.models import Checkpoint, Decision, Evidence


def _diff_string_lists(list_a: List[str], list_b: List[str]) -> Tuple[List[str], List[str]]:
    """Compares two string lists by exact value, preserving order where appropriate.
    Returns (added, removed).
    """
    set_a = set(list_a)
    set_b = set(list_b)
    
    # Preserving order in B for added, order in A for removed
    added = [x for x in list_b if x not in set_a]
    removed = [x for x in list_a if x not in set_b]
    return added, removed


def _diff_decisions(decisions_a: List[Decision], decisions_b: List[Decision]) -> Tuple[List[Decision], List[Decision]]:
    """Compares decisions by value (decision + reason).
    Returns (added, removed).
    """
    map_a = {(d.decision, d.reason): d for d in decisions_a}
    map_b = {(d.decision, d.reason): d for d in decisions_b}

    added = [map_b[k] for k in map_b if k not in map_a]
    removed = [map_a[k] for k in map_a if k not in map_b]
    return added, removed


def _diff_evidence(evidence_a: List[Evidence], evidence_b: List[Evidence]) -> Tuple[List[Evidence], List[Evidence], List[Tuple[Evidence, Evidence]]]:
    """Compares evidence items by claim, status, source, and detail.
    Returns (added, removed, modified).
    """
    # Key by claim for matching identity
    map_a = {e.claim: e for e in evidence_a}
    map_b = {e.claim: e for e in evidence_b}

    added: List[Evidence] = []
    removed: List[Evidence] = []
    modified: List[Tuple[Evidence, Evidence]] = []

    for claim, eb in map_b.items():
        if claim not in map_a:
            added.append(eb)
        else:
            ea = map_a[claim]
            if (ea.status != eb.status) or (ea.source != eb.source) or (ea.detail != eb.detail):
                modified.append((ea, eb))

    for claim, ea in map_a.items():
        if claim not in map_b:
            removed.append(ea)

    return added, removed, modified


def diff_checkpoints(checkpoint_a: Checkpoint, checkpoint_b: Checkpoint) -> str:
    """Computes deterministic work-state diff between Checkpoint A and Checkpoint B."""
    lines = []
    lines.append("[PAC] Work-State Diff")
    lines.append("")
    lines.append("FROM")
    lines.append(f"Project: {checkpoint_a.project.name} | Created: {checkpoint_a.created_at} | Agent: {checkpoint_a.source_agent.name}")
    lines.append("")
    lines.append("TO")
    lines.append(f"Project: {checkpoint_b.project.name} | Created: {checkpoint_b.created_at} | Agent: {checkpoint_b.source_agent.name}")
    lines.append("")

    # OBJECTIVE
    if checkpoint_a.task.objective != checkpoint_b.task.objective:
        lines.append("OBJECTIVE")
        lines.append(f"- FROM: {checkpoint_a.task.objective}")
        lines.append(f"+ TO:   {checkpoint_b.task.objective}")
        lines.append("")

    # STATUS
    if checkpoint_a.task.status != checkpoint_b.task.status:
        lines.append("STATUS")
        lines.append(f"- FROM: {checkpoint_a.task.status}")
        lines.append(f"+ TO:   {checkpoint_b.task.status}")
        lines.append("")

    # COMPLETED
    comp_added, comp_removed = _diff_string_lists(checkpoint_a.completed, checkpoint_b.completed)
    if comp_added or comp_removed:
        lines.append("COMPLETED")
        for item in comp_added:
            lines.append(f"+ {item}")
        for item in comp_removed:
            lines.append(f"- {item}")
        lines.append("")

    # REMAINING
    rem_added, rem_removed = _diff_string_lists(checkpoint_a.remaining, checkpoint_b.remaining)
    if rem_added or rem_removed:
        lines.append("REMAINING")
        for item in rem_added:
            lines.append(f"+ {item}")
        for item in rem_removed:
            lines.append(f"- {item}")
        lines.append("")

    # DECISIONS
    dec_added, dec_removed = _diff_decisions(checkpoint_a.decisions, checkpoint_b.decisions)
    if dec_added or dec_removed:
        lines.append("DECISIONS")
        for d in dec_added:
            lines.append(f"+ {d.decision} (Reason: {d.reason})")
        for d in dec_removed:
            lines.append(f"- {d.decision} (Reason: {d.reason})")
        lines.append("")

    # CONSTRAINTS
    cons_added, cons_removed = _diff_string_lists(checkpoint_a.constraints, checkpoint_b.constraints)
    if cons_added or cons_removed:
        lines.append("CONSTRAINTS")
        for item in cons_added:
            lines.append(f"+ {item}")
        for item in cons_removed:
            lines.append(f"- {item}")
        lines.append("")

    # CHANGED FILES
    files_added, files_removed = _diff_string_lists(checkpoint_a.changed_files, checkpoint_b.changed_files)
    if files_added or files_removed:
        lines.append("CHANGED FILES")
        for item in files_added:
            lines.append(f"+ {item}")
        for item in files_removed:
            lines.append(f"- {item}")
        lines.append("")

    # NEXT ACTION
    if checkpoint_a.next_action != checkpoint_b.next_action:
        lines.append("NEXT ACTION")
        lines.append(f"FROM: {checkpoint_a.next_action}")
        lines.append(f"TO:   {checkpoint_b.next_action}")
        lines.append("")

    # EVIDENCE
    ev_added, ev_removed, ev_modified = _diff_evidence(checkpoint_a.evidence, checkpoint_b.evidence)
    if ev_added or ev_removed or ev_modified:
        lines.append("EVIDENCE")
        for e in ev_added:
            lines.append(f"+ {e.status}: {e.claim}")
        for e in ev_removed:
            lines.append(f"- {e.status}: {e.claim}")
        for ea, eb in ev_modified:
            lines.append(f"~ [{ea.status} -> {eb.status}] {eb.claim}")
        lines.append("")

    # SOURCE AGENT
    if checkpoint_a.source_agent.name != checkpoint_b.source_agent.name:
        lines.append("SOURCE AGENT")
        lines.append(f"FROM: {checkpoint_a.source_agent.name}")
        lines.append(f"TO:   {checkpoint_b.source_agent.name}")
        lines.append("")

    # GIT STATE
    git_a = f"Commit: {checkpoint_a.project.commit[:8]}, Dirty: {checkpoint_a.project.dirty}"
    git_b = f"Commit: {checkpoint_b.project.commit[:8]}, Dirty: {checkpoint_b.project.dirty}"
    if git_a != git_b:
        lines.append("GIT STATE")
        lines.append(f"FROM: {git_a}")
        lines.append(f"TO:   {git_b}")
        lines.append("")

    if len(lines) == 8:  # Only header blocks (FROM/TO) were added
        lines.append("No work-state changes detected between checkpoints.")

    return "\n".join(lines).strip()


def diff_checkpoint_files(checkpoint_path_a: Path, checkpoint_path_b: Path) -> str:
    """Loads two checkpoint files from disk and returns work-state diff output."""
    cp_a_path = checkpoint_path_a.resolve()
    cp_b_path = checkpoint_path_b.resolve()

    if not cp_a_path.exists():
        raise CheckpointNotFoundError(f"First checkpoint file not found: {cp_a_path}")
    if not cp_b_path.exists():
        raise CheckpointNotFoundError(f"Second checkpoint file not found: {cp_b_path}")

    storage_a = CheckpointStorage(cp_a_path)
    cp_a = storage_a.load()
    cp_a.validate()

    storage_b = CheckpointStorage(cp_b_path)
    cp_b = storage_b.load()
    cp_b.validate()

    return diff_checkpoints(cp_a, cp_b)
