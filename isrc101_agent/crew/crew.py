"""Crew main entry point — thin wrapper around Coordinator."""

from dataclasses import dataclass, field
from typing import Dict, List

from rich.console import Console

from ..config import Config
from ..rendering import get_icon
from ..theme import ACCENT as THEME_ACCENT, DIM as THEME_DIM, ERROR as THEME_ERROR
from .coordinator import Coordinator


@dataclass
class CrewConfig:
    """Configuration for crew multi-agent execution.

    Parsed from the ``crew:`` section of ``.agent.conf.yml``.
    """

    max_parallel: int = 2
    per_agent_budget: int = 1_000_000
    token_budget: int = 0              # 0 = auto-scale
    auto_review: bool = True
    max_rework: int = 2
    message_timeout: float = 60.0
    task_timeout: float = 300.0
    budget_warning_thresholds: List[int] = field(default_factory=lambda: [50, 75, 90])
    role_budget_multipliers: Dict[str, float] = field(default_factory=lambda: {
        "coder": 1.0,
        "reviewer": 0.4,
        "researcher": 0.5,
        "tester": 0.6,
    })
    display_mode: str = "compact"      # "compact" | "full"
    display_max_events: int = 4
    display_refresh_rate: int = 2      # Hz

    @classmethod
    def from_dict(cls, data: dict) -> "CrewConfig":
        """Parse a CrewConfig from a raw config dictionary (YAML crew: section)."""
        if not data:
            return cls()

        display = data.get("display", {})
        role_mults = data.get("role-budget-multipliers", {})
        thresholds = data.get("budget-warning-thresholds", [50, 75, 90])

        return cls(
            max_parallel=data.get("max-parallel", 2),
            per_agent_budget=data.get("per-agent-budget", 1_000_000),
            token_budget=data.get("token-budget", 0),
            auto_review=data.get("auto-review", True),
            max_rework=data.get("max-rework", 2),
            message_timeout=data.get("message-timeout", 60.0),
            task_timeout=data.get("task-timeout", 300.0),
            budget_warning_thresholds=list(thresholds),
            role_budget_multipliers={
                "coder": role_mults.get("coder", 1.0),
                "reviewer": role_mults.get("reviewer", 0.4),
                "researcher": role_mults.get("researcher", 0.5),
                "tester": role_mults.get("tester", 0.6),
                **{k: v for k, v in role_mults.items()
                   if k not in ("coder", "reviewer", "researcher", "tester")},
            },
            display_mode=display.get("mode", "compact"),
            display_max_events=display.get("max-events", 4),
            display_refresh_rate=display.get("refresh-rate", 2),
        )


class Crew:
    """Top-level crew interface invoked by the /crew command."""

    def __init__(self, config: Config, console: Console):
        self.config = config
        self.console = console

        crew_raw = getattr(config, "crew_config", None) or {}
        self.crew_cfg = CrewConfig.from_dict(crew_raw)

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
            crew_cfg=self.crew_cfg,
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
