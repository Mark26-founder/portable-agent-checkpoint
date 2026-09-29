# Checkpoint Schema Specification

Version: `1.0.0`

The PAC checkpoint schema defines the minimal JSON structure needed to transfer work state between agents.

## Schema Principles
Every field in the schema must pass the test: **"Does this materially help another agent continue the work?"** Any metadata that does not directly inform the next agent's immediate actions or safety boundaries is excluded.

## Schema Fields Definition

| Field Name | Type | Required / Optional | Allowed Values / Format | Meaning |
| :--- | :--- | :--- | :--- | :--- |
| `version` | string | **Required** | SemVer string (e.g. `"1.0"`) | Version of the PAC checkpoint schema. |
| `project` | object | **Required** | Object | Basic identifier of the workspace repository. |
| `project.name` | string | **Required** | Free text | Name of the project. |
| `project.commit` | string | **Required** | 40-char SHA string or `"NONE"` | Git commit hash at capture time. |
| `project.dirty` | boolean | **Required** | `true`, `false` | True if uncommitted changes exist in working tree. |
| `task` | object | **Required** | Object | Contextual goal of the active task. |
| `task.objective` | string | **Required** | Free text | High-level objective the agent is accomplishing. |
| `task.status` | string | **Required** | `"in_progress"`, `"blocked"`, `"completed"` | Current macro state of the task. |
| `completed` | array[string] | **Required** | List of strings | Concrete sub-tasks finished during session. |
| `remaining` | array[string] | **Required** | List of strings | Concrete sub-tasks yet to be completed. |
| `decisions` | array[object] | **Optional** | List of Decision objects | Major architectural or design decisions made. |
| `decisions[].decision` | string | **Required** | Free text | What was decided. |
| `decisions[].reason` | string | **Required** | Free text | Why it was decided. |
| `constraints` | array[string] | **Optional** | List of strings | Explicit boundaries (e.g., "Do not edit X file"). |
| `changed_files` | array[string] | **Required** | List of relative file paths | Files touched or created during the session. |
| `next_action` | string | **Required** | Free text | The exact single next action recommended for Agent B. |
| `evidence` | array[object] | **Required** | List of Evidence objects | Claims paired with verification states & proof. |
| `evidence[].claim` | string | **Required** | Free text | Statement made (e.g. "84 tests pass"). |
| `evidence[].source` | string | **Required** | Free text (e.g. `"pytest"`, `"agent"`, `"git"`) | Tool or agent that produced the statement. |
| `evidence[].status` | string | **Required** | `"VERIFIED"`, `"OBSERVED"`, `"AGENT_REPORTED"`, `"UNKNOWN"`, `"STALE"` | Ground-truth verification state. |
| `evidence[].detail` | string | **Optional** | Free text / snippet summary | Command output snippet or path proving claim. |
| `source_agent` | object | **Required** | Object | Metadata regarding Agent A. |
| `source_agent.name` | string | **Required** | Free text (e.g. `"cursor"`, `"claude-code"`) | Identifier of Agent A framework/model. |
| `created_at` | string | **Required** | ISO-8601 UTC string | Timestamp when checkpoint was generated. |

## Removed / Excluded Fields & Rationale
* **`errors`**: Merged into `evidence` array with `AGENT_REPORTED` or `OBSERVED` status to avoid redundant error tracking collections.
* **`tests`**: Merged into `evidence` array under explicit test execution claims.
* **Full conversation transcripts**: Excluded due to context explosion; PAC compresses state.

## Complete Example Checkpoint (`.ai/checkpoint.json`)

```json
{
  "version": "1.0",
  "project": {
    "name": "portable-agent-checkpoint",
    "commit": "a1b2c3d4e5f678901234567890abcdef12345678",
    "dirty": true
  },
  "task": {
    "objective": "Implement user authentication middleware",
    "status": "in_progress"
  },
  "completed": [
    "Defined JWT token verification functions in auth/jwt.py",
    "Added user session payload extraction"
  ],
  "remaining": [
    "Wire auth middleware into router endpoints",
    "Add integration test for expired tokens"
  ],
  "decisions": [
    {
      "decision": "Use PyJWT instead of python-jose",
      "reason": "python-jose is unmaintained and has known security vulnerabilities."
    }
  ],
  "constraints": [
    "Do not change existing endpoint signature for /api/v1/status",
    "Keep authentication purely stateless"
  ],
  "changed_files": [
    "src/auth/jwt.py",
    "tests/test_jwt.py"
  ],
  "next_action": "Implement header extraction in src/auth/middleware.py and run pytest.",
  "evidence": [
    {
      "claim": "JWT token generation unit tests pass",
      "source": "pytest tests/test_jwt.py",
      "status": "VERIFIED",
      "detail": "8 passed in 0.42s"
    },
    {
      "claim": "Middleware handles missing headers gracefully",
      "source": "AI agent",
      "status": "AGENT_REPORTED",
      "detail": "Drafted logic in conversation but test file not yet executed"
    }
  ],
  "source_agent": {
    "name": "antigravity-agent"
  },
  "created_at": "2026-09-22T21:38:00Z"
}
```
