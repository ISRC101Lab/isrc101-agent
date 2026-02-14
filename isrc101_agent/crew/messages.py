"""Message types and message bus for crew inter-agent communication."""

import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageType(Enum):
    TASK_ASSIGNED = "task_assigned"      # coordinator → worker
    TASK_COMPLETE = "task_complete"      # worker → coordinator
    TASK_FAILED = "task_failed"          # worker → coordinator
    REVIEW_REQUEST = "review_request"    # coordinator → reviewer worker
    REVIEW_PASSED = "review_passed"      # worker → coordinator
    REWORK_NEEDED = "rework_needed"      # worker → coordinator (reviewer found issues)
    REWORK_ASSIGNED = "rework_assigned"  # coordinator → coder worker
    STATUS_UPDATE = "status_update"      # worker → coordinator (progress)
    SCRATCHPAD_WRITE = "scratchpad_write"  # worker → coordinator (knowledge sharing)
    SHUTDOWN = "shutdown"                # coordinator → all workers


@dataclass
class CrewMessage:
    type: MessageType
    sender: str               # "coordinator" or worker name
    recipient: str            # worker name or "coordinator"
    task_id: str = ""
    content: str = ""         # main text (task description, result, review feedback)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# Maximum number of messages kept in history (ring buffer)
_MAX_HISTORY = 200


class MessageBus:
    """Thread-safe message bus backed by queue.Queue per recipient."""

    def __init__(self, max_history: int = _MAX_HISTORY):
        self._coordinator_inbox: queue.Queue[CrewMessage] = queue.Queue()
        self._worker_inboxes: Dict[str, queue.Queue[CrewMessage]] = {}
        self._lock = threading.Lock()
        self._history: deque[CrewMessage] = deque(maxlen=max_history)

    def register_worker(self, name: str) -> None:
        with self._lock:
            self._worker_inboxes[name] = queue.Queue()

    def unregister_worker(self, name: str) -> None:
        with self._lock:
            self._worker_inboxes.pop(name, None)

    def send_to_coordinator(self, msg: CrewMessage) -> None:
        with self._lock:
            self._history.append(msg)
        self._coordinator_inbox.put(msg)

    def send_to_worker(self, msg: CrewMessage) -> None:
        with self._lock:
            self._history.append(msg)
            inbox = self._worker_inboxes.get(msg.recipient)
        if inbox:
            inbox.put(msg)

    def broadcast_to_workers(self, msg: CrewMessage) -> None:
        with self._lock:
            self._history.append(msg)
            inboxes = list(self._worker_inboxes.values())
        for inbox in inboxes:
            inbox.put(msg)

    def coordinator_recv(self, timeout: float = 30.0) -> Optional[CrewMessage]:
        try:
            return self._coordinator_inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def worker_recv(self, name: str, timeout: float = 30.0) -> Optional[CrewMessage]:
        with self._lock:
            inbox = self._worker_inboxes.get(name)
        if not inbox:
            return None
        try:
            return inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_history(self) -> List[CrewMessage]:
        """Return a snapshot of recent message history."""
        with self._lock:
            return list(self._history)

    def queue_depth(self, worker_name: str) -> int:
        """Return approximate pending message count for a worker."""
        with self._lock:
            inbox = self._worker_inboxes.get(worker_name)
        return inbox.qsize() if inbox else 0

    def coordinator_queue_depth(self) -> int:
        """Return approximate pending message count for coordinator."""
        return self._coordinator_inbox.qsize()
