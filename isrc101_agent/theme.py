"""Centralized color constants — backward-compatible wrapper for theme system."""

from .themes import get_theme

# Dynamic property access to current theme
def __getattr__(name: str):
    """Dynamically get theme attributes from the active theme."""
    theme = get_theme()
    if hasattr(theme, name):
        return getattr(theme, name)
    raise AttributeError(f"Theme has no attribute '{name}'")


# Re-export theme management functions
from .themes import (
    get_theme,
    set_theme,
    list_themes,
    get_theme_name,
)

__all__ = [
    "get_theme",
    "set_theme",
    "list_themes",
    "get_theme_name",
    # Color constants (dynamically resolved)
    "ACCENT",
    "BORDER",
    "DIM",
    "TEXT",
    "MUTED",
    "SEPARATOR",
    "SUCCESS",
    "WARN",
    "ERROR",
    "INFO",
    "PROMPT",
    "AGENT_BORDER",
    "AGENT_LABEL",
    "TOOL_BORDER",
]
