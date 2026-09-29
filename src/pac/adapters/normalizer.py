"""Deterministic normalization helpers for the PAC adapter layer.

These functions convert common raw-input field name variants into
PAC's canonical TaskContext-compatible field names using explicit,
deterministic mappings.

No LLMs, embeddings, or semantic similarity are used.
Every mapping is an explicit string-to-string lookup table.
"""

from typing import Any, Dict, List

from pac.adapters.errors import AdapterInputError
from pac.capture.redact import redact_structure

# ---------------------------------------------------------------------------
# Field-name normalization maps
# ---------------------------------------------------------------------------
# PAC canonical name → accepted aliases (all lowercase)
# If a caller uses any of these aliases, the value is mapped to the canonical key.

_COMPLETED_ALIASES = frozenset(
    ["completed", "finished", "done", "accomplished", "resolved"]
)
_REMAINING_ALIASES = frozenset(
    ["remaining", "pending", "todo", "in_progress", "left", "open", "backlog"]
)
_OBJECTIVE_ALIASES = frozenset(
    ["objective", "task", "goal", "description", "title", "what"]
)
_NEXT_ACTION_ALIASES = frozenset(
    ["next_action", "next", "next_step", "action", "recommended_action", "immediate_next"]
)
_DECISIONS_ALIASES = frozenset(
    ["decisions", "design_decisions", "architectural_decisions", "choices"]
)
_CONSTRAINTS_ALIASES = frozenset(
    ["constraints", "rules", "restrictions", "boundaries", "do_not", "off_limits"]
)
_STATUS_ALIASES = frozenset(
    ["status", "state", "progress", "task_status"]
)


def _find_key(data: Dict[str, Any], aliases: frozenset) -> Any:
    """Return the first value whose key (lowercased) appears in aliases.

    Returns None if no matching key found.
    """
    for k, v in data.items():
        if k.lower() in aliases:
            return v
    return None


def _normalize_string_list(raw: Any, field_name: str) -> List[str]:
    """Coerce a raw value into a list of strings.

    Accepts: list[str|int|float], str (single-item), or None.
    Raises AdapterInputError for structurally incompatible types.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        result = []
        for item in raw:
            if isinstance(item, (str, int, float)):
                result.append(str(item))
            elif isinstance(item, dict):
                # Gracefully convert dict items to a string representation
                # using the most descriptive key available
                for key in ("description", "text", "title", "name", "value"):
                    if key in item and isinstance(item[key], str) and item[key].strip():
                        result.append(item[key])
                        break
        return result
    raise AdapterInputError(
        f"Field '{field_name}' must be a list of strings or a string; got {type(raw).__name__}"
    )


def _normalize_status(raw: Any) -> str:
    """Map any task-status alias to a PAC-canonical status string.

    Returns 'in_progress' for unknown/missing values (safe default).
    """
    if not isinstance(raw, str):
        return "in_progress"
    mapping = {
        "in_progress": "in_progress",
        "inprogress": "in_progress",
        "in progress": "in_progress",
        "active": "in_progress",
        "working": "in_progress",
        "blocked": "blocked",
        "stalled": "blocked",
        "waiting": "blocked",
        "completed": "completed",
        "complete": "completed",
        "done": "completed",
        "finished": "completed",
    }
    return mapping.get(raw.lower().strip(), "in_progress")


def _normalize_decisions(raw: Any, field_name: str = "decisions") -> List[Dict[str, str]]:
    """Normalize a decisions list to PAC canonical form: [{decision, reason}].

    Accepts common alternative formats:
    - {"decision": "...", "reason": "..."}   (canonical)
    - {"decision": "...", "rationale": "..."}
    - {"what": "...", "why": "..."}
    - {"choice": "...", "reason": "..."}
    - plain strings — decision text with no reason (reason defaults to 'Not recorded')
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AdapterInputError(
            f"Field '{field_name}' must be a list; got {type(raw).__name__}"
        )

    result = []
    _REASON_KEYS = ["reason", "rationale", "why", "because", "justification", "explanation"]
    _DECISION_KEYS = ["decision", "what", "choice", "action", "item", "text"]

    for item in raw:
        if isinstance(item, str) and item.strip():
            result.append({"decision": item.strip(), "reason": "Not recorded"})
        elif isinstance(item, dict):
            dec_text = ""
            for k in _DECISION_KEYS:
                if k in item and isinstance(item[k], str) and item[k].strip():
                    dec_text = item[k].strip()
                    break
            reason_text = "Not recorded"
            for k in _REASON_KEYS:
                if k in item and isinstance(item[k], str) and item[k].strip():
                    reason_text = item[k].strip()
                    break
            if dec_text:
                result.append({"decision": dec_text, "reason": reason_text})
    return result


