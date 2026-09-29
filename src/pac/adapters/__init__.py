"""PAC Adapters sub-package — S6 Agent/Environment Interoperability.

Exports the adapter interface, the GenericAdapter, error types,
and a registry of all built-in adapters.

PAC core (capture, verify, resume, diff) does NOT depend on this package.
The dependency flows:

    Adapter → PAC core (TaskContext, Checkpoint)

Never:

    PAC core → Adapter
"""

from pac.adapters.interface import AgentAdapter
from pac.adapters.generic import GenericAdapter
from pac.adapters.errors import AdapterError, AdapterInputError
from pac.adapters.normalizer import normalize_adapter_payload

# Built-in adapter registry: maps adapter names to their classes.
# Future vendor-specific adapters can be added here without touching PAC core.
ADAPTER_REGISTRY: dict = {
    "generic": GenericAdapter,
}


def get_adapter(name: str) -> AgentAdapter:
    """Return an instantiated adapter by name.

    Args:
        name: Adapter name string (e.g. 'generic').

    Returns:
        An instantiated AgentAdapter.

    Raises:
        AdapterInputError: If the named adapter is not registered.
    """
    cls = ADAPTER_REGISTRY.get(name.lower().strip())
    if cls is None:
        available = ", ".join(sorted(ADAPTER_REGISTRY.keys()))
        raise AdapterInputError(
            f"Unknown adapter '{name}'. Available adapters: {available}"
        )
    return cls()


__all__ = [
    "AgentAdapter",
    "GenericAdapter",
    "AdapterError",
    "AdapterInputError",
    "normalize_adapter_payload",
    "ADAPTER_REGISTRY",
    "get_adapter",
]
