"""Verification Engine for PAC Checkpoints."""

import re
from pathlib import Path
from typing import List, Optional, Tuple

from pac.capture.git import inspect_git_repository
from pac.capture.redact import redact_string
from pac.checkpoint.errors import CheckpointValidationError, CheckpointNotFoundError
from pac.checkpoint.models import Checkpoint, Evidence
from pac.checkpoint.storage import CheckpointStorage
from pac.verify.models import EvidenceVerification, VerificationResult


def _extract_file_path_candidates(text: str) -> List[str]:
    """Extracts candidate relative file path strings from text claims using basic regex."""
    if not text:
        return []
    
    # Match relative file paths like src/foo.py, ./path/to/file.ext, or standalone file.txt, module.py
    pattern = re.compile(r"""(?:\b|\.|\/)([a-zA-Z0-9_\-\.]+(?:\/[a-zA-Z0-9_\-\.]+)*\.[a-zA-Z0-9]+)\b""")
    matches = pattern.findall(text)
    
    candidates = []
    for m in matches:
        clean_p = m.lstrip("./")
        if clean_p and clean_p not in candidates:
            candidates.append(clean_p)
    return candidates


def verify_checkpoint(
    checkpoint_path: Path,
    project_root: Optional[Path] = None,
    update_checkpoint: bool = False,
) -> VerificationResult:
    """Verifies a checkpoint against physical project state.

    Args:
        checkpoint_path: Path to `.ai/checkpoint.json` file.
        project_root: Root directory of the project (defaults to checkpoint's parent folder).
        update_checkpoint: If True, writes updated evidence statuses back to disk safely.

    Returns:
        VerificationResult domain object.
    """
    checkpoint_path = checkpoint_path.resolve()
    if not checkpoint_path.exists():
        raise CheckpointNotFoundError(f"Checkpoint file not found: {checkpoint_path}")

    # 1. Load and validate checkpoint via S2 CheckpointStorage
    storage = CheckpointStorage(checkpoint_path)
    checkpoint = storage.load()
    checkpoint.validate()

    root = project_root.resolve() if project_root else checkpoint_path.parent
    if root.name == ".ai":
        root = root.parent
    if not root.exists():
        root = Path.cwd()

    # 2. Inspect current Git state safely
    git_state = inspect_git_repository(root)

    is_stale = False
    errors: List[str] = []
    verified_items: List[EvidenceVerification] = []

    # 3. Check Git Commit & Dirty state
    commit_match = False
    if git_state.is_git_repo and checkpoint.project.commit != "NONE":
        if git_state.commit == checkpoint.project.commit:
            commit_match = True
        else:
            is_stale = True
            errors.append(
                f"Git commit mismatch: Checkpoint commit '{checkpoint.project.commit[:8]}' != current HEAD '{git_state.commit[:8]}'"
            )
    elif git_state.is_git_repo != (checkpoint.project.commit != "NONE"):
        is_stale = True
        errors.append("Repository Git state status changed since checkpoint capture.")

    # 4. Check changed_files existence on disk
    missing_changed_files: List[str] = []
    existing_changed_files: List[str] = []
    for rel_file in checkpoint.changed_files:
        full_path = root / rel_file
        if full_path.exists() and full_path.is_file():
            existing_changed_files.append(rel_file)
        else:
            missing_changed_files.append(rel_file)

    if missing_changed_files:
        is_stale = True
        errors.append(f"Recorded changed files missing on disk: {', '.join(missing_changed_files)}")

    # 5. Process existing evidence items
    updated_evidence_list: List[Evidence] = []

    for ev in checkpoint.evidence:
        claim_text = redact_string(ev.claim)
        source_text = redact_string(ev.source)
        detail_text = redact_string(ev.detail) if ev.detail else None

        new_status = ev.status
        basis: Optional[str] = None

        # Check staleness override
        if is_stale and ev.status in {"VERIFIED", "OBSERVED"}:
            new_status = "STALE"
            basis = "Workspace Git or changed-file state drifted from capture time."
        elif ev.status == "OBSERVED":
            candidates = _extract_file_path_candidates(claim_text)
            if candidates and not all((root / c).exists() for c in candidates):
                missing = [c for c in candidates if not (root / c).exists()]
                new_status = "STALE"
                is_stale = True
                basis = f"Observed file(s) missing from workspace: {', '.join(missing)}"
            elif "dirty status" in claim_text.lower():
                # Filter out .ai directory files from current dirty check if that was the only change
                actual_changed = [f for f in git_state.changed_files if not f.startswith(".ai/") and not f.startswith(".ai\\")]
                captured_changed = [f for f in checkpoint.changed_files if not f.startswith(".ai/") and not f.startswith(".ai\\")]
                
                is_currently_dirty = len(actual_changed) > 0
                was_dirty = checkpoint.project.dirty if captured_changed else False

                if is_currently_dirty == was_dirty or git_state.dirty == checkpoint.project.dirty:
                    new_status = "OBSERVED"
                    basis = "Current Git dirty state matches capture observation."
                else:
                    new_status = "STALE"
                    is_stale = True
                    basis = "Working tree dirty state changed since capture."

            elif "commit is" in claim_text.lower() or "commit" in claim_text.lower():
                if commit_match:
                    new_status = "OBSERVED"
                    basis = "Git commit SHA verified matching current HEAD."
                else:
                    new_status = "STALE"
                    is_stale = True
                    basis = "Git HEAD SHA moved since capture."
            else:
                new_status = "OBSERVED"
                basis = basis or "Observation preserved."

        elif ev.status == "AGENT_REPORTED":
            # Attempt deterministic verification (e.g. referenced file existence)
            candidates = _extract_file_path_candidates(claim_text)
            if candidates:
                all_exist = all((root / c).exists() for c in candidates)
                if all_exist:
                    # Physical file existence is an OBSERVATION, not semantic proof of feature verification
                    new_status = "OBSERVED"
                    basis = f"Confirmed all referenced files exist on disk: {', '.join(candidates)}"
                else:
                    missing = [c for c in candidates if not (root / c).exists()]
                    new_status = "STALE"
                    basis = f"Referenced file(s) missing from workspace: {', '.join(missing)}"
            else:
                # No deterministic file target -> keep AGENT_REPORTED state strictly
                new_status = "AGENT_REPORTED"
                basis = "Agent claim preserved; no automated tool runner or deterministic check available."



        elif ev.status == "UNKNOWN":
            candidates = _extract_file_path_candidates(claim_text)
            if candidates:
                all_exist = all((root / c).exists() for c in candidates)
                if all_exist:
                    new_status = "OBSERVED"
                    basis = f"Confirmed referenced file existence: {', '.join(candidates)}"
                else:
                    new_status = "STALE"
                    is_stale = True
                    basis = f"Referenced file missing: {', '.join(candidates)}"
            else:
                new_status = "UNKNOWN"
                basis = "Insufficient evidence to classify claim."

        elif ev.status == "VERIFIED":
            candidates = _extract_file_path_candidates(claim_text)
            if candidates and not all((root / c).exists() for c in candidates):
                missing = [c for c in candidates if not (root / c).exists()]
                new_status = "STALE"
                is_stale = True
                basis = f"Verified file(s) missing from workspace: {', '.join(missing)}"
            else:
                new_status = "VERIFIED" if not is_stale else "STALE"
                basis = basis or "Verification claim preserved."


        ev_res = EvidenceVerification(
            claim=claim_text,
            source=source_text,
            status=new_status,
            detail=detail_text,
            verification_basis=basis,
        )
        verified_items.append(ev_res)

        # Update evidence copy for checkpoint model
        updated_evidence_list.append(
            Evidence(
                claim=claim_text,
                source=source_text,
                status=new_status,
                detail=f"{detail_text} (Basis: {basis})" if detail_text and basis else (basis or detail_text),
            )
        )

    # 6. Verify completed tasks deterministically (file existence checks)
    for comp_item in checkpoint.completed:
        comp_text = redact_string(comp_item)
        file_candidates = _extract_file_path_candidates(comp_text)
        if file_candidates:
            existing = [c for c in file_candidates if (root / c).exists()]
            missing = [c for c in file_candidates if not (root / c).exists()]
            if existing and not missing:
                verified_items.append(
                    EvidenceVerification(
                        claim=f"Completed work '{comp_text}' observed on disk",
                        source="file system check",
                        status="OBSERVED" if not is_stale else "STALE",
                        verification_basis=f"Confirmed file existence: {', '.join(existing)}",
                    )
                )
            elif missing:
                is_stale = True
                verified_items.append(
                    EvidenceVerification(
                        claim=f"Completed work '{comp_text}' unconfirmed",
                        source="file system check",
                        status="STALE",
                        verification_basis=f"Referenced files missing: {', '.join(missing)}",
                    )
                )
        else:
            # Completed claim without file candidate or test runner -> preserves AGENT_REPORTED state
            verified_items.append(
                EvidenceVerification(
                    claim=f"Completed work claim '{comp_text}'",
                    source="agent context",
                    status="AGENT_REPORTED",
                    verification_basis="Agent reported completed sub-task; no physical file or tool check available.",
                )
            )


    # 7. Determine overall verification status
    #
    # Aggregate-status invariants (S8 trust model):
    #   FULLY_VERIFIED  — requires at least one VERIFIED item AND no OBSERVED,
    #                     AGENT_REPORTED, or UNKNOWN items remain unresolved.
    #                     File existence alone (OBSERVED) never justifies this.
    #   PARTIALLY_VERIFIED — some deterministic verification exists but weaker
    #                        evidence (OBSERVED, AGENT_REPORTED, UNKNOWN) also
    #                        present, OR only OBSERVED evidence exists.
    #   UNVERIFIED      — no verification or observation evidence at all.
    #   STALE           — workspace state drifted; any prior result is invalid.
    if is_stale:
        overall_status = "STALE"
    else:
        verified_cnt = sum(1 for v in verified_items if v.status == "VERIFIED")
        observed_cnt = sum(1 for v in verified_items if v.status == "OBSERVED")
        agent_cnt = sum(1 for v in verified_items if v.status == "AGENT_REPORTED")
        unknown_cnt = sum(1 for v in verified_items if v.status == "UNKNOWN")

        # FULLY_VERIFIED: only when every resolved item is VERIFIED; no OBSERVED,
        # AGENT_REPORTED, or UNKNOWN claims may remain.
        if verified_cnt > 0 and observed_cnt == 0 and agent_cnt == 0 and unknown_cnt == 0:
            overall_status = "FULLY_VERIFIED"
        elif verified_cnt > 0 or observed_cnt > 0:
            overall_status = "PARTIALLY_VERIFIED"
        else:
            overall_status = "UNVERIFIED"

    # 8. Optionally update checkpoint file on disk cleanly
    if update_checkpoint:
        checkpoint.evidence = updated_evidence_list
        checkpoint.validate()
        storage.save(checkpoint)

    return VerificationResult(
        checkpoint_path=str(checkpoint_path),
        checkpoint=checkpoint,
        current_git_commit=git_state.commit,
        current_git_dirty=git_state.dirty,
        is_git_repo=git_state.is_git_repo,
        is_stale=is_stale,
        overall_status=overall_status,
        evidence_results=verified_items,
        errors=errors,
    )
