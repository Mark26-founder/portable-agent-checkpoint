"""Local storage layer for PAC checkpoint files."""

import json
from pathlib import Path
from typing import Union

from pac.checkpoint.models import Checkpoint
from pac.checkpoint.errors import CheckpointNotFoundError, CheckpointValidationError

DEFAULT_CHECKPOINT_PATH = Path(".ai") / "checkpoint.json"


class CheckpointStorage:
    """Handles saving, loading, and directory creation for local checkpoint files."""

    def __init__(self, path: Union[str, Path] = DEFAULT_CHECKPOINT_PATH):
        self.path = Path(path)

    def save(self, checkpoint: Checkpoint) -> Path:
        """Saves a validated Checkpoint object to disk as UTF-8 formatted JSON."""
        checkpoint.validate()
        data = checkpoint.to_dict()
        
        # Ensure parent directory exists (.ai/)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            
        return self.path

    def load(self) -> Checkpoint:
        """Loads and validates a Checkpoint object from disk."""
        if not self.path.exists():
            raise CheckpointNotFoundError(f"Checkpoint file not found: '{self.path}'")

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise CheckpointValidationError(f"Invalid JSON syntax in checkpoint file '{self.path}': {e}")
        except Exception as e:
            raise CheckpointValidationError(f"Failed to read checkpoint file '{self.path}': {e}")

        return Checkpoint.from_dict(data)

    def exists(self) -> bool:
        """Checks whether the checkpoint file exists on disk."""
        return self.path.exists()
