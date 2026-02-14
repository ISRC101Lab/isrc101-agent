"""Crew-specific console rendering: table-based DAG, stable Live context, and summary."""

import threading
import time
from typing import Dict, List, Optional, Tuple

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..theme import (
    ACCENT as THEME_ACCENT,
    BORDER as THEME_BORDER,
    DIM as THEME_DIM,
    SUCCESS as THEME_SUCCESS,
    WARN as THEME_WARN,
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
    idx = hash(role_name) % len(AGENT_COLORS)
    return AGENT_COLORS[idx]


# Status display: (icon_char, color, label)
_STATE_DISPLAY = {
    "pending":   ("○", THEME_DIM,     "waiting"),
    "assigned":  ("▸", THEME_INFO,    "starting"),
    "running":   ("▸", THEME_INFO,    "running"),
    "done":      ("✓", THEME_SUCCESS, "done"),
    "failed":    ("✗", THEME_ERROR,   "failed"),
    "in_review": ("⊙", THEME_INFO,    "reviewing"),
    "rework":    ("⟲", THEME_WARN,    "rework"),
    "skipped":   ("–", THEME_DIM,     "skipped"),
}


def _topo_layers(tasks: List[CrewTask]) -> List[List[CrewTask]]:
    """Group tasks into topological layers for DAG visualization."""
    task_map = {t.id: t for t in tasks}
    placed: set = set()
    layers: List[List[CrewTask]] = []
    remaining = list(tasks)

    while remaining:
        layer = [t for t in remaining if all(d in placed for d in t.depends_on)]
        if not layer:
            layer = remaining[:]  # cycle fallback
        for t in layer:
            placed.add(t.id)
        remaining = [t for t in remaining if t.id not in placed]
        layers.append(layer)
    return layers


class CrewRenderer:
    """Renders crew execution with a stable table-based layout."""

    def __init__(self, console: Console, max_events: int = 4):
        self.console = console
        self._lock = threading.Lock()
        self._event_log: List[str] = []
        self._max_events = max_events

    def _log_event(self, markup_str: str) -> None:
        self._event_log.append(markup_str)
        if len(self._event_log) > self._max_events:
            self._event_log = self._event_log[-self._max_events:]

    # ── Decomposition: static task plan + DAG ──────────────

    def render_decomposition(self, tasks: List[CrewTask]) -> None:
        """Show task plan table + DAG dependency graph."""
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

        dag = self._build_static_dag(tasks)

        with self._lock:
            self.console.print(Panel(
                Group(table, Text(""), dag),
                title=f"[bold {THEME_ACCENT}] Crew Task Plan [/bold {THEME_ACCENT}]",
                title_align="left",
                border_style=THEME_BORDER,
                padding=(0, 1),
            ))

    def _build_static_dag(self, tasks: List[CrewTask]) -> Text:
        """Build a text DAG showing dependency flow and parallelism."""
        layers = _topo_layers(tasks)
        text = Text()
        text.append("  Execution flow:  ", style=f"bold {THEME_DIM}")

        for i, layer in enumerate(layers):
            if i > 0:
                text.append(" → ", style=THEME_DIM)
            if len(layer) == 1:
                t = layer[0]
                color = _color_for_role(t.assigned_role)
                text.append(f"{t.id}", style=f"bold {color}")
            else:
                text.append("[ ", style=THEME_ACCENT)
                for j, t in enumerate(layer):
                    if j > 0:
                        text.append(" | ", style=THEME_DIM)
                    color = _color_for_role(t.assigned_role)
                    text.append(f"{t.id}", style=f"bold {color}")
                text.append(" ]", style=THEME_ACCENT)

        parallel_count = sum(1 for l in layers if len(l) > 1)
        max_p = max((len(l) for l in layers), default=1)
        hint = f"  ({len(layers)} stages"
        if parallel_count > 0:
            hint += f", up to {max_p}x parallel"
        hint += ")"
        text.append(hint, style=THEME_DIM)
        return text

    # ── Event logging (updates live display) ───────────────

    def render_task_start(self, task: CrewTask) -> None:
        color = _color_for_role(task.assigned_role)
        worker = task.assigned_worker or task.assigned_role
        self._log_event(
            f"[{color}]{get_icon('▸')} {worker}[/{color}] "
            f"[{THEME_DIM}]starting {task.id}[/{THEME_DIM}]"
        )

    def render_task_done(self, result: TaskResult) -> None:
        color = _color_for_role(result.role_name)
        self._log_event(
            f"[{THEME_SUCCESS}]{get_icon('✓')}[/{THEME_SUCCESS}] "
            f"[{color}]{result.role_name}[/{color}] "
            f"[{THEME_DIM}]{result.task_id} done "
            f"({result.tokens_used:,}tok, {result.elapsed_seconds:.1f}s)[/{THEME_DIM}]"
        )

    def render_task_failed(self, result: TaskResult) -> None:
        color = _color_for_role(result.role_name)
        brief = (result.error or "unknown")[:60]
        self._log_event(
            f"[{THEME_ERROR}]{get_icon('✗')}[/{THEME_ERROR}] "
            f"[{color}]{result.role_name}[/{color}] "
            f"[{THEME_ERROR}]{result.task_id}: {brief}[/{THEME_ERROR}]"
        )

    def render_task_skipped(self, task: CrewTask) -> None:
        self._log_event(
            f"[{THEME_DIM}]{get_icon('–')} {task.assigned_role} skipped {task.id}[/{THEME_DIM}]"
        )

    def render_review_created(self, task_id: str) -> None:
        self._log_event(
            f"[{THEME_INFO}]{get_icon('⊙')} review[/{THEME_INFO}] "
            f"[{THEME_DIM}]{task_id}[/{THEME_DIM}]"
        )

    def render_review_passed(self, task_id: str) -> None:
        self._log_event(
            f"[{THEME_SUCCESS}]{get_icon('✓')} review passed[/{THEME_SUCCESS}] "
            f"[{THEME_DIM}]{task_id}[/{THEME_DIM}]"
        )

    def render_rework_requested(self, task_id: str, attempt: int) -> None:
        self._log_event(
            f"[{THEME_WARN}]{get_icon('⟲')} rework #{attempt}[/{THEME_WARN}] "
            f"[{THEME_DIM}]{task_id}[/{THEME_DIM}]"
        )

    def render_rework_limit(self, task_id: str) -> None:
        self._log_event(
            f"[{THEME_DIM}]{get_icon('–')} rework limit {task_id}[/{THEME_DIM}]"
        )

    def render_budget_warning(self, agent_id: str, threshold: int) -> None:
        self._log_event(
            f"[{THEME_WARN}]{get_icon('!')} {agent_id} budget at {threshold}%[/{THEME_WARN}]"
        )

    def render_budget_realloc(self, agent_id: str, reclaimed: int) -> None:
        if reclaimed > 0:
            self._log_event(
                f"[{THEME_DIM}]{get_icon('↻')} reclaimed {reclaimed:,}tok "
                f"from {agent_id}[/{THEME_DIM}]"
            )

    def render_status_update(self, agent_id: str, task_id: str, elapsed: float, tokens: int) -> None:
        self._log_event(
            f"[{THEME_DIM}]{get_icon('▸')} {agent_id} {task_id} "
            f"{elapsed:.0f}s {tokens:,}tok[/{THEME_DIM}]"
        )

    # ── Live progress display (three composable sections) ──

    def _build_flow_line(self, tasks: List[CrewTask], states: Dict[str, str]) -> Text:
        """Single-line compact DAG: ✓t1 → [ ▸t2 | ▸t3 ] → ○t4"""
        layers = _topo_layers(tasks)
        text = Text()
        text.append("  Flow: ", style=f"bold {THEME_DIM}")

        for i, layer in enumerate(layers):
            if i > 0:
                text.append(" → ", style=THEME_DIM)
            if len(layer) == 1:
                t = layer[0]
                state_str = states.get(t.id, "pending")
                icon_char, color, _label = _STATE_DISPLAY.get(
                    state_str, ("?", THEME_DIM, state_str))
                icon = get_icon(icon_char)
                text.append(f"{icon}{t.id}", style=f"bold {color}")
            else:
                text.append("[ ", style=THEME_ACCENT)
                for j, t in enumerate(layer):
                    if j > 0:
                        text.append(" | ", style=THEME_DIM)
                    state_str = states.get(t.id, "pending")
                    icon_char, color, _label = _STATE_DISPLAY.get(
                        state_str, ("?", THEME_DIM, state_str))
                    icon = get_icon(icon_char)
                    text.append(f"{icon}{t.id}", style=f"bold {color}")
                text.append(" ]", style=THEME_ACCENT)

        return text

    def _build_task_table(
        self,
        tasks: List[CrewTask],
        states: Dict[str, str],
        start_times: Dict[str, float],
    ) -> Table:
        """Rich Table with fixed columns: ID, Role, Worker, Status, Time."""
        now = time.monotonic()
        table = Table(
            show_header=True,
            header_style=f"bold {THEME_DIM}",
            border_style=THEME_BORDER,
            padding=(0, 1),
            show_edge=False,
            pad_edge=True,
        )
        table.add_column("ID", style="bold", min_width=6)
        table.add_column("Role", min_width=12)
        table.add_column("Worker", min_width=12)
        table.add_column("Status", min_width=10)
        table.add_column("Time", justify="right", min_width=8)

        for task in tasks:
            state_str = states.get(task.id, "pending")
            icon_char, color, label = _STATE_DISPLAY.get(
                state_str, ("?", THEME_DIM, state_str))
            icon = get_icon(icon_char)
            role_color = _color_for_role(task.assigned_role)
            worker = task.assigned_worker or "-"

            # Time display
            if state_str in ("assigned", "running", "in_review", "rework"):
                start = start_times.get(task.id)
                time_str = f"{now - start:.1f}s" if start else "-"
            else:
                time_str = "-"

            table.add_row(
                task.id,
                f"[{role_color}]{task.assigned_role}[/{role_color}]",
                f"[{role_color}]{worker}[/{role_color}]",
                f"[{color}]{icon} {label}[/{color}]",
                time_str,
            )

        return table

    def _build_footer(
        self,
        tasks: List[CrewTask],
        states: Dict[str, str],
        budget_used: int,
        budget_max: int,
    ) -> Text:
        """Progress bar + budget info + recent event log."""
        total_count = len(tasks)
        done_count = sum(
            1 for t in tasks
            if states.get(t.id) in ("done", "failed", "skipped")
        )

        pct = int(done_count / total_count * 100) if total_count > 0 else 0
        budget_pct = int(budget_used / budget_max * 100) if budget_max > 0 else 0
        bar_w = 12
        filled = int(bar_w * pct / 100)
        bar = get_icon("●") * filled + get_icon("·") * (bar_w - filled)
        bar_color = THEME_SUCCESS if pct >= 100 else (THEME_INFO if done_count > 0 else THEME_DIM)

        footer = Text()
        footer.append("  ")
        footer.append(f"{bar} ", style=bar_color)
        footer.append(f"{done_count}/{total_count}", style=f"bold {bar_color}")

        # Budget display with warning indicator
        def _fmt_tokens(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M"
            if n >= 1_000:
                return f"{n / 1_000:.0f}k"
            return str(n)

        budget_str = f"  Budget: {_fmt_tokens(budget_used)}/{_fmt_tokens(budget_max)} ({budget_pct}%)"
        if budget_pct >= 80:
            footer.append(f"  [!]{budget_str}", style=f"bold {THEME_WARN}")
        else:
            footer.append(budget_str, style=THEME_DIM)

        # Event log (last N entries)
        if self._event_log:
            for ev in self._event_log[-self._max_events:]:
                footer.append("\n  ")
                footer.append_text(Text.from_markup(ev))

        return footer

    def build_progress_display(
        self,
        tasks: List[CrewTask],
        states: Dict[str, str],
        start_times: Dict[str, float],
        budget_used: int,
        budget_max: int,
        per_agent_limit: int = 0,
    ) -> Panel:
        """Build a stable table-based progress panel.

        Three stacked sections: flow line, task table, footer (progress + events).
        """
        flow_line = self._build_flow_line(tasks, states)
        task_table = self._build_task_table(tasks, states, start_times)
        footer = self._build_footer(tasks, states, budget_used, budget_max)

        return Panel(
            Group(flow_line, Text(""), task_table, Text(""), footer),
            title=f"[bold {THEME_ACCENT}] Crew Progress [/bold {THEME_ACCENT}]",
            title_align="left",
            border_style=THEME_BORDER,
            padding=(0, 1),
        )

    # ── Final summary table ────────────────────────────────

    def render_summary(self, results: List[TaskResult], skipped: Optional[List[CrewTask]] = None) -> None:
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
