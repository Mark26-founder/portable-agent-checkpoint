# CLI Contract Specification

The PAC command-line interface consists of exactly four operations.

```text
pac capture  [--task <str>] [--next <str>] [--out <file>] [--adapter <name>] [--agent-context <file>]
pac verify   [<checkpoint_path>] [--strict] [--update]
pac resume   [<checkpoint_path>] [--format <markdown|json>]
pac diff     <checkpoint_a> <checkpoint_b>
pac history
pac inspect  [<checkpoint>]
pac recover  <checkpoint>
```

---

## 1. `pac capture` (Implemented in S3)

### Purpose
Inspects current repository state (git, changed files, active agent environment) and generates a fresh `.ai/checkpoint.json`.

### Inputs
* Optional CLI arguments: `--context <file>`, `--out <file>`, `--task <str>`, `--next <str>`
* **S6 Adapter Arguments**: `--adapter <name>` (e.g. `generic`), `--agent-context <file>` (path to agent JSON payload)
* Agent-Provided Information: Structured input file (`.ai/task-context.json` or `--context`), CLI flags, or adapter payload. Core PAC does not access private agent session logs automatically.
* Local environment: Git repository state, working tree.

### Output
* Writes formatted JSON checkpoint file (default: `.ai/checkpoint.json`).
* Prints human-readable summary to stdout:
  ```text
  [PAC] Captured checkpoint v1.0
  [PAC] Project: portable-agent-checkpoint (Commit: a1b2c3d4, Dirty: True)
  [PAC] Task: Implement user authentication middleware
  [PAC] Changed files: 2
  [PAC] Evidence captured: 2 Observed, 1 Agent Reported, 0 Verified
  [PAC] Saved to .ai/checkpoint.json
  ```

### Expected Behaviour
1. Queries Git for commit hash, dirty status, and changed files.
2. Integrates provided task context file (`.ai/task-context.json` or `--context`) or CLI overrides.
3. Formats evidence items with appropriate statuses (`OBSERVED`, `AGENT_REPORTED`).
4. Applies synchronous secret redaction filter (`SECURITY.md`).
5. Atomically writes JSON to `.ai/checkpoint.json` using `CheckpointStorage`.

### Failure Behaviour
* Exit Code `1` for invalid task context files or missing input files.
* Exit Code `2` if unable to validate or construct checkpoint payload.

---

## 2. `pac verify` (Implemented in S4)

### Purpose
Validates that claims recorded inside a checkpoint file match the current physical state of the repository and workspace.

### Inputs
* Positional argument: `<checkpoint_path>` (default: `.ai/checkpoint.json`)
* CLI Flag: `--strict` (fails verify with Exit Code 3 if any evidence is stale or unverified)
* CLI Flag: `--update` (updates evidence statuses in the checkpoint file on disk)

### Output
* Updates evidence status flags in memory / returns structured `VerificationResult`.
* Stdout summary:
  ```text
  [PAC] Verifying checkpoint .ai/checkpoint.json against working tree...
  [PAC] Project: portable-agent-checkpoint
  [PAC] Checkpoint commit: a1b2c3d4 | Current commit: a1b2c3d4

  Evidence:
    [OBSERVED]         Git commit matches (a1b2c3d4)
    [VERIFIED]         Referenced file src/auth/jwt.py exists on disk
    [AGENT_REPORTED]   Task completion claim
    [STALE]            Previous working-tree state changed

  [PAC] Verification Status: PARTIALLY_VERIFIED
  ```

### Expected Behaviour
1. Compares saved `project.commit` with current Git HEAD.
2. Checks existence of all listed `changed_files`.
3. Deterministically verifies physical claims (e.g. file existence for completion claims).
4. Marks evidence as `STALE` if workspace has drifted from checkpoint state.
5. Exit Code `0` for successful verification, Exit Code `1` for operational errors (file not found, invalid JSON/schema), Exit Code `3` if strict verification fails (`--strict`).

---

## 3. `pac resume`

### Purpose
Generates a compact continuation prompt intended directly for Agent B or human developer injection.

### Inputs
* Positional argument: `<checkpoint_path>` (default: `.ai/checkpoint.json`)
* CLI Flag: `--format` (`markdown` [default], `json`)

### Output
* Stdout prints compressed continuation Markdown (or JSON package):
  ```markdown
  ## TASK OBJECTIVE
  Implement user authentication middleware

  ## CURRENT STATUS & WORK STATE
  Status: IN_PROGRESS
  Source Agent: antigravity-agent

  ## COMPLETED WORK
  - Defined JWT token verification functions in auth/jwt.py
  - Added user session payload extraction

  ## REMAINING SUB-TASKS
  - Wire auth middleware into router endpoints
  - Add integration test for expired tokens

  ## CONSTRAINTS & DECISIONS
  - Decision: Use PyJWT instead of python-jose (Reason: python-jose is unmaintained)
  - Constraint: Keep authentication purely stateless

  ## VERIFIED EVIDENCE
  - [VERIFIED] JWT token generation unit tests pass (pytest tests/test_jwt.py)
  - [AGENT_REPORTED] Middleware handles missing headers gracefully

  ## RECOMMENDED NEXT ACTION
  Implement header extraction in src/auth/middleware.py and run pytest.
  ```

### Expected Behaviour
1. Reads checkpoint file.
2. Automatically triggers internal verification check.
3. Formats compact summary under 1,000 tokens.
4. If staleness detected, prepends a warning header: `[WARNING: Workspace has changed since this checkpoint was captured]`.

---

## 4. `pac diff`

### Purpose
Displays work-state progression between two checkpoint files.

### Inputs
* Positional arguments: `<checkpoint_a>` `<checkpoint_b>`

### Output
* Prints high-level work-state diff:
  ```text
  [PAC DIFF] Comparing Checkpoint A (2026-09-22 21:00) -> Checkpoint B (2026-09-22 21:38)

  COMPLETED DELTA:
  + Added user session payload extraction

  REMAINING DELTA:
  - Wire auth middleware into router endpoints (In Progress)

  CHANGED FILES DELTA:
  + tests/test_jwt.py

  EVIDENCE DELTA:
  + [VERIFIED] JWT token generation unit tests pass

  NEXT ACTION CHANGED:
  - Old: Write JWT unit tests
  + New: Implement header extraction in src/auth/middleware.py
  ```

### Expected Behaviour
1. Compares `completed`, `remaining`, `changed_files`, `evidence`, and `next_action`.
2. Suppresses irrelevant metadata noise (timestamp differences, source agent string changes) to focus purely on work progression.
