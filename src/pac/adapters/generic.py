"""Generic/Manual Agent Adapter — PAC S6.

Implements the AgentAdapter interface for any generic JSON-based agent context.

This is the default adapter and the reference implementation for how
the adapter boundary works. It accepts an explicit, structured JSON payload
and normalizes it into PAC's canonical TaskContext-compatible representation.

Input contract (all fields optional except shown):
{
    "agent": {                   // agent identity block
        "name": "my-agent",
        "version": "1.0"         // informational only
    },
    "task": {                    // task description block
        "objective": "...",      // or: goal, description
        "completed": [...],      // or: finished, done, accomplished
        "remaining": [...],      // or: pending, todo, open
        "next_action": "..."     // or: next, next_step
    },
    "decisions": [...],          // list of {decision, reason} objects or strings
    "constraints": [...]         // list of strings
}

Alternative field names (determined aliases in normalizer.py) are accepted.
Unknown fields are silently ignored.
Unknown agent identity falls back to 'unknown'.
"""

import json
from pathlib import Path
from typing import Any, Dict

from pac.adapters.interface import AgentAdapter
from pac.adapters.errors import AdapterInputError
from pac.adapters.normalizer import normalize_adapter_payload


class GenericAdapter(AgentAdapter):
    """Generic/manual adapter: accepts any structured JSON context payload.

    This adapter is the universal entry point for any external agent or
    environment that can produce a structured JSON description of its
    current work state.

    It does NOT:
    - Connect to external APIs
    - Access private agent files or databases
    - Infer state from environment variables, executable names, or paths
    - Access browser sessions or IDE internal state
    """

    @property
    def name(self) -> str:
        return "generic"

    @property
    def version(self) -> str:
        return "1.0"

    def normalize(self, raw_context: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a generic agent JSON context into PAC canonical form.

        Args:
            raw_context: Dict loaded from agent context JSON payload.

        Returns:
            PAC-normalized dict compatible with TaskContext.from_dict().

        Raises:
            AdapterInputError: If raw_context cannot be safely normalized.
        """
        return normalize_adapter_payload(raw_context)

    @classmethod
    def from_file(cls, path: Path) -> "GenericAdapter":
        """Factory: return a GenericAdapter instance (stateless; provided for convenience)."""
        return cls()

    def load_and_normalize(self, path: Path) -> Dict[str, Any]:
        """Load a JSON file from disk and normalize it.

        Performs:
        1. File existence check
        2. JSON decode
        3. Normalization via normalize()

        Args:
            path: Absolute or relative path to the JSON context file.

        Returns:
            Normalized dict compatible with TaskContext.from_dict().

        Raises:
            AdapterInputError: For file-not-found, invalid JSON, or
                               normalization failures.
        """
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise AdapterInputError(f"Agent context file not found: {resolved}")

        try:
            with open(resolved, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as exc:
            raise AdapterInputError(
                f"Agent context file contains invalid JSON: {exc}"
            ) from exc
        except OSError as exc:
            raise AdapterInputError(
                f"Cannot read agent context file: {exc}"
            ) from exc

        return self.normalize(raw)
