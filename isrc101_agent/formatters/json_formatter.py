"""JSON formatter for tool results."""

import json
from typing import Optional
from rich.console import RenderableType
from rich.json import JSON

from .base import Formatter


class JSONFormatter(Formatter):
    """Format JSON content with syntax highlighting and indentation."""

    @property
    def priority(self) -> int:
        return 10  # High priority for common format

    def can_format(self, content: str, context: dict) -> bool:
        """Detect JSON content."""
        stripped = content.strip()
        if not stripped:
            return False

        # Quick structural check
        if not (stripped.startswith('{') or stripped.startswith('[')):
            return False

        # Validate it's actually valid JSON
        try:
            json.loads(stripped)
            return True
        except (json.JSONDecodeError, ValueError):
            return False

    def format(self, content: str, context: dict) -> Optional[RenderableType]:
        """Format JSON with rich.json.JSON for syntax highlighting."""
        try:
            # Parse and re-serialize for consistent formatting
            data = json.loads(content.strip())

            # Use Rich's JSON renderer for beautiful output
            return JSON.from_data(data, indent=2, highlight=True, sort_keys=False)
        except Exception:
            # If formatting fails, fall back to default
            return None
