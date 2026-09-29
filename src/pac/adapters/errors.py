"""Adapter-specific error types for PAC S6."""


class AdapterError(Exception):
    """Base exception for all adapter failures."""


class AdapterInputError(AdapterError):
    """Raised when an adapter receives structurally invalid or unacceptable input.

    This is the clean error surface for the adapter boundary.
    Callers can catch this to produce user-facing error messages
    without catching all exceptions.
    """
