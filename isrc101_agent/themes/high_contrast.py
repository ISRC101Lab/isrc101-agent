"""High contrast theme — for users with visual impairments."""

from .base import Theme


class HighContrastTheme(Theme):
    """High contrast theme with bright colors on dark background."""

    def __init__(self):
        # Core palette — bright and distinct colors
        self.ACCENT = "#00BFFF"       # Bright blue (DeepSkyBlue)
        self.BORDER = "#FFFFFF"       # Pure white
        self.DIM = "#AAAAAA"          # Light gray (still readable)
        self.TEXT = "#FFFFFF"         # Pure white
        self.MUTED = "#CCCCCC"        # Very light gray
        self.SEPARATOR = "#FFFFFF"    # Pure white

        # Semantic colors — maximum contrast
        self.SUCCESS = "#00FF00"      # Bright green (Lime)
        self.WARN = "#FFFF00"         # Bright yellow
        self.ERROR = "#FF0000"        # Bright red
        self.INFO = "#00BFFF"         # Bright cyan/blue

        # Prompt / input
        self.PROMPT = "#00BFFF"       # Bright blue

        # Agent rendering
        self.AGENT_BORDER = "#00BFFF"
        self.AGENT_LABEL = "isrc101"
        self.TOOL_BORDER = "#FFFFFF"
