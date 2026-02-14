"""Coordinator: decomposes requests, event-loop execution, synthesizes results."""

import json
import re
import time
from collections import Counter
from typing import Dict, List, Optional, Set

from rich.console import Console

from ..config import Config
from ..llm import LLMAdapter, build_system_prompt
from ..logger import get_logger
from .board import TaskBoard, TaskState
from .context import SharedTokenBudget, CrewContext
from .messages import MessageBus, CrewMessage, MessageType
from .roles import RoleSpec, load_roles_from_config
from .tasks import CrewTask, TaskResult
from .rendering import CrewRenderer
from .worker import AgentWorker

_log = get_logger(__name__)

_JSON_ARRAY_RE = re.compile(r'```(?:\w*)\s*\n(.*?)```', re.DOTALL)

DECOMPOSE_PROMPT = """\
You are a task coordinator for a multi-agent coding crew.

Given the user's request and the available specialist roles, decompose the request
into a list of concrete tasks. Each task should be assigned to exactly one role.

Available roles:
{roles_description}

Output ONLY a JSON array of task objects. Each object must have:
- "id": short identifier (e.g. "t1", "t2")
- "description": what the agent should do (be specific and actionable)
- "assigned_role": one of the available role names
- "depends_on": array of task IDs that must complete first (empty if independent)
- "context_from": array of task IDs whose results should be passed as context (optional, defaults to depends_on)

Rules:
- Tasks that can run independently should have empty depends_on
- Order tasks logically: research before coding, coding before review, review before testing
- Keep tasks focused — each task should be completable by a single agent
- Include 2-6 tasks for typical requests
- Do NOT include any text outside the JSON array

User request: {request}
"""

SYNTHESIZE_PROMPT = """\
You are synthesizing the results from a multi-agent crew execution.

The original user request was:
{request}

Here are the results from each agent:

{results}

Provide a unified, coherent summary of what was accomplished. Include:
1. What was done (key changes, findings)
2. Any issues or warnings from the agents
3. Suggested next steps if applicable

Be concise but complete.
"""

# Default per-task timeout (seconds). 0 = no timeout.
_DEFAULT_TASK_TIMEOUT = 300.0


