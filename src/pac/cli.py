"""PAC Command Line Interface entrypoint."""

import argparse
import sys
from pathlib import Path
from typing import Optional

from pac.capture import capture_checkpoint, TaskContext
from pac.verify import verify_checkpoint
from pac.resume import resume_checkpoint
from pac.diff import diff_checkpoint_files
from pac.checkpoint.errors import CheckpointValidationError, UnsupportedVersionError, CheckpointNotFoundError
from pac.adapters import get_adapter, AdapterInputError


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pac",
        description="Portable Agent Checkpoint (PAC) — Preserve and transfer AI work state across coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available PAC commands")

    # Capture command parser
    capture_parser = subparsers.add_parser("capture", help="Inspect project state and capture a checkpoint")
    capture_parser.add_argument(
        "--context",
        "--input",
        type=str,
        dest="context_path",
        help="Path to structured task context JSON file (default: .ai/task-context.json if exists)",
    )
    capture_parser.add_argument(
        "--out",
        type=str,
        dest="out_path",
        help="Output path for checkpoint JSON (default: .ai/checkpoint.json)",
    )
    capture_parser.add_argument(
        "--task",
        type=str,
        dest="task_override",
        help="Explicit task objective string override",
    )
    capture_parser.add_argument(
        "--next",
        type=str,
        dest="next_override",
        help="Explicit recommended next action string override",
    )
    capture_parser.add_argument(
        "--adapter",
        type=str,
        dest="adapter_name",
        default=None,
        help="Adapter name to use for normalizing agent context (e.g. 'generic'). Requires --agent-context.",
    )
    capture_parser.add_argument(
        "--agent-context",
        type=str,
        dest="agent_context_path",
        default=None,
        help="Path to agent context JSON file for adapter normalization (used with --adapter).",
    )

    # Verify command parser
    verify_parser = subparsers.add_parser("verify", help="Verify claims in a PAC checkpoint against workspace state")
    verify_parser.add_argument(
        "checkpoint_path",
        nargs="?",
        default=".ai/checkpoint.json",
        help="Path to checkpoint JSON file (default: .ai/checkpoint.json)",
    )
    verify_parser.add_argument(
        "--strict",
        action="store_true",
        help="Enforce strict verification mode (fails if any evidence is stale or unverified)",
    )
    verify_parser.add_argument(
        "--update",
        action="store_true",
        help="Update evidence statuses in the checkpoint file on disk",
    )

    # Resume command parser
    resume_parser = subparsers.add_parser("resume", help="Summarize checkpoint state for continuation")
    resume_parser.add_argument(
        "checkpoint_path",
        nargs="?",
        default=".ai/checkpoint.json",
        help="Path to checkpoint JSON file (default: .ai/checkpoint.json)",
    )
    resume_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    # History command parser
    subparsers.add_parser("history", help="List stored checkpoint history")

    # Inspect command parser
    inspect_parser = subparsers.add_parser("inspect", help="Inspect detailed contents of a checkpoint")
    inspect_parser.add_argument(
        "checkpoint",
        nargs="?",
        default=".ai/checkpoint.json",
        help="Path or ID of checkpoint to inspect (default: .ai/checkpoint.json)",
    )

    # Recover command parser
    recover_parser = subparsers.add_parser("recover", help="Recover a stored checkpoint to become active (.ai/checkpoint.json)")
    recover_parser.add_argument(
        "checkpoint",
        help="Path or ID of checkpoint to recover",
    )

    # Diff command parser
    diff_parser = subparsers.add_parser("diff", help="Compare work-state changes between two PAC checkpoints")
    diff_parser.add_argument(
        "checkpoint_a",
        help="Path or ID of first checkpoint (from)",
    )
    diff_parser.add_argument(
        "checkpoint_b",
        help="Path or ID of second checkpoint (to)",
    )

    args = parser.parse_args()

    if not args.command:
        print("PAC (Portable Agent Checkpoint) v0.1.0")
        print("Usage: pac [capture|verify|resume|diff|history|inspect|recover] [options]")
        print("Use 'pac <command> --help' for details.")
        sys.exit(0)


    if args.command == "capture":
        project_root = Path.cwd()

        # ----------------------------------------------------------------
        # S6 Adapter path: --adapter + --agent-context
        # ----------------------------------------------------------------
        adapter_name = getattr(args, "adapter_name", None)
        agent_context_path = getattr(args, "agent_context_path", None)

        if adapter_name and not agent_context_path:
            print(
                "[PAC ERROR] --adapter requires --agent-context <file>.",
                file=sys.stderr,
            )
            sys.exit(1)
        if agent_context_path and not adapter_name:
            # Default to generic if context given without explicit adapter name
            adapter_name = "generic"

        task_context: Optional[TaskContext] = None

        if adapter_name:
            # Adapter-based capture path (S6)
            try:
                adapter = get_adapter(adapter_name)
            except AdapterInputError as err:
                print(f"[PAC ERROR] Invalid adapter: {err}", file=sys.stderr)
                sys.exit(1)

            try:
                normalized = adapter.load_and_normalize(Path(agent_context_path))
                task_context = TaskContext.from_dict(normalized)
            except AdapterInputError as err:
                print(f"[PAC ERROR] Adapter normalization failed: {err}", file=sys.stderr)
                sys.exit(1)
            except CheckpointValidationError as err:
                print(f"[PAC ERROR] Normalized context is invalid: {err}", file=sys.stderr)
                sys.exit(1)
            except Exception as err:
                print(f"[PAC ERROR] Adapter error: {err}", file=sys.stderr)
                sys.exit(1)
        else:
            # ----------------------------------------------------------------
            # Standard S3 capture path (backward-compatible, unchanged)
            # ----------------------------------------------------------------
            context_file: Optional[Path] = None

            if args.context_path:
                context_file = Path(args.context_path)
                if not context_file.exists():
                    print(f"[PAC ERROR] Task context file not found: {args.context_path}", file=sys.stderr)
                    sys.exit(1)
            else:
                default_ctx = project_root / ".ai" / "task-context.json"
                if default_ctx.exists():
                    context_file = default_ctx

            if context_file:
                try:
                    task_context = TaskContext.load_from_file(context_file)
                except CheckpointValidationError as err:
                    print(f"[PAC ERROR] Invalid task context file: {err}", file=sys.stderr)
                    sys.exit(1)
                except Exception as err:
                    print(f"[PAC ERROR] Cannot read task context: {err}", file=sys.stderr)
                    sys.exit(1)

        out_path: Optional[Path] = Path(args.out_path) if args.out_path else None

        try:
            checkpoint, saved_at = capture_checkpoint(
                project_root=project_root,
                task_context=task_context,
                output_path=out_path,
                explicit_task_override=args.task_override,
                explicit_next_override=args.next_override,
            )

            observed_cnt = sum(1 for e in checkpoint.evidence if e.status == "OBSERVED")
            agent_cnt = sum(1 for e in checkpoint.evidence if e.status == "AGENT_REPORTED")
            verified_cnt = sum(1 for e in checkpoint.evidence if e.status == "VERIFIED")

            rel_saved_path = saved_at.relative_to(project_root) if saved_at.is_relative_to(project_root) else saved_at

            print(f"[PAC] Captured checkpoint v{checkpoint.version}")
            print(f"[PAC] Project: {checkpoint.project.name} (Commit: {checkpoint.project.commit[:8]}, Dirty: {checkpoint.project.dirty})")
            print(f"[PAC] Task: {checkpoint.task.objective}")
            print(f"[PAC] Changed files: {len(checkpoint.changed_files)}")
            print(f"[PAC] Evidence captured: {observed_cnt} Observed, {agent_cnt} Agent Reported, {verified_cnt} Verified")
            if adapter_name:
                print(f"[PAC] Adapter: {adapter_name}")
            print(f"[PAC] Saved to {rel_saved_path}")
            sys.exit(0)

        except CheckpointValidationError as err:
            print(f"[PAC ERROR] Cannot create checkpoint: {err}", file=sys.stderr)
            sys.exit(2)
        except Exception as err:
            print(f"[PAC ERROR] Unexpected failure during capture: {err}", file=sys.stderr)
            sys.exit(2)

    elif args.command == "verify":
        cp_path = Path(args.checkpoint_path)

        try:
            res = verify_checkpoint(
                checkpoint_path=cp_path,
                project_root=Path.cwd(),
                update_checkpoint=args.update,
            )

            print(f"[PAC] Verifying checkpoint {cp_path} against working tree...")
            print(f"[PAC] Project: {res.checkpoint.project.name}")
            print(f"[PAC] Checkpoint commit: {res.checkpoint.project.commit[:8]} | Current commit: {res.current_git_commit[:8]}")
            print("\nEvidence:")
            for ev in res.evidence_results:
                status_str = f"[{ev.status}]".ljust(18)
                print(f"  {status_str} {ev.claim}")
                if ev.verification_basis:
                    print(f"                     (Basis: {ev.verification_basis})")

            print(f"\n[PAC] Verification Status: {res.overall_status}")

            if res.is_stale:
                print("[PAC WARNING] Workspace state has drifted or changed since capture.")

            if args.strict and (res.is_stale or res.overall_status != "FULLY_VERIFIED"):
                print("[PAC ERROR] Strict verification failed: unverified or stale claims detected.", file=sys.stderr)
                sys.exit(3)

            sys.exit(0)

        except CheckpointNotFoundError as err:
            print(f"[PAC ERROR] {err}", file=sys.stderr)
            sys.exit(1)
        except CheckpointValidationError as err:
            print(f"[PAC ERROR] Checkpoint validation failed: {err}", file=sys.stderr)
            sys.exit(1)
        except UnsupportedVersionError as err:
            print(f"[PAC ERROR] Unsupported checkpoint version: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as err:
            print(f"[PAC ERROR] Verification failed: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "resume":
        cp_path = Path(args.checkpoint_path)
        try:
            out_str = resume_checkpoint(
                checkpoint_path=cp_path,
                project_root=Path.cwd(),
                output_format=args.format,
                verify=True,
            )
            print(out_str)
            sys.exit(0)
        except CheckpointNotFoundError as err:
            print(f"[PAC ERROR] {err}", file=sys.stderr)
            sys.exit(1)
        except CheckpointValidationError as err:
            print(f"[PAC ERROR] Checkpoint validation failed: {err}", file=sys.stderr)
            sys.exit(1)
        except UnsupportedVersionError as err:
            print(f"[PAC ERROR] Unsupported checkpoint version: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as err:
            print(f"[PAC ERROR] Resume failed: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "history":
        from pac.history import CheckpointHistoryStore, format_history_output
        store = CheckpointHistoryStore(Path.cwd())
        entries = store.list_history()
        print(format_history_output(entries))
        sys.exit(0)

    elif args.command == "inspect":
        from pac.history import inspect_checkpoint
        try:
            out_str = inspect_checkpoint(args.checkpoint, project_root=Path.cwd())
            print(out_str)
            sys.exit(0)
        except CheckpointNotFoundError as err:
            print(f"[PAC ERROR] {err}", file=sys.stderr)
            sys.exit(1)
        except CheckpointValidationError as err:
            print(f"[PAC ERROR] Checkpoint validation failed: {err}", file=sys.stderr)
            sys.exit(1)
        except UnsupportedVersionError as err:
            print(f"[PAC ERROR] Unsupported checkpoint version: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as err:
            print(f"[PAC ERROR] Inspect failed: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "recover":
        from pac.history import CheckpointHistoryStore
        store = CheckpointHistoryStore(Path.cwd())
        try:
            checkpoint, active_path = store.recover(args.checkpoint)
            from pac.history import compute_checkpoint_id
            cp_id = compute_checkpoint_id(checkpoint)
            print(f"[PAC] Successfully recovered checkpoint {cp_id}")
            print(f"[PAC] Active checkpoint is now {active_path}")
            print(f"[PAC] Task: {checkpoint.task.objective}")
            sys.exit(0)
        except CheckpointNotFoundError as err:
            print(f"[PAC ERROR] {err}", file=sys.stderr)
            sys.exit(1)
        except CheckpointValidationError as err:
            print(f"[PAC ERROR] Cannot recover checkpoint: {err}", file=sys.stderr)
            sys.exit(1)
        except UnsupportedVersionError as err:
            print(f"[PAC ERROR] Unsupported checkpoint version: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as err:
            print(f"[PAC ERROR] Recovery failed: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "diff":
        from pac.history import CheckpointHistoryStore
        store = CheckpointHistoryStore(Path.cwd())
        try:
            cp_a_path = store.resolve_checkpoint_path(args.checkpoint_a)
            cp_b_path = store.resolve_checkpoint_path(args.checkpoint_b)
            out_str = diff_checkpoint_files(cp_a_path, cp_b_path)
            print(out_str)
            sys.exit(0)
        except CheckpointNotFoundError as err:
            print(f"[PAC ERROR] {err}", file=sys.stderr)
            sys.exit(1)
        except CheckpointValidationError as err:
            print(f"[PAC ERROR] Checkpoint validation failed: {err}", file=sys.stderr)
            sys.exit(1)
        except UnsupportedVersionError as err:
            print(f"[PAC ERROR] Unsupported checkpoint version: {err}", file=sys.stderr)
            sys.exit(1)
        except Exception as err:
            print(f"[PAC ERROR] Diff failed: {err}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

