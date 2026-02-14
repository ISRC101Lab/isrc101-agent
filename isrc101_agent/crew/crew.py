"""Crew main entry point — thin wrapper around Coordinator."""

from rich.console import Console

from ..config import Config
from ..rendering import get_icon
from ..theme import ACCENT as THEME_ACCENT, DIM as THEME_DIM, ERROR as THEME_ERROR
from .coordinator import Coordinator


class Crew:
    """Top-level crew interface invoked by the /crew command."""

    def __init__(self, config: Config, console: Console):
        self.config = config
        self.console = console

        crew_cfg = getattr(config, "crew_config", None) or {}
        self.max_parallel = crew_cfg.get("max-parallel", 2)
        self.per_agent_budget = crew_cfg.get("per-agent-budget", 200_000)
        self.token_budget = crew_cfg.get("token-budget", 0)  # 0 = auto-scale
        self.auto_review = crew_cfg.get("auto-review", True)
        self.max_rework = crew_cfg.get("max-rework", 2)
        self.message_timeout = crew_cfg.get("message-timeout", 60.0)

    def run(self, request: str) -> str:
        """Execute a crew request end-to-end."""
        if not request.strip():
            self.console.print(f"  [{THEME_DIM}]Usage: /crew <task description>[/{THEME_DIM}]")
            return ""

        icon = get_icon("●")
        self.console.print(
            f"\n  [{THEME_ACCENT}]{icon} Crew[/{THEME_ACCENT}] "
            f"[{THEME_DIM}]decomposing request...[/{THEME_DIM}]"
        )

        coordinator = Coordinator(
            config=self.config,
            console=self.console,
            max_parallel=self.max_parallel,
            token_budget=self.token_budget,
            per_agent_budget=self.per_agent_budget,
            auto_review=self.auto_review,
            max_rework=self.max_rework,
            message_timeout=self.message_timeout,
        )

        try:
            result = coordinator.run(request)
        except KeyboardInterrupt:
            self.console.print(f"\n  [{THEME_ERROR}]Crew interrupted by user[/{THEME_ERROR}]")
            return "Crew execution interrupted."
        except Exception as e:
            self.console.print(f"\n  [{THEME_ERROR}]Crew error: {e}[/{THEME_ERROR}]")
            return f"Crew execution failed: {e}"

        return result
