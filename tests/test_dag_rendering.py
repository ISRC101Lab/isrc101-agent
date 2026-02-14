"""Tests for crew DAG graph rendering."""

import io

import pytest
from rich.console import Console
from rich.text import Text

from isrc101_agent.crew.rendering import CrewRenderer, _topo_layers, _BOX_CHARS
from isrc101_agent.crew.tasks import CrewTask


def _make_tasks(specs):
    """Create tasks from (id, role, depends_on) tuples."""
    return [
        CrewTask(id=tid, description=f"Task {tid}", assigned_role=role,
                 depends_on=deps)
        for tid, role, deps in specs
    ]


def _render_dag_text(tasks, states=None):
    """Render DAG to plain text for assertion."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    renderer = CrewRenderer(console)
    dag = renderer._build_dag_graph(tasks, states)
    console.print(dag, end="")
    return buf.getvalue()


class TestTopoLayers:
    """_topo_layers() groups tasks correctly."""

    def test_linear_chain(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
            ("t3", "reviewer", ["t2"]),
        ])
        layers = _topo_layers(tasks)
        assert len(layers) == 3
        assert [t.id for t in layers[0]] == ["t1"]
        assert [t.id for t in layers[1]] == ["t2"]
        assert [t.id for t in layers[2]] == ["t3"]

    def test_parallel_roots(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", []),
            ("t3", "reviewer", ["t1", "t2"]),
        ])
        layers = _topo_layers(tasks)
        assert len(layers) == 2
        assert {t.id for t in layers[0]} == {"t1", "t2"}
        assert [t.id for t in layers[1]] == ["t3"]

    def test_diamond(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
            ("t3", "coder", ["t1"]),
            ("t4", "reviewer", ["t2", "t3"]),
        ])
        layers = _topo_layers(tasks)
        assert len(layers) == 3
        assert [t.id for t in layers[0]] == ["t1"]
        assert {t.id for t in layers[1]} == {"t2", "t3"}
        assert [t.id for t in layers[2]] == ["t4"]


class TestColumnAssignment:
    """_assign_dag_columns() places nodes in correct columns."""

    def test_linear_single_column(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
            ("t3", "reviewer", ["t2"]),
        ])
        layers = _topo_layers(tasks)
        cols = CrewRenderer._assign_dag_columns(layers)
        # Linear chain should be all in column 0
        assert cols["t1"] == 0
        assert cols["t2"] == 0
        assert cols["t3"] == 0

    def test_parallel_branches(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", []),
            ("t3", "reviewer", ["t1"]),
            ("t4", "tester", ["t2"]),
        ])
        layers = _topo_layers(tasks)
        cols = CrewRenderer._assign_dag_columns(layers)
        # t1 and t2 are in different columns
        assert cols["t1"] != cols["t2"]
        # t3 inherits t1's column, t4 inherits t2's column
        assert cols["t3"] == cols["t1"]
        assert cols["t4"] == cols["t2"]

    def test_fan_in(self):
        tasks = _make_tasks([
            ("t1", "coder", []),
            ("t2", "coder", []),
            ("t3", "reviewer", ["t1", "t2"]),
        ])
        layers = _topo_layers(tasks)
        cols = CrewRenderer._assign_dag_columns(layers)
        # t1 and t2 in different columns
        assert cols["t1"] != cols["t2"]
        # t3 placed at median of parents
        assert cols["t3"] in (cols["t1"], cols["t2"])

    def test_fan_out(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
            ("t3", "coder", ["t1"]),
        ])
        layers = _topo_layers(tasks)
        cols = CrewRenderer._assign_dag_columns(layers)
        # t2 inherits t1's column, t3 goes to next
        assert cols["t2"] == cols["t1"]
        assert cols["t3"] == cols["t1"] + 1


class TestBoxDrawingChars:
    """_BOX_CHARS covers all 4-bit direction combos."""

    def test_straight_vertical(self):
        assert _BOX_CHARS[frozenset({'up', 'down'})] == '│'

    def test_straight_horizontal(self):
        assert _BOX_CHARS[frozenset({'left', 'right'})] == '─'

    def test_corners(self):
        assert _BOX_CHARS[frozenset({'up', 'right'})] == '└'
        assert _BOX_CHARS[frozenset({'up', 'left'})] == '┘'
        assert _BOX_CHARS[frozenset({'down', 'right'})] == '┌'
        assert _BOX_CHARS[frozenset({'down', 'left'})] == '┐'

    def test_tees(self):
        assert _BOX_CHARS[frozenset({'up', 'down', 'right'})] == '├'
        assert _BOX_CHARS[frozenset({'up', 'down', 'left'})] == '┤'
        assert _BOX_CHARS[frozenset({'up', 'left', 'right'})] == '┴'
        assert _BOX_CHARS[frozenset({'down', 'left', 'right'})] == '┬'

    def test_cross(self):
        assert _BOX_CHARS[frozenset({'up', 'down', 'left', 'right'})] == '┼'


class TestDagGraphRendering:
    """_build_dag_graph() produces correct multi-line output."""

    def test_linear_chain_has_vertical_connectors(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
            ("t3", "reviewer", ["t2"]),
        ])
        output = _render_dag_text(tasks)
        # Should have all task IDs
        assert "t1" in output
        assert "t2" in output
        assert "t3" in output
        # Should have vertical connectors
        assert "│" in output

    def test_parallel_branches_separate_columns(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t4", "coder", []),
            ("t2", "coder", ["t1"]),
            ("t5", "reviewer", ["t4"]),
        ])
        output = _render_dag_text(tasks)
        lines = output.strip().split("\n")
        # First line should have both t1 and t4 on the same row
        first_line = lines[0]
        assert "t1" in first_line
        assert "t4" in first_line

    def test_fan_in_has_merge_connector(self):
        tasks = _make_tasks([
            ("t1", "coder", []),
            ("t2", "coder", []),
            ("t3", "reviewer", ["t1", "t2"]),
        ])
        output = _render_dag_text(tasks)
        # Should have merge characters (┘ or └ or ┬)
        has_merge = any(c in output for c in "└┘┬")
        assert has_merge, f"Expected merge connectors in:\n{output}"

    def test_fan_out_has_fork_connector(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
            ("t3", "coder", ["t1"]),
        ])
        output = _render_dag_text(tasks)
        # Should have fork characters (├ or ┐ or ┌)
        has_fork = any(c in output for c in "├┐┌")
        assert has_fork, f"Expected fork connectors in:\n{output}"

    def test_seven_task_crew_dag(self):
        """Realistic 7-task crew DAG from user's example."""
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
            ("t3", "reviewer", ["t2"]),
            ("t4", "coder", []),
            ("t5", "reviewer", ["t4"]),
            ("t6", "tester", ["t3"]),
            ("t7", "tester", ["t5"]),
        ])
        output = _render_dag_text(tasks)
        # All tasks should be present
        for tid in ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]:
            assert tid in output, f"{tid} missing from:\n{output}"
        # Should have multiple lines (layered, not one-line)
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 4, f"Expected layered DAG, got {len(lines)} lines"

    def test_single_task(self):
        tasks = _make_tasks([("t1", "coder", [])])
        output = _render_dag_text(tasks)
        assert "t1" in output
        # No connectors needed
        assert "│" not in output

    def test_status_icons_reflected(self):
        tasks = _make_tasks([
            ("t1", "researcher", []),
            ("t2", "coder", ["t1"]),
        ])
        states = {"t1": "done", "t2": "running"}
        output = _render_dag_text(tasks, states)
        # t1 should show done icon, t2 should show running icon
        assert "✓" in output or "✓" in output  # done icon
        assert "▸" in output  # running icon

    def test_no_tasks_returns_placeholder(self):
        output = _render_dag_text([])
        assert "no tasks" in output.lower()
