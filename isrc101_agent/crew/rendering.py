"""Crew-specific console rendering: agent panels, progress, and summary table."""

import threading
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..theme import (
    ACCENT as THEME_ACCENT,
    BORDER as THEME_BORDER,
    DIM as THEME_DIM,
    SUCCESS as THEME_SUCCESS,
    ERROR as THEME_ERROR,
    INFO as THEME_INFO,
)
from ..rendering import get_icon
from .tasks import CrewTask, TaskResult

# 8-color palette for agent distinction
AGENT_COLORS = [
    "#7FA6D9",  # blue
    "#57DB9C",  # green
    "#D9A67F",  # orange
    "#D97FD9",  # magenta
    "#7FD9D9",  # cyan
    "#D9D97F",  # yellow
    "#9C7FD9",  # purple
    "#D97F7F",  # red
]


def _color_for_role(role_name: str) -> str:
    """Assign a deterministic color based on role name hash."""
    idx = hash(role_name) % len(AGENT_COLORS)
    return AGENT_COLORS[idx]


class CrewRenderer:
    """Renders crew execution progress to the console."""

    def __init__(self, console: Console):
        self.console = console
        self._lock = threading.Lock()

    def render_decomposition(self, tasks: List[CrewTask]) -> None:
        """Show the task decomposition plan."""
        table = Table(
            show_header=True,
            header_style=f"bold {THEME_ACCENT}",
            border_style=THEME_BORDER,
            padding=(0, 1),
        )
        table.add_column("ID", style="bold", min_width=6)
        table.add_column("Role", min_width=10)
        table.add_column("Description", min_width=30)
        table.add_column("Depends On", min_width=10)

        for task in tasks:
            color = _color_for_role(task.assigned_role)
            deps = ", ".join(task.depends_on) if task.depends_on else "-"
            table.add_row(
                task.id,
                f"[{color}]{task.assigned_role}[/{color}]",
                task.description,
                deps,
            )

        with self._lock:
            self.console.print(Panel(
                table,
                title=f"[bold {THEME_ACCENT}] Crew Task Plan [/bold {THEME_ACCENT}]",
                title_align="left",
                border_style=THEME_BORDER,
                padding=(0, 1),
            ))

    def render_task_start(self, task: CrewTask) -> None:
        """Show that a task is starting, including worker instance if assigned."""
        color = _color_for_role(task.assigned_role)
        icon = get_icon("▶")
        worker_label = task.assigned_role
        if task.assigned_worker and task.assigned_worker != task.assigned_role:
            worker_label = task.assigned_worker
        with self._lock:
            self.console.print(
                f"  [{color}]{icon} {worker_label}[/{color}] "
                f"[{THEME_DIM}]starting: {task.description}[/{THEME_DIM}]"
            )

    def render_task_done(self, result: TaskResult) -> None:
        """Show task completion."""
        color = _color_for_role(result.role_name)
        icon = get_icon("✓")
        with self._lock:
            self.console.print(
                f"  [{THEME_SUCCESS}]{icon}[/{THEME_SUCCESS}] "
                f"[{color}]{result.role_name}[/{color}] completed "
                f"[{THEME_DIM}]({result.tokens_used:,} tokens, {result.elapsed_seconds:.1f}s)[/{THEME_DIM}]"
            )

    def render_task_failed(self, result: TaskResult) -> None:
        """Show task failure."""
        color = _color_for_role(result.role_name)
        icon = get_icon("✗")
        with self._lock:
            self.console.print(
                f"  [{THEME_ERROR}]{icon}[/{THEME_ERROR}] "
                f"[{color}]{result.role_name}[/{color}] failed: "
                f"[{THEME_ERROR}]{result.error or 'unknown error'}[/{THEME_ERROR}]"
            )

    def render_task_skipped(self, task: CrewTask) -> None:
        """Show task skipped due to upstream failure."""
        color = _color_for_role(task.assigned_role)
        icon = get_icon("⊘")
        with self._lock:
            self.console.print(
                f"  [{THEME_DIM}]{icon} {task.assigned_role} skipped: {task.description}[/{THEME_DIM}]"
            )

    def render_review_created(self, task_id: str) -> None:
        """Show that a review has been requested for a task."""
        icon = get_icon("⟳")
        with self._lock:
            self.console.print(
                f"  [{THEME_INFO}]{icon} review requested[/{THEME_INFO}] "
                f"[{THEME_DIM}]for task {task_id}[/{THEME_DIM}]"
            )

    def render_review_passed(self, task_id: str) -> None:
        """Show that a review passed."""
        icon = get_icon("✓")
        with self._lock:
            self.console.print(
                f"  [{THEME_SUCCESS}]{icon} review passed[/{THEME_SUCCESS}] "
                f"[{THEME_DIM}]for task {task_id}[/{THEME_DIM}]"
            )

    def render_rework_requested(self, task_id: str, attempt: int) -> None:
        """Show that rework has been requested."""
        icon = get_icon("⟲")
        with self._lock:
            self.console.print(
                f"  [{THEME_INFO}]{icon} rework #{attempt}[/{THEME_INFO}] "
                f"[{THEME_DIM}]requested for task {task_id}[/{THEME_DIM}]"
            )

    def render_rework_limit(self, task_id: str) -> None:
        """Show that rework limit was reached and output accepted as-is."""
        icon = get_icon("⊘")
        with self._lock:
            self.console.print(
                f"  [{THEME_DIM}]{icon} rework limit reached for task {task_id} — accepting current output[/{THEME_DIM}]"
            )

    def render_summary(self, results: List[TaskResult], skipped: Optional[List[CrewTask]] = None) -> None:
        """Render the final crew execution summary table."""
        table = Table(
            show_header=True,
            header_style=f"bold {THEME_ACCENT}",
            border_style=THEME_BORDER,
            padding=(0, 1),
        )
        table.add_column("Task", min_width=8)
        table.add_column("Agent", min_width=12)
        table.add_column("Status", min_width=8)
        table.add_column("Tokens", justify="right", min_width=8)
        table.add_column("Time", justify="right", min_width=8)

        total_tokens = 0
        total_time = 0.0

        for r in results:
            color = _color_for_role(r.role_name)
            status_style = THEME_SUCCESS if r.status == "done" else THEME_ERROR
            table.add_row(
                r.task_id,
                f"[{color}]{r.role_name}[/{color}]",
                f"[{status_style}]{r.status}[/{status_style}]",
                f"{r.tokens_used:,}",
                f"{r.elapsed_seconds:.1f}s",
            )
            total_tokens += r.tokens_used
            total_time += r.elapsed_seconds

        if skipped:
            for task in skipped:
                table.add_row(
                    task.id,
                    task.assigned_role,
                    f"[{THEME_DIM}]skipped[/{THEME_DIM}]",
                    "-",
                    "-",
                )

        footer = f"{total_time:.1f}s total | {total_tokens:,} tokens"
        with self._lock:
            self.console.print(Panel(
                table,
                title=f"[bold {THEME_ACCENT}] Crew Summary [/bold {THEME_ACCENT}]",
                subtitle=f"[{THEME_DIM}]{footer}[/{THEME_DIM}]",
                title_align="left",
                border_style=THEME_BORDER,
                padding=(0, 1),
            ))
