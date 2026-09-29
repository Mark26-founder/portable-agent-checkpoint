# Architecture & System Design Specification

## System Overview
PAC is built around a decoupled pipeline. The core engine is vendor-neutral and relies strictly on generic structured inputs and workspace inspections. Adapters sit on the outer edge to translate environment-specific agent context into PAC's normalized model. PAC core never depends on any adapter.

```
Vendor/Environment Input (explicit JSON payload)
        |
        v
  Adapter Layer (S6) -- pac.adapters
  GenericAdapter + Normalizer (field-name aliasing, status mapping, secret redaction)
        |
        v  (PAC TaskContext -- normalized)
  Capture Engine (S3)
        |
        v
  Checkpoint Core <-- Redaction Engine
        |
        +-------------------+
        v                   v
  Verifier Engine     Resume Engine
        |                   |
        v                   v
  Evidence Status     Compact Continuation
  (VERIFIED/STALE)    Markdown Output
```

---

## Core Component Responsibilities

### 1. `adapters` (Adapter Layer — Implemented in S6)
* **Input**: Explicit structured JSON payload from an external agent environment.
* **Process**: Translates field-name aliases, normalizes status/decisions/identity, applies secret redaction, returns PAC-canonical dict.
* **Output**: `TaskContext`-compatible dict, passed to the Capture Engine.
* **Boundary Rule**: PAC core (capture, verify, resume, diff) NEVER imports from `pac.adapters`. The dependency flows one way: `Adapter → PAC core`.

### 2. `capture` (Capture Pipeline)
* **Input**: Git status output, CLI flags, optional adapter JSON (via `--adapter`/`--agent-context`), or legacy `task-context.json`.
* **Process**: Collects Git working tree diffs, applies the security redaction filter, normalizes tasks/decisions.
* **Output**: Instantiates and saves `Checkpoint` domain model.

### 3. `normalizer` (Normalizer Engine)
* Converts raw agent statements, CLI inputs, or adapter payloads into standard schema fields (`completed`, `remaining`, `decisions`, `constraints`).
* Enforces strict type boundaries and validates schema constraints.

### 4. `verifier` (Verification Engine — Implemented in S4)
* **Input**: Checkpoint JSON file (`.ai/checkpoint.json`), physical workspace root path.
* **Process**:
  - Compares saved `project.commit` vs `git rev-parse HEAD`.
  - Checks existence and integrity of all recorded `changed_files` on disk.
  - Deterministically evaluates completed tasks and claims against workspace evidence (e.g. file existence).
  - Re-evaluates evidence states, marking items as `VERIFIED`, `OBSERVED`, `AGENT_REPORTED`, or `STALE`.
* **Output**: Returns `VerificationResult` domain object and outputs human-readable console report.

### 5. `resume` (Context Compression Engine)
* Reads verified `Checkpoint` object.
* Transforms object into a deterministic, context-compressed Markdown string (<1,000 tokens).
* Resume output is **vendor-neutral** — no language specific to any AI agent brand.

### 6. `diff` (Work State Comparison)
* Computes semantic deltas between two `Checkpoint` instances focusing strictly on work progression (`completed`, `remaining`, `changed_files`, `next_action`).

### 7. `history` (History & Storage Lifecycle Layer — Implemented in S7)
* **Input**: Stored checkpoints in `.ai/checkpoints/` directory.
* **Process**:
  - Archives captured checkpoints using deterministic SHA-256 ID formula.
  - Lists historical checkpoints ordered deterministically by timestamp.
  - Inspects checkpoint details without modifying workspace or state.
  - Recovers AI work state atomically by writing to active `.ai/checkpoint.json` without modifying Git or source code files.


---

## Component Boundaries & Neutrality
* **Vendor Independence**: Core PAC logic imports zero agent-specific SDKs (no OpenAI, Anthropic, Cursor, or LangChain dependencies). The adapter layer also imports no external SDKs.
* **Storage Abstraction**: All operations write/read plain JSON from `.ai/checkpoint.json` using standard library primitives.
* **Extensibility**: Future vendor-specific adapters add a class to `ADAPTER_REGISTRY` in `pac/adapters/__init__.py` without modifying PAC core.
