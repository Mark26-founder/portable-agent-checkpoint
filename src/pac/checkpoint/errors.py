"""Exceptions for PAC checkpoint handling."""

class CheckpointError(Exception):
    """Base exception for checkpoint operations."""
    pass


class CheckpointValidationError(CheckpointError):
    """Raised when checkpoint data fails validation."""
    pass


class UnsupportedVersionError(CheckpointError):
    """Raised when checkpoint version is unsupported."""
    pass


class CheckpointNotFoundError(CheckpointError):
    """Raised when a requested checkpoint file is missing."""
    pass
