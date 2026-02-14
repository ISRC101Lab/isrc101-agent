"""Crew-specific console rendering: event log, single-line ticker, and summary."""

import threading
import time
from typing import Dict, List, Optional

from rich.console import Console, Group
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


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


# Box-drawing character lookup: frozenset of directions → character
_BOX_CHARS = {
    frozenset():                              ' ',
    frozenset({'up'}):                        '│',
    frozenset({'down'}):                      '│',
    frozenset({'left'}):                      '─',
    frozenset({'right'}):                     '─',
    frozenset({'up', 'down'}):                '│',
    frozenset({'left', 'right'}):             '─',
    frozenset({'up', 'right'}):               '└',
    frozenset({'up', 'left'}):                '┘',
    frozenset({'down', 'right'}):             '┌',
    frozenset({'down', 'left'}):              '┐',
    frozenset({'up', 'down', 'right'}):       '├',
    frozenset({'up', 'down', 'left'}):        '┤',
    frozenset({'up', 'left', 'right'}):       '┴',
    frozenset({'down', 'left', 'right'}):     '┬',
    frozenset({'up', 'down', 'left', 'right'}): '┼',
}

# DAG layout constants
_DAG_COL_W = 14   # horizontal spacing between column centers
_DAG_MARGIN = 6   # left margin


