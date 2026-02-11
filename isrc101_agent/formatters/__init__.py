"""Formatter registry and dispatch system."""

from typing import List, Optional, Dict
from rich.console import RenderableType

from .base import Formatter
from .json_formatter import JSONFormatter
from .table_formatter import TableFormatter
from .xml_formatter import XMLFormatter
from .text_formatter import TextFormatter


class FormatterRegistry:
    """Registry for managing and dispatching formatters."""

    def __init__(self):
        self._formatters: List[Formatter] = []
        self._register_default_formatters()

    def _register_default_formatters(self):
        """Register all built-in formatters."""
        # Register formatters - they will be sorted by priority
        self.register(JSONFormatter())
        self.register(TableFormatter())
        self.register(XMLFormatter())
        self.register(TextFormatter())

    def register(self, formatter: Formatter):
        """Register a new formatter.

        Args:
            formatter: Formatter instance to register
        """
        self._formatters.append(formatter)
        # Sort by priority (highest first)
        self._formatters.sort(key=lambda f: f.priority, reverse=True)

    def format_result(
        self,
        content: str,
        context: Optional[Dict] = None
    ) -> Optional[RenderableType]:
        """Attempt to format content using registered formatters.

        Args:
            content: Raw result string from a tool
            context: Additional context including:
                - tool_name: str - Name of the tool
                - tool_arguments: dict - Tool arguments
                - elapsed: float - Execution time

        Returns:
            A Rich renderable object if a formatter handled it,
            or None to use default rendering
        """
        if context is None:
            context = {}

        # Try each formatter in priority order
        for formatter in self._formatters:
            try:
                if formatter.can_format(content, context):
                    result = formatter.format(content, context)
                    if result is not None:
                        return result
            except Exception:
                # If a formatter fails, continue to next one
                continue

        # No formatter handled it
        return None


# Global registry instance
_registry = FormatterRegistry()


def format_result(
    content: str,
    tool_name: str = "",
    tool_arguments: Optional[Dict] = None,
    elapsed: float = 0.0
) -> Optional[RenderableType]:
    """Format a tool result using the global formatter registry.

    This is the main entry point for formatting tool results.

    Args:
        content: Raw result string from a tool
        tool_name: Name of the tool that produced the result
        tool_arguments: Arguments passed to the tool
        elapsed: Time taken to execute the tool

    Returns:
        A Rich renderable object if a formatter handled it,
        or None to use default rendering

    Example:
        >>> result = '{"name": "Alice", "age": 30}'
        >>> formatted = format_result(result, tool_name="read_file")
        >>> console.print(formatted)
    """
    context = {
        "tool_name": tool_name,
        "tool_arguments": tool_arguments or {},
        "elapsed": elapsed,
    }

    return _registry.format_result(content, context)


def register_formatter(formatter: Formatter):
    """Register a custom formatter with the global registry.

    Args:
        formatter: Formatter instance to register

    Example:
        >>> class MyFormatter(Formatter):
        ...     def can_format(self, content, context):
        ...         return content.startswith("CUSTOM:")
        ...     def format(self, content, context):
        ...         return Panel(content[7:])
        >>> register_formatter(MyFormatter())
    """
    _registry.register(formatter)


__all__ = [
    "Formatter",
    "FormatterRegistry",
    "format_result",
    "register_formatter",
    "JSONFormatter",
    "TableFormatter",
    "XMLFormatter",
    "TextFormatter",
]
