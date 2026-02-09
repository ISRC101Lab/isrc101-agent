"""Lightweight startup profiling for interactive CLI startup."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUTHY


@dataclass(frozen=True)
class StartupStage:
    name: str
    delta_ms: float
    total_ms: float


class StartupProfiler:
    """Collect and optionally print startup stage timings."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        now = time.perf_counter()
        self._start = now
        self._last = now
        self._stages: list[StartupStage] = []

    @classmethod
    def from_env(cls, env_var: str = "ISRC_PROFILE_STARTUP") -> "StartupProfiler":
        return cls(enabled=_is_truthy(os.getenv(env_var)))

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self.enabled = True

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self._stages.append(
            StartupStage(
                name=name,
                delta_ms=(now - self._last) * 1000.0,
                total_ms=(now - self._start) * 1000.0,
            )
        )
        self._last = now

    def render(self, console: Console) -> None:
        if not self.enabled or not self._stages:
            return

        table = Table(title="[bold]Startup Profile[/bold]", border_style="#4C566A")
        table.add_column("Stage", style="bold")
        table.add_column("Δ ms", justify="right")
        table.add_column("Total ms", justify="right")

        for stage in self._stages:
            table.add_row(stage.name, f"{stage.delta_ms:.1f}", f"{stage.total_ms:.1f}")

        console.print(table)

