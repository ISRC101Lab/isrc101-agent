"""GitHub Light theme — light color scheme."""

from .base import Theme


class GithubLightTheme(Theme):
    """GitHub Light color palette."""

    def __init__(self):
        # Core palette
        self.ACCENT = "#0969DA"
        self.BORDER = "#D0D7DE"
        self.DIM = "#57606A"
        self.TEXT = "#24292F"
        self.MUTED = "#656D76"
        self.SEPARATOR = "#D8DEE4"

        # Semantic colors
        self.SUCCESS = "#1A7F37"
        self.WARN = "#9A6700"
        self.ERROR = "#CF222E"
        self.INFO = "#0969DA"

        # Prompt / input
        self.PROMPT = "#0969DA"

        # Agent rendering
        self.AGENT_BORDER = "blue"
        self.AGENT_LABEL = "[bold blue]isrc101[/bold blue]"
        self.TOOL_BORDER = "dim"