class CrewRenderer:
    """Renders crew execution with print-based events and a single-line live ticker."""

    def __init__(self, console: Console, max_events: int = 4):
        self.console = console
        self._lock = threading.Lock()
        # live_console is set during event loop to the Live context's console
        self._live_console: Optional[Console] = None

    def _print(self, markup: str) -> None:
        """Print an event line. Uses Live console if available to print above ticker."""
        c = self._live_console or self.console
        with self._lock:
            c.print(f"  {markup}")

    # ── Decomposition: static task plan + layered DAG ────

    def render_decomposition(self, tasks: List[CrewTask]) -> None:
        """Show task plan table + layered DAG graph."""
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

        dag = self._build_dag_graph(tasks)

        with self._lock:
            self.console.print(Panel(
                Group(table, Text(""), dag),
                title=f"[bold {THEME_ACCENT}] Crew Task Plan [/bold {THEME_ACCENT}]",
                title_align="left",
                border_style=THEME_BORDER,
                padding=(0, 1),
            ))

    # ── Layered DAG graph ──────────────────────────────────

    @staticmethod
    def _assign_dag_columns(layers: List[List[CrewTask]]) -> Dict[str, int]:
        """Assign a column index to each task for horizontal positioning.

        Children inherit their parent's column when possible so that
        straight-down edges dominate the graph.
        """
        task_col: Dict[str, int] = {}
        for layer in layers:
            # Process tasks that have parents first, sorted by leftmost parent
            sorted_layer = sorted(
                layer,
                key=lambda t: min(
                    (task_col.get(d, float('inf')) for d in t.depends_on),
                    default=float('inf'),
                ),
            )
            used: set = set()
            for task in sorted_layer:
                parent_cols = sorted(
                    task_col[d] for d in task.depends_on if d in task_col
                )
                if parent_cols:
                    # Single parent → same column; fan-in → median parent column
                    preferred = parent_cols[len(parent_cols) // 2]
                else:
                    preferred = 0
                col = preferred
                while col in used:
                    col += 1
                task_col[task.id] = col
                used.add(col)
        return task_col

    def _build_dag_graph(
        self,
        tasks: List[CrewTask],
        states: Optional[Dict[str, str]] = None,
    ) -> Text:
        """Build a multi-line layered DAG with box-drawing connectors.

        Example output (7 tasks, 2 parallel streams + fan-in)::

              ○ t1            ○ t4
               │               │
              ○ t2            ○ t5
               │               │
              ○ t3            ○ t7
               └───────┬───────┘
                      ○ t6
        """
        layers = _topo_layers(tasks)
        if not layers:
            return Text("  (no tasks)")

        if states is None:
            states = {t.id: "pending" for t in tasks}

        task_col = self._assign_dag_columns(layers)
        max_col = max(task_col.values(), default=0)

        def cx(col: int) -> int:
            """Center x-position for a column."""
            return _DAG_MARGIN + col * _DAG_COL_W + _DAG_COL_W // 2

        total_w = _DAG_MARGIN + (max_col + 1) * _DAG_COL_W + _DAG_MARGIN
        text = Text()

        for li, layer in enumerate(layers):
            # ── Node row ──
            sorted_tasks = sorted(layer, key=lambda t: task_col[t.id])
            cursor = 0
            for task in sorted_tasks:
                center = cx(task_col[task.id])
                state_str = states.get(task.id, "pending")
                icon_char, color, _ = _STATE_DISPLAY.get(
                    state_str, ("?", THEME_DIM, "?"))
                icon = get_icon(icon_char)
                role_color = _color_for_role(task.assigned_role)

                node_label = f"{icon} {task.id}"
                start = max(0, center - len(node_label) // 2)
                if start > cursor:
                    text.append(" " * (start - cursor))
                text.append(f"{icon} ", style=color)
                text.append(task.id, style=f"bold {role_color}")
                cursor = start + len(node_label)
            text.append("\n")

            # ── Connector row(s) between this layer and the next ──
            if li < len(layers) - 1:
                self._render_dag_connectors(
                    text, layers[li + 1], task_col, cx, total_w,
                )

        return text

    @staticmethod
    def _render_dag_connectors(
        text: Text,
        next_layer: List[CrewTask],
        task_col: Dict[str, int],
        cx_fn,
        total_w: int,
    ) -> None:
        """Draw box-drawing connectors between two adjacent layers."""
        # Collect all edges as (source_x, target_x)
        edges = []
        for task in next_layer:
            tgt_x = cx_fn(task_col[task.id])
            for dep in task.depends_on:
                if dep in task_col:
                    src_x = cx_fn(task_col[dep])
                    edges.append((src_x, tgt_x))

        if not edges:
            text.append("\n")
            return

        # Build direction sets at each x-position
        dirs: Dict[int, set] = {}
        for sx, tx in edges:
            if sx == tx:
                dirs.setdefault(sx, set()).update({'up', 'down'})
            elif sx < tx:
                dirs.setdefault(sx, set()).add('up')
                dirs.setdefault(sx, set()).add('right')
                dirs.setdefault(tx, set()).add('down')
                dirs.setdefault(tx, set()).add('left')
                for x in range(sx + 1, tx):
                    dirs.setdefault(x, set()).update({'left', 'right'})
            else:
                dirs.setdefault(sx, set()).add('up')
                dirs.setdefault(sx, set()).add('left')
                dirs.setdefault(tx, set()).add('down')
                dirs.setdefault(tx, set()).add('right')
                for x in range(tx + 1, sx):
                    dirs.setdefault(x, set()).update({'left', 'right'})

        # Render connector row
        grid = [' '] * total_w
        for x, d in dirs.items():
            if 0 <= x < total_w:
                grid[x] = _BOX_CHARS.get(frozenset(d), '?')

        text.append(''.join(grid).rstrip(), style=THEME_DIM)
        text.append("\n")

    # ── Event logging (prints permanently above live ticker) ──

    def render_task_start(self, task: CrewTask) -> None:
        color = _color_for_role(task.assigned_role)
        worker = task.assigned_worker or task.assigned_role
        self._print(
            f"[{color}]{get_icon('▸')} {worker}[/{color}] "
            f"[{THEME_DIM}]starting {task.id}[/{THEME_DIM}]"
        )

    def render_task_done(self, result: TaskResult) -> None:
        color = _color_for_role(result.role_name)
        self._print(
            f"[{THEME_SUCCESS}]{get_icon('✓')}[/{THEME_SUCCESS}] "
            f"[{color}]{result.role_name}[/{color}] "
            f"[{THEME_DIM}]{result.task_id} done "
            f"({result.tokens_used:,}tok, {result.elapsed_seconds:.1f}s)[/{THEME_DIM}]"
        )

    def render_task_failed(self, result: TaskResult) -> None:
        color = _color_for_role(result.role_name)
        brief = (result.error or "unknown")[:60]
        self._print(
            f"[{THEME_ERROR}]{get_icon('✗')}[/{THEME_ERROR}] "
            f"[{color}]{result.role_name}[/{color}] "
            f"[{THEME_ERROR}]{result.task_id}: {brief}[/{THEME_ERROR}]"
        )

    def render_task_skipped(self, task: CrewTask) -> None:
        self._print(
            f"[{THEME_DIM}]{get_icon('–')} {task.assigned_role} skipped {task.id}[/{THEME_DIM}]"
        )

    def render_review_created(self, task_id: str) -> None:
        self._print(
            f"[{THEME_INFO}]{get_icon('⊙')} review[/{THEME_INFO}] "
            f"[{THEME_DIM}]{task_id}[/{THEME_DIM}]"
        )

    def render_review_passed(self, task_id: str) -> None:
        self._print(
            f"[{THEME_SUCCESS}]{get_icon('✓')} review passed[/{THEME_SUCCESS}] "
            f"[{THEME_DIM}]{task_id}[/{THEME_DIM}]"
        )

    def render_rework_requested(self, task_id: str, attempt: int) -> None:
        self._print(
            f"[{THEME_WARN}]{get_icon('⟲')} rework #{attempt}[/{THEME_WARN}] "
            f"[{THEME_DIM}]{task_id}[/{THEME_DIM}]"
        )

    def render_rework_limit(self, task_id: str) -> None:
        self._print(
            f"[{THEME_DIM}]{get_icon('–')} rework limit {task_id}[/{THEME_DIM}]"
        )

    def render_budget_warning(self, agent_id: str, threshold: int) -> None:
        self._print(
            f"[{THEME_WARN}]{get_icon('!')} {agent_id} budget at {threshold}%[/{THEME_WARN}]"
        )

    def render_budget_realloc(self, agent_id: str, reclaimed: int) -> None:
        if reclaimed > 0:
            self._print(
                f"[{THEME_DIM}]{get_icon('↻')} reclaimed {reclaimed:,}tok "
                f"from {agent_id}[/{THEME_DIM}]"
            )

    def render_status_update(self, agent_id: str, task_id: str, elapsed: float, tokens: int) -> None:
        self._print(
            f"[{THEME_DIM}]{get_icon('▸')} {agent_id} {task_id} "
            f"{elapsed:.0f}s {tokens:,}tok[/{THEME_DIM}]"
        )

    # ── Live progress ticker (single line, updated in-place) ──

    def build_ticker(
        self,
        tasks: List[CrewTask],
        states: Dict[str, str],
        start_times: Dict[str, float],
        budget_used: int,
        budget_max: int,
    ) -> Text:
        """Build a single-line compact progress ticker for the Live display.

        Format: ● 2/7 | ✓t1 → [▸t2|▸t3] → ○t4 | Budget: 150k/7.0M (2%)
        """
        total = len(tasks)
        done = sum(1 for t in tasks if states.get(t.id) in ("done", "failed", "skipped"))
        now = time.monotonic()

        text = Text()
        text.append(f"  {get_icon('●')} ", style=f"bold {THEME_ACCENT}")
        text.append(f"{done}/{total}", style=f"bold {THEME_INFO}")
        text.append(" │ ", style=THEME_DIM)

        # Compact flow: ✓t1 → [▸t2|▸t3] → ○t4
        layers = _topo_layers(tasks)
        for i, layer in enumerate(layers):
            if i > 0:
                text.append("→", style=THEME_DIM)
            if len(layer) > 1:
                text.append("[", style=THEME_DIM)
            for j, t in enumerate(layer):
                if j > 0:
                    text.append("|", style=THEME_DIM)
                state_str = states.get(t.id, "pending")
                icon_char, color, _label = _STATE_DISPLAY.get(
                    state_str, ("?", THEME_DIM, state_str))
                icon = get_icon(icon_char)
                text.append(f"{icon}{t.id}", style=color)
            if len(layer) > 1:
                text.append("]", style=THEME_DIM)

        text.append(" │ ", style=THEME_DIM)

        # Budget
        budget_pct = int(budget_used / budget_max * 100) if budget_max > 0 else 0
        if budget_max > 0:
            budget_str = f"Budget: {_fmt_tokens(budget_used)}/{_fmt_tokens(budget_max)} ({budget_pct}%)"
            if budget_pct >= 80:
                text.append(f"[!] {budget_str}", style=f"bold {THEME_WARN}")
            else:
                text.append(budget_str, style=THEME_DIM)
        else:
            text.append(f"Budget: {_fmt_tokens(budget_used)}", style=THEME_DIM)

        # Active task elapsed times
        active = []
        for t in tasks:
            s = states.get(t.id, "pending")
            if s in ("assigned", "running", "in_review", "rework"):
                start = start_times.get(t.id)
                if start:
                    active.append(f"{t.id}:{now - start:.0f}s")
        if active:
            text.append(f" │ ", style=THEME_DIM)
            text.append(" ".join(active), style=THEME_DIM)

        return text

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
