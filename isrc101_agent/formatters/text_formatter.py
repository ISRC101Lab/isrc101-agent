"""Large text formatter for tool results."""

from typing import Optional
from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text

from .base import Formatter
from ..theme import DIM, WARN, BORDER, INFO


class TextFormatter(Formatter):
    """Format large text results with summary (head + tail)."""

    @property
    def priority(self) -> int:
        return 1  # Low priority - only if no other formatter matches

    def can_format(self, content: str, context: dict) -> bool:
        """Detect large text content."""
        if not content:
            return False

        lines = content.splitlines()

        # Only format if text is very large (>1000 lines)
        # For smaller text, use default rendering
        return len(lines) > 1000

    def format(self, content: str, context: dict) -> Optional[RenderableType]:
        """Format as summary: first 10 lines + ... + last 10 lines."""
        try:
            lines = content.splitlines()
            total_lines = len(lines)
            total_chars = len(content)

            # Configuration
            head_lines = 10
            tail_lines = 10

            # Build summary
            summary = Text()

            # Add statistics header
            summary.append(
                f"Large text output: {total_lines:,} lines, {total_chars:,} characters\n\n",
                style=f"bold {INFO}"
            )

            # Add first N lines
            summary.append(f"First {head_lines} lines:\n", style=f"bold {DIM}")
            summary.append("─" * 60 + "\n", style=BORDER)

            for i, line in enumerate(lines[:head_lines], 1):
                summary.append(f"{i:4d} │ ", style=DIM)
                summary.append(line + "\n", style=DIM)

            # Add separator
            summary.append("\n", style=DIM)
            summary.append(
                f"... ({total_lines - head_lines - tail_lines:,} lines omitted) ...\n\n",
                style=f"italic {WARN}"
            )

            # Add last N lines
            summary.append(f"Last {tail_lines} lines:\n", style=f"bold {DIM}")
            summary.append("─" * 60 + "\n", style=BORDER)

            start_line_num = total_lines - tail_lines + 1
            for i, line in enumerate(lines[-tail_lines:], start_line_num):
                summary.append(f"{i:4d} │ ", style=DIM)
                summary.append(line + "\n", style=DIM)

            # Wrap in panel
            panel = Panel(
                summary,
                title=f"[{INFO}]Large Text Summary[/{INFO}]",
                border_style=BORDER,
                padding=(1, 2),
            )

            return panel

        except Exception:
            # Fall back to default rendering
            return None
