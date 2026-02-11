"""GitHub Dark theme — the default dark color scheme."""

from .base import Theme


class GithubDarkTheme(Theme):
    """GitHub Dark color palette."""

    def __init__(self):
        # Core palette
        self.ACCENT = "#7FA6D9"
        self.BORDER = "#30363D"
        self.DIM = "#6E7681"
        self.TEXT = "#E6EDF3"
        self.MUTED = "#8B949E"
        self.SEPARATOR = "#484F58"

        # Semantic colors
        self.SUCCESS = "#57DB9C"
        self.WARN = "#E3B341"
        self.ERROR = "#F85149"
        self.INFO = "#58A6FF"

        # Prompt / input
        self.PROMPT = "#B7C6D8"

        # Agent rendering
        self.AGENT_BORDER = "cyan"
        self.AGENT_LABEL = "[bold cyan]isrc101[/bold cyan]"
        self.TOOL_BORDER = "dim"
