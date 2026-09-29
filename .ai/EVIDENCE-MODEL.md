# Evidence Model Specification

## Core Rule
**PAC must NEVER silently convert an AI agent claim into a verified fact.**

AI agents frequently state assertions such as *"I fixed the bug"* or *"All 50 unit tests pass."* In PAC, an unverified statement from an AI agent is treated strictly as an unconfirmed claim.

## Evidence States

| State | Level of Trust | Plain Language Definition |
| :--- | :--- | :--- |
| `VERIFIED` | High | Directly confirmed by PAC through execution of automated tools, test runners, or deterministic checks (e.g. exit code 0 from `pytest`). |
| `OBSERVED` | Medium-High | Directly observed in environment state without execution output (e.g. Git status shows file exists, git diff shows exact lines added). |
| `AGENT_REPORTED` | Medium-Low | Stated by Agent A in session notes or structured capture input, but NOT independently re-run or checked by PAC. |
| `UNKNOWN` | Low | Claim exists without corroborating source or verifiable tooling in local workspace. |
| `STALE` | Invalidated | Claim was previously `VERIFIED` or `OBSERVED`, but repository state (Git commit or modified files) changed since verification. |

## Claims vs Facts Separation

```text
       [ AI Agent A Statement ]
                   │
                   ▼
       Claim: "84 tests pass"
                   │
         [ PAC Capture Engine ]
                   │
      ┌────────────┴────────────┐
      │ Was command run by PAC? │
      └────────────┬────────────┘
            YES    │    NO
             ┌─────┴─────┐
             ▼           ▼
        [ VERIFIED ]   [ AGENT_REPORTED ]
```

### Example 1: Agent Claim vs Verified Fact
* **Claim**: `"84 tests pass."`
* **Source**: `pytest`
* **Status**: `VERIFIED`
* **Verification Detail**: `PAC executed 'pytest' during verify phase -> Exit Code 0, 84 passed.`

### Example 2: Agent Claim Unverified
* **Claim**: `"Authentication implementation is complete."`
* **Source**: `AI Agent`
* **Status**: `AGENT_REPORTED`
* **Verification Detail**: `Agent reported completion, but no automated test target exists.`

## System-Collected Evidence vs Agent-Provided Information

PAC strictly delineates between what PAC itself observes or runs vs what an agent reports:

* **System-Collected Evidence**: Gathered directly by PAC running local tools (e.g. `git`, test runner CLI). Yields `VERIFIED` or `OBSERVED` states.
* **Agent-Provided Information**: Supplied to PAC via explicit structured inputs (CLI flags, input JSON file, or adapter interface). Yields `AGENT_REPORTED` states until verified. PAC never assumes automatic read access to private agent session/chat logs.

## Types of Collectible Evidence in MVP
In the MVP version, PAC collects evidence through local workspace inspections only:

1. **Git State Evidence**: `git status`, `git rev-parse HEAD`, `git diff --stat`.
2. **File Existence & Integrity**: Verification that declared `changed_files` exist on disk and match stored file hashes.
3. **Test Results**: Execution output and return codes from local test runners (e.g., `pytest`, `npm test`).
4. **Command Exit Codes**: Standard output snippets and exit codes from local tools.

## Evidence State Transition Matrix

| Initial Status | Event | New Status |
| :--- | :--- | :--- |
| `AGENT_REPORTED` | `pac verify` confirms physical existence of referenced file target | `OBSERVED` |
| `AGENT_REPORTED` | `pac verify` successfully runs corresponding test command | `VERIFIED` |
| `VERIFIED` | Git commit changes or modified files detected | `STALE` |
| `OBSERVED` | File referenced in `changed_files` or observation is deleted | `STALE` |
| `AGENT_REPORTED` | `pac verify` runs test command and it fails | `UNKNOWN` (with failure detail) |

## Aggregate Checkpoint Status vs Claim-Level Evidence

These are **two separate concepts** that must never be conflated:

* **Claim-level evidence** — the five-state classification attached to each individual claim: `VERIFIED`, `OBSERVED`, `AGENT_REPORTED`, `UNKNOWN`, `STALE`.
* **Checkpoint-level summary** — a single aggregate status that summarises the overall trust posture of the checkpoint.

### Critical Invariant: Aggregate status must never strengthen claim-level evidence

```
OBSERVED  ≠  VERIFIED
```

File existence alone is observation. It is not proof that a feature is correct, complete, or semantically meaningful.

| Aggregate Status | Condition |
| :--- | :--- |
| `FULLY_VERIFIED` | **All** resolved items are `VERIFIED`; zero `OBSERVED`, `AGENT_REPORTED`, or `UNKNOWN` items remain. |
| `PARTIALLY_VERIFIED` | At least one `VERIFIED` or `OBSERVED` item exists, but weaker evidence is also present. |
| `UNVERIFIED` | No `VERIFIED` or `OBSERVED` evidence exists at all. |
| `STALE` | Workspace state drifted; prior result is invalid regardless of previous status. |

A checkpoint containing only `OBSERVED` evidence (e.g. file existence confirmed) **cannot** produce `FULLY_VERIFIED`. It produces `PARTIALLY_VERIFIED` at most.

