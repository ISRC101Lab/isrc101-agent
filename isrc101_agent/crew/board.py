"""TaskBoard: thread-safe task state machine replacing TaskGraph for the message-driven architecture."""

import threading
from enum import Enum
from typing import Dict, List, Optional, Set

from .tasks import CrewTask, TaskResult


class TaskState(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    IN_REVIEW = "in_review"
    REWORK = "rework"
    SKIPPED = "skipped"


_TERMINAL_STATES = frozenset({TaskState.DONE, TaskState.FAILED, TaskState.SKIPPED})


class TaskBoard:
    """Thread-safe task state machine with support for dynamic tasks and rework cycles."""

    def __init__(self):
        self._tasks: Dict[str, CrewTask] = {}
        self._states: Dict[str, TaskState] = {}
        self._results: Dict[str, TaskResult] = {}
        self._assignments: Dict[str, str] = {}    # task_id → worker_name
        self._rework_counts: Dict[str, int] = {}  # task_id → rework count
        self._lock = threading.RLock()

    # ── Task management ───────────────────────────────────────

    def add_task(self, task: CrewTask) -> None:
        with self._lock:
            self._tasks[task.id] = task
            self._states[task.id] = TaskState.PENDING
            self._rework_counts[task.id] = 0

    def add_tasks(self, tasks: List[CrewTask]) -> None:
        with self._lock:
            for task in tasks:
                self._tasks[task.id] = task
                self._states[task.id] = TaskState.PENDING
                self._rework_counts[task.id] = 0

    def get_task(self, task_id: str) -> Optional[CrewTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[CrewTask]:
        with self._lock:
            return list(self._tasks.values())

    def used_roles(self) -> Set[str]:
        """Return set of role names referenced by current tasks."""
        with self._lock:
            return {t.assigned_role for t in self._tasks.values()}

    # ── State transitions ─────────────────────────────────────

    def assign(self, task_id: str, worker: str) -> None:
        with self._lock:
            self._states[task_id] = TaskState.ASSIGNED
            self._assignments[task_id] = worker
            task = self._tasks.get(task_id)
            if task:
                task.assigned_worker = worker

    def mark_running(self, task_id: str) -> None:
        with self._lock:
            self._states[task_id] = TaskState.RUNNING

    def mark_done(self, task_id: str, result: TaskResult) -> None:
        with self._lock:
            self._states[task_id] = TaskState.DONE
            self._results[task_id] = result

    def mark_failed(self, task_id: str, result: TaskResult) -> None:
        with self._lock:
            self._states[task_id] = TaskState.FAILED
            self._results[task_id] = result

    def mark_in_review(self, task_id: str) -> None:
        with self._lock:
            self._states[task_id] = TaskState.IN_REVIEW

    def stash_result(self, task_id: str, result: TaskResult) -> None:
        """Store a result without changing task state (used during review)."""
        with self._lock:
            self._results[task_id] = result

    def request_rework(self, task_id: str) -> int:
        """Mark task for rework and return the current rework count."""
        with self._lock:
            self._rework_counts[task_id] = self._rework_counts.get(task_id, 0) + 1
            self._states[task_id] = TaskState.REWORK
            return self._rework_counts[task_id]

    # ── Queries ───────────────────────────────────────────────

    def get_assignable(self) -> List[CrewTask]:
        """Return tasks that are PENDING or REWORK and whose dependencies are satisfied.

        Tasks are sorted by priority: downstream dependency count (desc),
        then complexity (desc), so critical-path tasks are dispatched first.
        """
        with self._lock:
            assignable = []
            for task_id, task in self._tasks.items():
                state = self._states.get(task_id)
                if state not in (TaskState.PENDING, TaskState.REWORK):
                    continue
                deps_met = all(
                    self._states.get(dep) == TaskState.DONE
                    for dep in task.depends_on
                    if dep in self._tasks
                )
                if deps_met:
                    assignable.append(task)
            # Sort by priority: downstream count desc, then complexity desc
            assignable.sort(
                key=lambda t: (self._downstream_count(t.id), t.complexity),
                reverse=True,
            )
            return assignable

    def _downstream_count(self, task_id: str) -> int:
        """Count tasks transitively depending on this one (caller must hold _lock)."""
        count = 0
        visited: set = set()
        queue = [task_id]
        while queue:
            current = queue.pop()
            for tid, task in self._tasks.items():
                if tid in visited:
                    continue
                if current in task.depends_on:
                    visited.add(tid)
                    count += 1
                    queue.append(tid)
        return count

    def get_result(self, task_id: str) -> Optional[TaskResult]:
        with self._lock:
            return self._results.get(task_id)

    def get_context_for_task(self, task: CrewTask) -> str:
        """Build context string from completed dependency results."""
        with self._lock:
            source_ids = task.context_from if task.context_from else task.depends_on
            parts = []
            for tid in source_ids:
                result = self._results.get(tid)
                if result and result.status == "done":
                    parts.append(
                        f"--- Result from task '{tid}' ({result.role_name}) ---\n{result.output}"
                    )
            return "\n\n".join(parts)

    def all_resolved(self) -> bool:
        """True when every task is in a terminal state (DONE/FAILED/SKIPPED)."""
        with self._lock:
            return all(
                s in _TERMINAL_STATES for s in self._states.values()
            ) if self._states else False

    def get_skipped_tasks(self) -> List[CrewTask]:
        """Return tasks in SKIPPED state."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if self._states.get(t.id) == TaskState.SKIPPED
            ]

    def get_state(self, task_id: str) -> Optional[TaskState]:
        with self._lock:
            return self._states.get(task_id)

    def get_assignment(self, task_id: str) -> Optional[str]:
        """Return the worker instance name assigned to a task."""
        with self._lock:
            return self._assignments.get(task_id)

    # ── Downstream management ─────────────────────────────────

    def skip_downstream(self, task_id: str) -> None:
        """Recursively skip tasks that depend on a failed task."""
        with self._lock:
            visited: set = set()
            self._skip_downstream_iter(task_id, visited)

    def _skip_downstream_iter(self, failed_id: str, visited: set) -> None:
        """Iterative-safe downstream skip (caller must hold _lock)."""
        for task_id, task in self._tasks.items():
            if task_id in visited:
                continue
            if self._states.get(task_id) == TaskState.PENDING and failed_id in task.depends_on:
                self._states[task_id] = TaskState.SKIPPED
                visited.add(task_id)
                self._skip_downstream_iter(task_id, visited)
