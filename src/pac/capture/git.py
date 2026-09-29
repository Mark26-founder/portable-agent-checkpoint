"""Safe Git repository inspection routines for PAC Capture Engine."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class GitState:
    is_git_repo: bool
    commit: str
    dirty: bool
    changed_files: List[str]
    branch: Optional[str] = None


def _run_git_cmd(args: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """Runs a git command via safe subprocess execution without shell invocation."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (FileNotFoundError, PermissionError, subprocess.SubprocessError):
        # Git executable missing, or subprocess error
        return -1, "", "Git binary not found or execution failed"


def inspect_git_repository(project_root: Path) -> GitState:
    """Inspects Git repository state at project_root cleanly and safely without side-effects."""
    if not project_root.exists() or not project_root.is_dir():
        return GitState(
            is_git_repo=False,
            commit="NONE",
            dirty=False,
            changed_files=[],
        )

    # 1. Check if inside work tree
    code, out, _ = _run_git_cmd(["rev-parse", "--is-inside-work-tree"], cwd=project_root)
    if code != 0 or out.lower() != "true":
        return GitState(
            is_git_repo=False,
            commit="NONE",
            dirty=False,
            changed_files=[],
        )

    # 2. Get current commit hash (40-char SHA)
    code, commit_out, _ = _run_git_cmd(["rev-parse", "HEAD"], cwd=project_root)
    commit = commit_out if (code == 0 and len(commit_out) == 40) else "NONE"

    # 3. Get branch name (optional detail)
    code, branch_out, _ = _run_git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], cwd=project_root)
    branch = branch_out if code == 0 else None

    # 4. Get status --porcelain to collect changed files & dirty status
    code, status_out, _ = _run_git_cmd(["status", "--porcelain", "-uall"], cwd=project_root)
    changed_files: List[str] = []
    dirty = False

    if code == 0 and status_out:
        for line in status_out.splitlines():
            if not line.strip():
                continue
            dirty = True
            # Porcelain status line starts with 2 status chars followed by a space at index 2
            path_part = line[2:].lstrip()
            # Handle renames: 'old_path -> new_path'
            if " -> " in path_part:
                parts = path_part.split(" -> ")
                path_part = parts[-1].strip()

            # Remove quotes if git quoted spaces/special characters
            if path_part.startswith('"') and path_part.endswith('"'):
                path_part = path_part[1:-1]

            # Convert to normalized relative path with forward slashes
            rel_path = Path(path_part).as_posix()
            if rel_path and rel_path not in changed_files:
                changed_files.append(rel_path)

    return GitState(
        is_git_repo=True,
        commit=commit,
        dirty=dirty,
        changed_files=changed_files,
        branch=branch,
    )
