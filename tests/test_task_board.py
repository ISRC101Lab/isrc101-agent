"""Tests for TaskBoard state machine and priority scheduling."""

import pytest

from isrc101_agent.crew.board import TaskBoard, TaskState
from isrc101_agent.crew.tasks import CrewTask, TaskResult


def _task(id, role="coder", depends_on=None, complexity=3):
    return CrewTask(
        id=id,
        description=f"Task {id}",
        assigned_role=role,
        depends_on=depends_on or [],
        complexity=complexity,
    )


def _result(task_id, role="coder", status="done"):
    return TaskResult(
        task_id=task_id,
        role_name=role,
        status=status,
        output=f"Output for {task_id}",
        tokens_used=1000,
        elapsed_seconds=1.0,
    )


class TestTaskBoardBasics:
    """Basic task management."""

    def test_add_and_get_task(self):
        board = TaskBoard()
        t = _task("t1")
        board.add_task(t)
        assert board.get_task("t1") is t
        assert board.get_state("t1") == TaskState.PENDING

    def test_add_tasks_bulk(self):
        board = TaskBoard()
        tasks = [_task("t1"), _task("t2"), _task("t3")]
        board.add_tasks(tasks)
        assert len(board.get_all_tasks()) == 3

    def test_get_nonexistent_task(self):
        board = TaskBoard()
        assert board.get_task("nonexistent") is None

    def test_used_roles(self):
        board = TaskBoard()
        board.add_tasks([
            _task("t1", role="coder"),
            _task("t2", role="reviewer"),
            _task("t3", role="coder"),
        ])
        assert board.used_roles() == {"coder", "reviewer"}


class TestTaskBoardStateTransitions:
    """State machine transitions."""

    def test_assign(self):
        board = TaskBoard()
        board.add_task(_task("t1"))
        board.assign("t1", "worker-0")
        assert board.get_state("t1") == TaskState.ASSIGNED
        assert board.get_assignment("t1") == "worker-0"

    def test_mark_running(self):
        board = TaskBoard()
        board.add_task(_task("t1"))
        board.assign("t1", "w")
        board.mark_running("t1")
        assert board.get_state("t1") == TaskState.RUNNING

    def test_mark_done(self):
        board = TaskBoard()
        board.add_task(_task("t1"))
        result = _result("t1")
        board.mark_done("t1", result)
        assert board.get_state("t1") == TaskState.DONE
        assert board.get_result("t1") is result

    def test_mark_failed(self):
        board = TaskBoard()
        board.add_task(_task("t1"))
        result = _result("t1", status="failed")
        board.mark_failed("t1", result)
        assert board.get_state("t1") == TaskState.FAILED

    def test_mark_in_review(self):
        board = TaskBoard()
        board.add_task(_task("t1"))
        board.mark_in_review("t1")
        assert board.get_state("t1") == TaskState.IN_REVIEW

    def test_request_rework(self):
        board = TaskBoard()
        board.add_task(_task("t1"))
        count = board.request_rework("t1")
        assert count == 1
        assert board.get_state("t1") == TaskState.REWORK
        count2 = board.request_rework("t1")
        assert count2 == 2


class TestTaskBoardAssignable:
    """get_assignable() with dependencies and priority ordering."""

    def test_no_deps(self):
        board = TaskBoard()
        board.add_tasks([_task("t1"), _task("t2")])
        assignable = board.get_assignable()
        assert len(assignable) == 2

    def test_deps_not_met(self):
        board = TaskBoard()
        board.add_tasks([
            _task("t1"),
            _task("t2", depends_on=["t1"]),
        ])
        assignable = board.get_assignable()
        assert len(assignable) == 1
        assert assignable[0].id == "t1"

    def test_deps_met_after_done(self):
        board = TaskBoard()
        board.add_tasks([
            _task("t1"),
            _task("t2", depends_on=["t1"]),
        ])
        board.mark_done("t1", _result("t1"))
        assignable = board.get_assignable()
        assert len(assignable) == 1
        assert assignable[0].id == "t2"

    def test_assigned_not_in_assignable(self):
        board = TaskBoard()
        board.add_tasks([_task("t1"), _task("t2")])
        board.assign("t1", "w")
        assignable = board.get_assignable()
        assert len(assignable) == 1
        assert assignable[0].id == "t2"

    def test_rework_in_assignable(self):
        board = TaskBoard()
        board.add_tasks([_task("t1")])
        board.request_rework("t1")
        assignable = board.get_assignable()
        assert len(assignable) == 1
        assert assignable[0].id == "t1"

    def test_priority_by_downstream_count(self):
        """Tasks with more downstream dependents should be dispatched first."""
        board = TaskBoard()
        # t1 has 2 downstream (t3, t4), t2 has 1 downstream (t3)
        board.add_tasks([
            _task("t1"),
            _task("t2"),
            _task("t3", depends_on=["t1", "t2"]),
            _task("t4", depends_on=["t1"]),
        ])
        assignable = board.get_assignable()
        assert assignable[0].id == "t1"  # t1 has more downstream

    def test_priority_by_complexity_tiebreak(self):
        """Equal downstream count -> higher complexity first."""
        board = TaskBoard()
        board.add_tasks([
            _task("t1", complexity=2),
            _task("t2", complexity=5),
        ])
        assignable = board.get_assignable()
        assert assignable[0].id == "t2"


class TestTaskBoardResolution:
    """all_resolved() and skip_downstream()."""

    def test_all_resolved(self):
        board = TaskBoard()
        board.add_tasks([_task("t1"), _task("t2")])
        board.mark_done("t1", _result("t1"))
        board.mark_done("t2", _result("t2"))
        assert board.all_resolved() is True

    def test_not_all_resolved(self):
        board = TaskBoard()
        board.add_tasks([_task("t1"), _task("t2")])
        board.mark_done("t1", _result("t1"))
        assert board.all_resolved() is False

    def test_empty_board_not_resolved(self):
        board = TaskBoard()
        assert board.all_resolved() is False

    def test_skip_downstream(self):
        board = TaskBoard()
        board.add_tasks([
            _task("t1"),
            _task("t2", depends_on=["t1"]),
            _task("t3", depends_on=["t2"]),
        ])
        board.mark_failed("t1", _result("t1", status="failed"))
        board.skip_downstream("t1")
        assert board.get_state("t2") == TaskState.SKIPPED
        assert board.get_state("t3") == TaskState.SKIPPED

    def test_get_skipped_tasks(self):
        board = TaskBoard()
        board.add_tasks([
            _task("t1"),
            _task("t2", depends_on=["t1"]),
        ])
        board.mark_failed("t1", _result("t1", status="failed"))
        board.skip_downstream("t1")
        skipped = board.get_skipped_tasks()
        assert len(skipped) == 1
        assert skipped[0].id == "t2"


class TestTaskBoardContextForTask:
    """get_context_for_task() dependency result injection."""

    def test_context_from_dependencies(self):
        board = TaskBoard()
        board.add_tasks([
            _task("t1"),
            _task("t2", depends_on=["t1"]),
        ])
        board.mark_done("t1", _result("t1"))
        context = board.get_context_for_task(board.get_task("t2"))
        assert "Output for t1" in context

    def test_context_from_explicit_context_from(self):
        board = TaskBoard()
        t2 = CrewTask(
            id="t2", description="Task t2", assigned_role="coder",
            depends_on=["t1"], context_from=["t1"],
        )
        board.add_tasks([_task("t1"), t2])
        board.mark_done("t1", _result("t1"))
        context = board.get_context_for_task(t2)
        assert "Output for t1" in context
