"""Theme system — centralized color management with multiple themes."""

import os
from typing import Optional, Dict, Type

from .base import Theme
from .github_dark import GithubDarkTheme
from .github_light import GithubLightTheme
from .no_color import NoColorTheme
from .high_contrast import HighContrastTheme

# Theme registry
_THEMES: Dict[str, Type[Theme]] = {
    "github_dark": GithubDarkTheme,
    "github_light": GithubLightTheme,
    "high_contrast": HighContrastTheme,
    "dark": GithubDarkTheme,  # alias
    "light": GithubLightTheme,  # alias
}

# Current active theme
_current_theme: Optional[Theme] = None


def get_theme() -> Theme:
    """Return the currently active theme instance."""
    global _current_theme
    if _current_theme is None:
        _current_theme = GithubDarkTheme()
    return _current_theme


def set_theme(name: str) -> bool:
    """Set the active theme by name. Returns True if successful."""
    global _current_theme

    # Check NO_COLOR environment variable
    if os.environ.get("NO_COLOR"):
        from .no_color import NoColorTheme
        _current_theme = NoColorTheme()
        return True

    theme_class = _THEMES.get(name.lower())
    if theme_class:
        _current_theme = theme_class()
        return True
    return False


def list_themes() -> list[str]:
    """Return list of available theme names."""
    seen = set()
    result = []
    for name, cls in _THEMES.items():
        if cls not in seen:
            result.append(name)
            seen.add(cls)
    return result


def get_theme_name() -> str:
    """Return the name of the current theme."""
    theme = get_theme()
    for name, cls in _THEMES.items():
        if isinstance(theme, cls):
            return name
    return "unknown"


# Initialize theme from environment
def _init_theme():
    """Initialize theme based on NO_COLOR environment variable."""
    if os.environ.get("NO_COLOR"):
        set_theme("no_color")


_init_theme()


# Dynamic attribute access for backward compatibility
# This allows `from .themes import ACCENT` to resolve at import time
# via the module-level __getattr__ below.

def __getattr__(name: str) -> str:
    """Dynamically resolve theme color constants from the active theme."""
    theme = get_theme()
    if hasattr(theme, name):
        return getattr(theme, name)
    raise AttributeError(f"module 'themes' has no attribute '{name}'")


__all__ = [
    "Theme",
    "get_theme",
    "set_theme",
    "list_themes",
    "get_theme_name",
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
