"""AgentWorker: long-lived worker thread that processes messages from the bus."""

import logging
import threading
import time

from .messages import MessageBus, CrewMessage, MessageType
from .roles import RoleSpec, create_agent_for_role
from .context import SharedTokenBudget

_log = logging.getLogger(__name__)

# Interval for STATUS_UPDATE messages while a task is running (seconds)
_STATUS_UPDATE_INTERVAL = 15.0


class AgentWorker(threading.Thread):
    """Long-lived daemon thread — blocks on its inbox and executes tasks/reviews."""

    def __init__(
        self,
        name: str,
        role: RoleSpec,
        bus: MessageBus,
        config,
        project_root: str,
        budget: SharedTokenBudget,
    ):
        super().__init__(name=f"crew-{name}", daemon=True)
        self.worker_name = name
        self.role = role
        self.bus = bus
        self.config = config
        self.project_root = project_root
        self.budget = budget
        self._shutdown = threading.Event()

    def run(self):
        self.bus.register_worker(self.worker_name)
        try:
            while not self._shutdown.is_set():
                msg = self.bus.worker_recv(self.worker_name, timeout=5.0)
                if msg is None:
                    continue
                if msg.type == MessageType.SHUTDOWN:
                    break
                if msg.type in (MessageType.TASK_ASSIGNED, MessageType.REWORK_ASSIGNED):
                    self._handle_task(msg)
                elif msg.type == MessageType.REVIEW_REQUEST:
                    self._handle_review(msg)
        finally:
            self.bus.unregister_worker(self.worker_name)

    def _handle_task(self, msg: CrewMessage):
        t0 = time.perf_counter()
        tokens = 0
        try:
            agent = create_agent_for_role(
                self.role, self.config, self.project_root, self.budget,
            )
        except Exception as e:
            _log.error("Worker %s: agent creation failed: %s", self.worker_name, e)
            self.bus.send_to_coordinator(CrewMessage(
                type=MessageType.TASK_FAILED,
                sender=self.worker_name,
                recipient="coordinator",
                task_id=msg.task_id,
                content=f"Agent creation failed: {e}",
                metadata={"tokens": 0, "elapsed": time.perf_counter() - t0},
            ))
            return

        user_input = msg.content
        rework_context = msg.metadata.get("rework_feedback", "")
        if rework_context:
            user_input += f"\n\n## Review Feedback (please address):\n{rework_context}"

        previous_output = msg.metadata.get("previous_output", "")
        if previous_output:
            user_input += f"\n\n## Your Previous Output:\n{previous_output}"

        # Spawn a daemon thread that sends STATUS_UPDATE every 15s while task runs
        task_done = threading.Event()

        def _status_updater():
            while not task_done.wait(timeout=_STATUS_UPDATE_INTERVAL):
                elapsed = time.perf_counter() - t0
                tok = getattr(agent, "total_tokens", 0)
                self.bus.send_to_coordinator(CrewMessage(
                    type=MessageType.STATUS_UPDATE,
                    sender=self.worker_name,
                    recipient="coordinator",
                    task_id=msg.task_id,
                    metadata={"elapsed": elapsed, "tokens": tok},
                ))

        updater = threading.Thread(
            target=_status_updater, daemon=True,
            name=f"status-{self.worker_name}",
        )
        updater.start()

        try:
            output = agent.chat(user_input)
            task_done.set()
            elapsed = time.perf_counter() - t0
            self.bus.send_to_coordinator(CrewMessage(
                type=MessageType.TASK_COMPLETE,
                sender=self.worker_name,
                recipient="coordinator",
                task_id=msg.task_id,
                content=output or "",
                metadata={"tokens": agent.total_tokens, "elapsed": elapsed},
            ))
        except Exception as e:
            task_done.set()
            elapsed = time.perf_counter() - t0
            self.bus.send_to_coordinator(CrewMessage(
                type=MessageType.TASK_FAILED,
                sender=self.worker_name,
                recipient="coordinator",
                task_id=msg.task_id,
                content=str(e),
                metadata={"tokens": agent.total_tokens, "elapsed": elapsed},
            ))

    def _handle_review(self, msg: CrewMessage):
        t0 = time.perf_counter()
        try:
            agent = create_agent_for_role(
                self.role, self.config, self.project_root, self.budget,
            )
        except Exception as e:
            _log.error("Worker %s: reviewer agent creation failed: %s", self.worker_name, e)
            # Cannot review → pass through so pipeline isn't blocked
            self.bus.send_to_coordinator(CrewMessage(
                type=MessageType.REVIEW_PASSED,
                sender=self.worker_name,
                recipient="coordinator",
                task_id=msg.task_id,
                content=f"Review skipped (agent creation failed): {e}",
                metadata={"tokens": 0, "elapsed": time.perf_counter() - t0,
                          "review_error": True},
            ))
            return

        review_prompt = (
            f"Review the following output from a coding task.\n\n"
            f"## Task Description:\n{msg.metadata.get('task_description', '')}\n\n"
            f"## Code/Output to Review:\n{msg.content}\n\n"
            f"If the output is acceptable, respond with exactly: LGTM\n"
            f"If issues found, describe them clearly for the author to fix."
        )
        try:
            output = agent.chat(review_prompt)
            elapsed = time.perf_counter() - t0
            is_pass = output and output.strip().upper().startswith("LGTM")
            self.bus.send_to_coordinator(CrewMessage(
                type=MessageType.REVIEW_PASSED if is_pass else MessageType.REWORK_NEEDED,
                sender=self.worker_name,
                recipient="coordinator",
                task_id=msg.task_id,
                content=output or "",
                metadata={"tokens": agent.total_tokens, "elapsed": elapsed},
            ))
        except Exception as e:
            # Review failure → pass through with error flag so coordinator knows
            self.bus.send_to_coordinator(CrewMessage(
                type=MessageType.REVIEW_PASSED,
                sender=self.worker_name,
                recipient="coordinator",
                task_id=msg.task_id,
                content=f"Review error: {e}",
                metadata={"tokens": agent.total_tokens, "elapsed": time.perf_counter() - t0,
                          "review_error": True},
            ))

    def request_shutdown(self):
        self._shutdown.set()
