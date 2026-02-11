"""Base theme interface."""

from abc import ABC, abstractmethod


class Theme(ABC):
    """Base theme class defining the color palette interface."""

    # Core palette
    ACCENT: str
    BORDER: str
    DIM: str
    TEXT: str
    MUTED: str
    SEPARATOR: str

    # Semantic colors
    SUCCESS: str
    WARN: str
    ERROR: str
    INFO: str

    # Prompt / input
    PROMPT: str

    # Agent rendering
    AGENT_BORDER: str
    AGENT_LABEL: str
    TOOL_BORDER: str

    @abstractmethod
    def __init__(self):
        """Initialize theme colors."""
        pass

    @property
    def name(self) -> str:
        """Return the theme name."""
        return self.__class__.__name__.replace("Theme", "").lower()
