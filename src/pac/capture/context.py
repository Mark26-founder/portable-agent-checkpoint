"""Task context parser and loader for PAC Capture Engine."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

from pac.checkpoint.errors import CheckpointValidationError


@dataclass
class TaskContextDecision:
    decision: str
    reason: str


@dataclass
class TaskContext:
    objective: str = "Unspecified development task"
    status: str = "in_progress"
    completed: List[str] = field(default_factory=list)
    remaining: List[str] = field(default_factory=list)
    decisions: List[TaskContextDecision] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    next_action: str = "Continue task implementation."
    source_agent_name: str = "unknown"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskContext":
        if not isinstance(data, dict):
            raise CheckpointValidationError("Task context JSON content must be an object")

        objective = data.get("objective", "Unspecified development task")
        if not isinstance(objective, str) or not objective.strip():
            objective = "Unspecified development task"

        status = data.get("status", "in_progress")
        if status not in {"in_progress", "blocked", "completed"}:
            status = "in_progress"

        completed_raw = data.get("completed", [])
        if not isinstance(completed_raw, list):
            raise CheckpointValidationError("Task context 'completed' field must be a list of strings")
        completed = [str(x) for x in completed_raw if isinstance(x, (str, int, float))]

        remaining_raw = data.get("remaining", [])
        if not isinstance(remaining_raw, list):
            raise CheckpointValidationError("Task context 'remaining' field must be a list of strings")
        remaining = [str(x) for x in remaining_raw if isinstance(x, (str, int, float))]

        decisions_raw = data.get("decisions", [])
        if not isinstance(decisions_raw, list):
            raise CheckpointValidationError("Task context 'decisions' field must be a list of objects")
        decisions = []
        for d in decisions_raw:
            if isinstance(d, dict):
                dec_text = str(d.get("decision", "")).strip()
                reason_text = str(d.get("reason", "")).strip()
                if dec_text and reason_text:
                    decisions.append(TaskContextDecision(decision=dec_text, reason=reason_text))

        constraints_raw = data.get("constraints", [])
        if not isinstance(constraints_raw, list):
            raise CheckpointValidationError("Task context 'constraints' field must be a list of strings")
        constraints = [str(x) for x in constraints_raw if isinstance(x, (str, int, float))]

        next_action = data.get("next_action", "Continue task implementation.")
        if not isinstance(next_action, str) or not next_action.strip():
            next_action = "Continue task implementation."

        source_agent_raw = data.get("source_agent", {})
        source_agent_name = "unknown"
        if isinstance(source_agent_raw, dict):
            source_agent_name = str(source_agent_raw.get("name", "unknown")).strip() or "unknown"
        elif isinstance(source_agent_raw, str) and source_agent_raw.strip():
            source_agent_name = source_agent_raw.strip()

        return cls(
            objective=objective,
            status=status,
            completed=completed,
            remaining=remaining,
            decisions=decisions,
            constraints=constraints,
            next_action=next_action,
            source_agent_name=source_agent_name,
        )

    @classmethod
    def load_from_file(cls, path: Path) -> "TaskContext":
        """Loads and parses task context from a JSON file."""
        if not path.exists():
            raise FileNotFoundError(f"Task context file not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as err:
            raise CheckpointValidationError(f"Task context file contains invalid JSON: {err}") from err
        except Exception as err:
            raise CheckpointValidationError(f"Failed to read task context file: {err}") from err

        return cls.from_dict(data)
