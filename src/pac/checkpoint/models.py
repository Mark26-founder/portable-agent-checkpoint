"""PAC Dataclasses and JSON Serialization Model."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any

from pac.checkpoint.errors import CheckpointValidationError, UnsupportedVersionError

SUPPORTED_VERSION = "1.0"

ALLOWED_TASK_STATUSES = {"in_progress", "blocked", "completed"}
ALLOWED_EVIDENCE_STATUSES = {"VERIFIED", "OBSERVED", "AGENT_REPORTED", "UNKNOWN", "STALE"}


@dataclass
class ProjectInfo:
    name: str
    commit: str
    dirty: bool

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise CheckpointValidationError("project.name must be a non-empty string")
        if not isinstance(self.commit, str) or not self.commit.strip():
            raise CheckpointValidationError("project.commit must be a non-empty string")
        if not isinstance(self.dirty, bool):
            raise CheckpointValidationError("project.dirty must be a boolean")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectInfo":
        if not isinstance(data, dict):
            raise CheckpointValidationError("project field must be an object")
        return cls(
            name=data.get("name", ""),
            commit=data.get("commit", ""),
            dirty=data.get("dirty", False),
        )


@dataclass
class TaskInfo:
    objective: str
    status: str

    def validate(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise CheckpointValidationError("task.objective must be a non-empty string")
        if self.status not in ALLOWED_TASK_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_TASK_STATUSES))
            raise CheckpointValidationError(
                f"task.status must be one of: {allowed} (got '{self.status}')"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskInfo":
        if not isinstance(data, dict):
            raise CheckpointValidationError("task field must be an object")
        return cls(
            objective=data.get("objective", ""),
            status=data.get("status", ""),
        )


@dataclass
class Decision:
    decision: str
    reason: str

    def validate(self) -> None:
        if not isinstance(self.decision, str) or not self.decision.strip():
            raise CheckpointValidationError("decisions[].decision must be a non-empty string")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise CheckpointValidationError("decisions[].reason must be a non-empty string")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Decision":
        if not isinstance(data, dict):
            raise CheckpointValidationError("decisions item must be an object")
        return cls(
            decision=data.get("decision", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class Evidence:
    claim: str
    source: str
    status: str
    detail: Optional[str] = None

    def validate(self) -> None:
        if not isinstance(self.claim, str) or not self.claim.strip():
            raise CheckpointValidationError("evidence[].claim must be a non-empty string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise CheckpointValidationError("evidence[].source must be a non-empty string")
        if self.status not in ALLOWED_EVIDENCE_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_EVIDENCE_STATUSES))
            raise CheckpointValidationError(
                f"evidence[].status must be one of: {allowed} (got '{self.status}')"
            )
        if self.detail is not None and not isinstance(self.detail, str):
            raise CheckpointValidationError("evidence[].detail must be a string if provided")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        if not isinstance(data, dict):
            raise CheckpointValidationError("evidence item must be an object")
        return cls(
            claim=data.get("claim", ""),
            source=data.get("source", ""),
            status=data.get("status", ""),
            detail=data.get("detail"),
        )


@dataclass
class SourceAgent:
    name: str

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise CheckpointValidationError("source_agent.name must be a non-empty string")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceAgent":
        if not isinstance(data, dict):
            raise CheckpointValidationError("source_agent field must be an object")
        return cls(
            name=data.get("name", ""),
        )


@dataclass
class Checkpoint:
    version: str
    project: ProjectInfo
    task: TaskInfo
    completed: List[str]
    remaining: List[str]
    changed_files: List[str]
    next_action: str
    evidence: List[Evidence]
    source_agent: SourceAgent
    created_at: str
    decisions: List[Decision] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validates all checkpoint attributes strictly against S1 schema."""
        if not isinstance(self.version, str):
            raise CheckpointValidationError("version must be a string")
        if self.version != SUPPORTED_VERSION:
            raise UnsupportedVersionError(
                f"Unsupported checkpoint version '{self.version}'. Supported: '{SUPPORTED_VERSION}'"
            )

        if not isinstance(self.project, ProjectInfo):
            raise CheckpointValidationError("project must be a ProjectInfo instance")
        self.project.validate()

        if not isinstance(self.task, TaskInfo):
            raise CheckpointValidationError("task must be a TaskInfo instance")
        self.task.validate()

        if not isinstance(self.completed, list) or not all(isinstance(x, str) for x in self.completed):
            raise CheckpointValidationError("completed must be a list of strings")

        if not isinstance(self.remaining, list) or not all(isinstance(x, str) for x in self.remaining):
            raise CheckpointValidationError("remaining must be a list of strings")

        if not isinstance(self.changed_files, list) or not all(isinstance(x, str) for x in self.changed_files):
            raise CheckpointValidationError("changed_files must be a list of strings")

        if not isinstance(self.next_action, str) or not self.next_action.strip():
            raise CheckpointValidationError("next_action must be a non-empty string")

        if not isinstance(self.evidence, list):
            raise CheckpointValidationError("evidence must be a list")
        for ev in self.evidence:
            if not isinstance(ev, Evidence):
                raise CheckpointValidationError("evidence item must be an Evidence instance")
            ev.validate()

        if not isinstance(self.source_agent, SourceAgent):
            raise CheckpointValidationError("source_agent must be a SourceAgent instance")
        self.source_agent.validate()

        if not isinstance(self.created_at, str):
            raise CheckpointValidationError("created_at must be an ISO-8601 string")
        self._validate_timestamp(self.created_at)

        if not isinstance(self.decisions, list):
            raise CheckpointValidationError("decisions must be a list")
        for d in self.decisions:
            if not isinstance(d, Decision):
                raise CheckpointValidationError("decisions item must be a Decision instance")
            d.validate()

        if not isinstance(self.constraints, list) or not all(isinstance(x, str) for x in self.constraints):
            raise CheckpointValidationError("constraints must be a list of strings")

    @staticmethod
    def _validate_timestamp(ts: str) -> None:
        try:
            # Parse ISO-8601 timestamp string
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            datetime.fromisoformat(ts)
        except Exception:
            raise CheckpointValidationError(f"created_at is not a valid ISO-8601 timestamp: '{ts}'")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes model to a JSON-compatible dictionary."""
        self.validate()
        d = asdict(self)
        # Filter optional detail if None
        for ev in d["evidence"]:
            if ev["detail"] is None:
                del ev["detail"]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        """Deserializes a dictionary into a validated Checkpoint object."""
        if not isinstance(data, dict):
            raise CheckpointValidationError("Checkpoint data must be a JSON object")

        version = data.get("version")
        if version != SUPPORTED_VERSION:
            raise UnsupportedVersionError(
                f"Unsupported checkpoint version '{version}'. Supported: '{SUPPORTED_VERSION}'"
            )

        project = ProjectInfo.from_dict(data.get("project", {}))
        task = TaskInfo.from_dict(data.get("task", {}))
        
        completed = data.get("completed")
        if not isinstance(completed, list):
            raise CheckpointValidationError("completed field must be a list")

        remaining = data.get("remaining")
        if not isinstance(remaining, list):
            raise CheckpointValidationError("remaining field must be a list")

        changed_files = data.get("changed_files")
        if not isinstance(changed_files, list):
            raise CheckpointValidationError("changed_files field must be a list")

        next_action = data.get("next_action", "")
        
        evidence_raw = data.get("evidence")
        if not isinstance(evidence_raw, list):
            raise CheckpointValidationError("evidence field must be a list")
        evidence = [Evidence.from_dict(e) for e in evidence_raw]

        source_agent = SourceAgent.from_dict(data.get("source_agent", {}))
        created_at = data.get("created_at", "")

        decisions_raw = data.get("decisions", [])
        if not isinstance(decisions_raw, list):
            raise CheckpointValidationError("decisions field must be a list")
        decisions = [Decision.from_dict(d) for d in decisions_raw]

        constraints = data.get("constraints", [])
        if not isinstance(constraints, list):
            raise CheckpointValidationError("constraints field must be a list")

        checkpoint = cls(
            version=version,
            project=project,
            task=task,
            completed=completed,
            remaining=remaining,
            changed_files=changed_files,
            next_action=next_action,
            evidence=evidence,
            source_agent=source_agent,
            created_at=created_at,
            decisions=decisions,
            constraints=constraints,
        )
        checkpoint.validate()
        return checkpoint
