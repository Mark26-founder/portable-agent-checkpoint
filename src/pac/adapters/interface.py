"""Agent Adapter Interface — PAC S6 Interoperability Boundary.

Defines the minimal contract that any agent adapter must satisfy
to translate environment-specific work state into PAC's normalized model.

PAC core never depends on a specific adapter implementation.
The dependency always flows:

    Vendor/Environment Input
            ↓
        Adapter
            ↓
    PAC canonical model (TaskContext)
            ↓
        Checkpoint
            ↓
    Resume / Verify / Diff

Adapters do NOT connect to external APIs, SDKs, or private session databases.
All input must cross the adapter boundary as explicit, structured data.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class AgentAdapter(ABC):
    """Abstract base class for all PAC agent adapters.

    An adapter translates environment-specific agent context (a raw dict
    or JSON payload) into a PAC-normalized dict ready for TaskContext.from_dict().

    Subclasses MUST implement:
        - name (property)
        - version (property)
        - normalize(raw_context)

    Subclasses MUST NOT:
        - Connect to external APIs
        - Read private agent session files or databases
        - Access browser sessions or IDE private state
        - Ingest API keys, tokens, or credentials
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name (e.g. 'generic', 'manual')."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Adapter version string (e.g. '1.0')."""

    @abstractmethod
    def normalize(self, raw_context: Dict[str, Any]) -> Dict[str, Any]:
        """Translate environment-specific context into a PAC-normalized dict.

        The returned dict must be compatible with TaskContext.from_dict().
        Required keys in the returned dict:
            objective   (str)
            status      (str: in_progress|blocked|completed)
            completed   (list[str])
            remaining   (list[str])
            decisions   (list[dict with 'decision' and 'reason'])
            constraints (list[str])
            next_action (str)
            source_agent (dict with 'name' key)

        Missing optional fields should be replaced with safe defaults.
        Unknown agent identity must fall back to 'unknown'.

        Args:
            raw_context: Environment-specific dict payload.

        Returns:
            Normalized dict compatible with TaskContext.from_dict().

        Raises:
            AdapterInputError: If raw_context is structurally invalid or
                               cannot be safely normalized.
        """