def _normalize_agent_identity(raw: Any) -> str:
    """Extract agent name from raw source_agent payload.

    Accepts:
    - str: used directly
    - dict with 'name' key
    - dict with 'agent' key
    - None or missing: falls back to 'unknown'

    Unknown identity is always explicitly 'unknown', never inferred.
    """
    if raw is None:
        return "unknown"
    if isinstance(raw, str):
        stripped = raw.strip()
        return stripped if stripped else "unknown"
    if isinstance(raw, dict):
        for key in ("name", "agent", "id", "identifier"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return "unknown"


def normalize_adapter_payload(raw_context: Dict[str, Any]) -> Dict[str, Any]:
    """Top-level normalization: translate a raw adapter payload into PAC canonical form.

    The returned dict is compatible with TaskContext.from_dict().

    This function handles:
    1. Field-name aliasing (e.g. 'finished' → 'completed')
    2. Nested agent identity extraction
    3. Status normalization
    4. Decision format normalization
    5. Constraint / remaining / completed list coercion
    6. Secret redaction on all string values

    Returns a dict with keys:
        objective, status, completed, remaining, decisions, constraints,
        next_action, source_agent

    Raises:
        AdapterInputError: if top-level input is not a dict, or a required
                           sub-field is structurally invalid.
    """
    if not isinstance(raw_context, dict):
        raise AdapterInputError(
            f"Adapter context must be a JSON object (dict); got {type(raw_context).__name__}"
        )

    # -- Agent identity --
    # Try top-level 'agent' block first (generic adapter format),
    # then 'source_agent' (PAC native format), then top-level string fields.
    agent_raw = raw_context.get("agent") or raw_context.get("source_agent")
    agent_name = _normalize_agent_identity(agent_raw)

    # -- Task / objective --
    task_raw = raw_context.get("task", {})
    if isinstance(task_raw, dict):
        # Nested task block (generic adapter format)
        objective_raw = (
            task_raw.get("objective")
            or task_raw.get("goal")
            or task_raw.get("description")
            or _find_key(raw_context, _OBJECTIVE_ALIASES)
            or "Unspecified development task"
        )
        status_raw = task_raw.get("status") or _find_key(raw_context, _STATUS_ALIASES)
        completed_raw = (
            _find_key(task_raw, _COMPLETED_ALIASES)
            or _find_key(raw_context, _COMPLETED_ALIASES)
        )
        remaining_raw = (
            _find_key(task_raw, _REMAINING_ALIASES)
            or _find_key(raw_context, _REMAINING_ALIASES)
        )
        next_action_raw = (
            task_raw.get("next_action")
            or task_raw.get("next")
            or task_raw.get("next_step")
            or _find_key(raw_context, _NEXT_ACTION_ALIASES)
            or "Continue task implementation."
        )
    elif isinstance(task_raw, str) and task_raw.strip():
        # Task is a plain string — treat as objective
        objective_raw = task_raw
        status_raw = _find_key(raw_context, _STATUS_ALIASES)
        completed_raw = _find_key(raw_context, _COMPLETED_ALIASES)
        remaining_raw = _find_key(raw_context, _REMAINING_ALIASES)
        next_action_raw = _find_key(raw_context, _NEXT_ACTION_ALIASES) or "Continue task implementation."
    else:
        # No task block — scan top-level keys with aliases
        objective_raw = _find_key(raw_context, _OBJECTIVE_ALIASES) or "Unspecified development task"
        status_raw = _find_key(raw_context, _STATUS_ALIASES)
        completed_raw = _find_key(raw_context, _COMPLETED_ALIASES)
        remaining_raw = _find_key(raw_context, _REMAINING_ALIASES)
        next_action_raw = _find_key(raw_context, _NEXT_ACTION_ALIASES) or "Continue task implementation."

    # -- Decisions & Constraints --
    decisions_raw = (
        _find_key(raw_context, _DECISIONS_ALIASES)
        or (
            _find_key(task_raw, _DECISIONS_ALIASES)
            if isinstance(task_raw, dict)
            else None
        )
    )
    constraints_raw = (
        _find_key(raw_context, _CONSTRAINTS_ALIASES)
        or (
            _find_key(task_raw, _CONSTRAINTS_ALIASES)
            if isinstance(task_raw, dict)
            else None
        )
    )

    # -- Validate / coerce types --
    objective = str(objective_raw).strip() if objective_raw else "Unspecified development task"
    status = _normalize_status(status_raw)
    completed = _normalize_string_list(completed_raw, "completed")
    remaining = _normalize_string_list(remaining_raw, "remaining")
    decisions = _normalize_decisions(decisions_raw)
    constraints = _normalize_string_list(constraints_raw, "constraints")
    next_action = str(next_action_raw).strip() if next_action_raw else "Continue task implementation."

    # -- Assemble canonical payload --
    normalized: Dict[str, Any] = {
        "objective": objective,
        "status": status,
        "completed": completed,
        "remaining": remaining,
        "decisions": decisions,
        "constraints": constraints,
        "next_action": next_action,
        "source_agent": {"name": agent_name},
    }

    # -- Security: redact secrets from all string values --
    normalized = redact_structure(normalized)

    return normalized
