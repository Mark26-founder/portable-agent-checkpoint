"""Secret Redaction Engine adhering strictly to SECURITY.md specification."""

import re
from typing import Any, List, Dict


# Regex Patterns defined in SECURITY.md
PATTERNS = [
    # Generic Secret Key (e.g. api_key = "...", token: '...')
    (
        re.compile(r"""(?i)(api_key|secret|token|password)\s*[:=]\s*["']?([a-zA-Z0-9_\-\.]{8,})["']?"""),
        r"\1=[REDACTED_SECRET]",
    ),
    # OpenAI API Keys
    (
        re.compile(r"sk-[a-zA-Z0-9T3BlbkFJ]{20,}"),
        "[REDACTED_API_KEY]",
    ),
    # Anthropic API Keys
    (
        re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),
        "[REDACTED_API_KEY]",
    ),
    # AWS Access Keys
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "[REDACTED_AWS_KEY]",
    ),
]


def redact_string(text: str) -> str:
    """Applies regex pattern replacements to mask sensitive credentials in text."""
    if not isinstance(text, str) or not text:
        return text

    result = text
    for pattern, replacement in PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def redact_structure(obj: Any) -> Any:
    """Recursively redacts strings inside lists, dicts, or nested objects."""
    if isinstance(obj, str):
        return redact_string(obj)
    elif isinstance(obj, list):
        return [redact_structure(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: redact_structure(v) for k, v in obj.items()}
    return obj
