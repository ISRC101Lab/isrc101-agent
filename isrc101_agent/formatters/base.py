"""Base formatter class for tool result formatting."""

from abc import ABC, abstractmethod
from typing import Optional
from rich.console import RenderableType


class Formatter(ABC):
    """Abstract base class for result formatters.

    Formatters are plugins that detect and format specific types of tool results
    (JSON, CSV, XML, etc.) for optimal display in the terminal.
    """

    @abstractmethod
    def can_format(self, content: str, context: dict) -> bool:
        """Check if this formatter can handle the given content.

        Args:
            content: The raw result string from a tool
            context: Additional context including:
                - tool_name: str - Name of the tool that produced the result
                - tool_arguments: dict - Arguments passed to the tool
                - elapsed: float - Time taken to execute the tool

        Returns:
            True if this formatter should handle the content
        """
        pass

    @abstractmethod
    def format(self, content: str, context: dict) -> Optional[RenderableType]:
        """Format the content for display.

        Args:
            content: The raw result string from a tool
            context: Additional context (same as can_format)

        Returns:
            A Rich renderable object (Syntax, Table, JSON, Panel, etc.)
            or None to fall back to default rendering
        """
        pass

    @property
    def priority(self) -> int:
        """Priority for formatter selection (higher = checked first).

        Returns:
            Integer priority value. Default is 0.
            Higher priority formatters are checked before lower priority ones.
        """
        return 0
