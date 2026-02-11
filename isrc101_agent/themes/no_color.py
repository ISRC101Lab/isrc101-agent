"""No Color theme — plain text output respecting NO_COLOR environment variable."""

from .base import Theme


class NoColorTheme(Theme):
    """No color theme for NO_COLOR environment variable."""

    def __init__(self):
        # All colors are empty — no ANSI codes
        self.ACCENT = ""
        self.BORDER = ""
        self.DIM = ""
        self.TEXT = ""
        self.MUTED = ""
        self.SEPARATOR = ""

        # Semantic colors
        self.SUCCESS = ""
        self.WARN = ""
        self.ERROR = ""
        self.INFO = ""

        # Prompt / input
        self.PROMPT = ""

        # Agent rendering (plain names)
        self.AGENT_BORDER = ""
        self.AGENT_LABEL = "isrc101"
        self.TOOL_BORDER = ""