class Coordinator:
    """Event-driven coordinator: decomposes, dispatches via MessageBus, synthesizes.

    Supports multiple worker instances per role for same-role parallel execution.
    """

    def __init__(
        self,
        config: Config,
        console: Console,
        max_parallel: int = 2,
        token_budget: int = 200_000,
        auto_review: bool = True,
        max_rework: int = 2,
        message_timeout: float = 60.0,
        task_timeout: float = _DEFAULT_TASK_TIMEOUT,
    ):
        self.config = config
        self.console = console
        self.max_parallel = max_parallel
        self.auto_review = auto_review
        self.max_rework = max_rework
        self.message_timeout = message_timeout
        self.task_timeout = task_timeout
        self.budget = SharedTokenBudget(token_budget)
        self.crew_context = CrewContext()
        self.renderer = CrewRenderer(console)
        self.roles = load_roles_from_config(config)
        self._project_root = config.project_root or "."
        self.bus = MessageBus()
        self.board = TaskBoard()
        self._workers: Dict[str, AgentWorker] = {}           # instance_name -> worker
        self._role_instances: Dict[str, List[str]] = {}       # role_name -> [instance_names]
        self._busy_workers: Set[str] = set()                  # instance names currently executing
        self._task_start_times: Dict[str, float] = {}         # task_id -> monotonic start

    # ── Public API ────────────────────────────────────────────

    def run(self, request: str) -> str:
        """Full crew execution: decompose -> event loop -> synthesize."""
        # Phase 1: Decompose
        self.console.print()
        tasks = self._decompose(request)
        if not tasks:
            return "Failed to decompose the request into tasks."

        self.board.add_tasks(tasks)
        self.renderer.render_decomposition(tasks)

        # Phase 2: Start workers + event loop
        self._start_workers()
        try:
            self._event_loop()
        finally:
            self._shutdown_workers()

        # Phase 3: Synthesize
        results = [
            self.board.get_result(t.id)
            for t in tasks
            if self.board.get_result(t.id)
        ]
        synthesis = self._synthesize(request, results)

        # Render summary
        skipped = self.board.get_skipped_tasks()
        self.renderer.render_summary(results, skipped if skipped else None)

        return synthesis

    # ── Decomposition ─────────────────────────────────────────

    def _decompose(self, request: str) -> List[CrewTask]:
        """Use LLM to decompose the request into structured tasks."""
        roles_desc = "\n".join(
            f"- {name}: {role.description}"
            for name, role in self.roles.items()
        )

        prompt = DECOMPOSE_PROMPT.format(
            roles_description=roles_desc,
            request=request,
        )

        preset = self.config.get_active_preset()
        llm = LLMAdapter(**preset.get_llm_kwargs())
        system = build_system_prompt(mode="ask")

        try:
            response = llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as e:
            _log.error("Decomposition LLM call failed: %s", e)
            self.console.print(f"  [red]Decomposition failed: {e}[/red]")
            return []

        if response.usage:
            self.budget.consume(response.usage.get("total_tokens", 0))

        return self._parse_tasks(response.content or "")

    def _parse_tasks(self, raw: str) -> List[CrewTask]:
        """Parse JSON task list from LLM output."""
        text = raw.strip()

        m = _JSON_ARRAY_RE.search(text)
        if m:
            text = m.group(1).strip()

        if not text.startswith('['):
            start = text.find('[')
            end = text.rfind(']')
            if start >= 0 and end > start:
                text = text[start:end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            _log.error("Failed to parse task JSON: %s", text[:200])
            self.console.print("  [red]Failed to parse task decomposition[/red]")
            return []

        if not isinstance(data, list):
            return []

        tasks = []
        for item in data:
            if not isinstance(item, dict):
                continue
            task_id = item.get("id", f"t{len(tasks)+1}")
            role_name = item.get("assigned_role", "coder")
            if role_name not in self.roles:
                role_name = "coder"
            tasks.append(CrewTask(
                id=task_id,
                description=item.get("description", ""),
                assigned_role=role_name,
                depends_on=item.get("depends_on", []),
                context_from=item.get("context_from", []),
            ))

        return tasks

    # ── Worker lifecycle ──────────────────────────────────────

    def _start_workers(self):
        """Start worker instances per role, scaling up to max_parallel per role."""
        # Count tasks per role to determine instance count
        tasks_per_role: Counter = Counter()
        for task in self.board.get_all_tasks():
            tasks_per_role[task.assigned_role] += 1

        used_roles = self.board.used_roles()

        for role_name in used_roles:
            role = self.roles.get(role_name)
            if not role:
                continue
            n_tasks = tasks_per_role.get(role_name, 1)
            n_instances = min(n_tasks, self.max_parallel)
            self._spawn_role_instances(role_name, role, n_instances)

        # Auto-review: ensure at least one reviewer instance exists
        if (self.auto_review
                and "reviewer" not in self._role_instances
                and "reviewer" in self.roles
                and "coder" in used_roles):
            role = self.roles["reviewer"]
            self._spawn_role_instances("reviewer", role, 1)

    def _spawn_role_instances(self, role_name: str, role: RoleSpec, count: int):
        """Create N worker instances for a single role."""
        instances = []
        for i in range(count):
            instance_name = f"{role_name}-{i}" if count > 1 else role_name
            worker = AgentWorker(
                name=instance_name,
                role=role,
                bus=self.bus,
                config=self.config,
                project_root=self._project_root,
                budget=self.budget,
            )
            worker.start()
            self._workers[instance_name] = worker
            instances.append(instance_name)
        self._role_instances[role_name] = instances

    def _shutdown_workers(self):
        """Broadcast SHUTDOWN and join all worker threads."""
        shutdown_msg = CrewMessage(
            type=MessageType.SHUTDOWN,
            sender="coordinator",
            recipient="all",
        )
        self.bus.broadcast_to_workers(shutdown_msg)
        for w in self._workers.values():
            w.request_shutdown()
        for w in self._workers.values():
            w.join(timeout=10.0)
            if w.is_alive():
                _log.warning("Worker %s did not shut down within timeout", w.worker_name)

    # ── Instance scheduling ───────────────────────────────────

    def _get_idle_instance(self, role_name: str) -> Optional[str]:
        """Find an idle worker instance for the given role. Returns None if all busy."""
        for instance in self._role_instances.get(role_name, []):
            if instance not in self._busy_workers:
                return instance
        return None

    def _get_any_instance(self, role_name: str) -> Optional[str]:
        """Get any instance for a role (prefer idle, fall back to least-loaded)."""
        idle = self._get_idle_instance(role_name)
        if idle:
            return idle
        instances = self._role_instances.get(role_name, [])
        if not instances:
            return None
        # Fall back to first instance (message will queue)
        return instances[0]

    # ── Event loop ────────────────────────────────────────────

    def _event_loop(self):
        """Main loop: dispatch ready tasks, process incoming messages."""
        self._dispatch_ready_tasks()

        while not self.board.all_resolved():
            if self.budget.is_exhausted():
                self.console.print(
                    f"  [yellow]Token budget exhausted "
                    f"({self.budget.used:,}/{self.budget.max_tokens:,}). "
                    f"Stopping.[/yellow]"
                )
                break

            msg = self.bus.coordinator_recv(timeout=self.message_timeout)
            if msg is None:
                self._check_task_timeouts()
                continue

            if msg.type == MessageType.TASK_COMPLETE:
                self._on_task_complete(msg)
            elif msg.type == MessageType.TASK_FAILED:
                self._on_task_failed(msg)
            elif msg.type == MessageType.REVIEW_PASSED:
                self._on_review_passed(msg)
            elif msg.type == MessageType.REWORK_NEEDED:
                self._on_rework_needed(msg)
            elif msg.type == MessageType.STATUS_UPDATE:
                pass

            self._dispatch_ready_tasks()

    def _dispatch_ready_tasks(self):
        """Assign ready tasks to idle worker instances of the matching role."""
        for task in self.board.get_assignable():
            instance = self._get_idle_instance(task.assigned_role)
            if instance is None:
                continue  # All instances busy, will retry next tick
            self._busy_workers.add(instance)
            self.board.assign(task.id, instance)
            self._task_start_times[task.id] = time.monotonic()
            context = self.board.get_context_for_task(task)
            self.bus.send_to_worker(CrewMessage(
                type=MessageType.TASK_ASSIGNED,
                sender="coordinator",
                recipient=instance,
                task_id=task.id,
                content=task.description + ("\n\n## Context from previous tasks:\n" + context if context else ""),
            ))
            self.renderer.render_task_start(task)

    def _check_task_timeouts(self):
        """Fail tasks that have exceeded the task timeout."""
        if self.task_timeout <= 0:
            return
        now = time.monotonic()
        for task_id, start in list(self._task_start_times.items()):
            if now - start <= self.task_timeout:
                continue
            state = self.board.get_state(task_id)
            if state in (TaskState.ASSIGNED, TaskState.RUNNING, TaskState.IN_REVIEW):
                # Free the worker instance
                assignment = self.board.get_assignment(task_id)
                if assignment:
                    self._busy_workers.discard(assignment)
                result = TaskResult(
                    task_id=task_id, role_name="coordinator",
                    status="failed", output="",
                    error=f"Task timed out after {self.task_timeout:.0f}s",
                    tokens_used=0, elapsed_seconds=now - start,
                )
                self.board.mark_failed(task_id, result)
                self.board.skip_downstream(task_id)
                self.renderer.render_task_failed(result)
                del self._task_start_times[task_id]

    # ── Message handlers ──────────────────────────────────────

    def _on_task_complete(self, msg: CrewMessage):
        self._busy_workers.discard(msg.sender)
        self._task_start_times.pop(msg.task_id, None)

        task = self.board.get_task(msg.task_id)
        role_name = task.assigned_role if task else msg.sender

        result = TaskResult(
            task_id=msg.task_id,
            role_name=role_name,
            status="done",
            output=msg.content,
            tokens_used=msg.metadata.get("tokens", 0),
            elapsed_seconds=msg.metadata.get("elapsed", 0.0),
        )

        # Auto-review coder output
        if (self.auto_review
                and task
                and task.assigned_role == "coder"
                and "reviewer" in self._role_instances):
            self.board.mark_in_review(msg.task_id)
            self.board.stash_result(msg.task_id, result)
            self._task_start_times[msg.task_id] = time.monotonic()

            reviewer_instance = self._get_any_instance("reviewer")
            if reviewer_instance:
                self._busy_workers.add(reviewer_instance)
                self.bus.send_to_worker(CrewMessage(
                    type=MessageType.REVIEW_REQUEST,
                    sender="coordinator",
                    recipient=reviewer_instance,
                    task_id=msg.task_id,
                    content=msg.content,
                    metadata={"task_description": task.description},
                ))
            self.renderer.render_review_created(msg.task_id)
        else:
            self.board.mark_done(msg.task_id, result)
            self.crew_context.add_result(msg.task_id, result.output)
            self.renderer.render_task_done(result)

    def _on_task_failed(self, msg: CrewMessage):
        self._busy_workers.discard(msg.sender)
        self._task_start_times.pop(msg.task_id, None)

        task = self.board.get_task(msg.task_id)
        role_name = task.assigned_role if task else msg.sender

        result = TaskResult(
            task_id=msg.task_id,
            role_name=role_name,
            status="failed",
            output="",
            error=msg.content,
            tokens_used=msg.metadata.get("tokens", 0),
            elapsed_seconds=msg.metadata.get("elapsed", 0.0),
        )
        self.board.mark_failed(msg.task_id, result)
        self.board.skip_downstream(msg.task_id)
        self.renderer.render_task_failed(result)

    def _on_review_passed(self, msg: CrewMessage):
        self._busy_workers.discard(msg.sender)
        self._task_start_times.pop(msg.task_id, None)
        if msg.metadata.get("review_error"):
            _log.warning("Review for task %s passed due to error: %s",
                         msg.task_id, msg.content[:200])
        result = self.board.get_result(msg.task_id)
        if result:
            self.board.mark_done(msg.task_id, result)
            self.crew_context.add_result(msg.task_id, result.output)
            self.renderer.render_review_passed(msg.task_id)
            self.renderer.render_task_done(result)

    def _on_rework_needed(self, msg: CrewMessage):
        self._busy_workers.discard(msg.sender)

        rework_count = self.board.request_rework(msg.task_id)
        if rework_count > self.max_rework:
            self._task_start_times.pop(msg.task_id, None)
            result = self.board.get_result(msg.task_id)
            if result:
                self.board.mark_done(msg.task_id, result)
                self.crew_context.add_result(msg.task_id, result.output)
                self.renderer.render_rework_limit(msg.task_id)
            return

        task = self.board.get_task(msg.task_id)
        previous_result = self.board.get_result(msg.task_id)
        if task and previous_result:
            self.renderer.render_rework_requested(msg.task_id, rework_count)

            coder_instance = self._get_idle_instance(task.assigned_role)
            if coder_instance:
                self._task_start_times[msg.task_id] = time.monotonic()
                self._busy_workers.add(coder_instance)
                self.board.assign(msg.task_id, coder_instance)
                self.bus.send_to_worker(CrewMessage(
                    type=MessageType.REWORK_ASSIGNED,
                    sender="coordinator",
                    recipient=coder_instance,
                    task_id=msg.task_id,
                    content=task.description,
                    metadata={
                        "rework_feedback": msg.content,
                        "previous_output": previous_result.output,
                    },
                ))

    # ── Synthesis ─────────────────────────────────────────────

    def _synthesize(self, request: str, results: List[TaskResult]) -> str:
        """Synthesize all task results into a unified response."""
        if not results:
            return "No tasks were completed."

        done_results = [r for r in results if r.status == "done"]
        if not done_results:
            return "All tasks failed. Check the summary above for details."

        results_text = "\n\n".join(
            f"### Task {r.task_id} ({r.role_name}):\n{r.output}"
            for r in done_results
        )

        prompt = SYNTHESIZE_PROMPT.format(
            request=request,
            results=results_text,
        )

        preset = self.config.get_active_preset()
        llm = LLMAdapter(**preset.get_llm_kwargs())
        system = build_system_prompt(mode="ask")

        try:
            response = llm.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as e:
            _log.error("Synthesis LLM call failed: %s", e)
            return results_text

        if response.usage:
            self.budget.consume(response.usage.get("total_tokens", 0))

        return response.content or results_text
