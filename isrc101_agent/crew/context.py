"""Shared token budget and crew-wide context accumulator."""

import threading
from dataclasses import dataclass, field
from typing import Dict, List


class SharedTokenBudget:
    """Thread-safe global token budget shared across all crew agents.

    Supports per-agent tracking: each agent has an independent budget
    (``per_agent_limit``) so one agent's consumption doesn't starve others.
    The global ``max_tokens`` ceiling acts as a safety cap.
    """

    def __init__(self, max_tokens: int = 200_000, per_agent_limit: int = 200_000):
        self.max_tokens = max_tokens
        self.per_agent_limit = per_agent_limit
        self._used = 0
        self._agent_usage: Dict[str, int] = {}
        self._lock = threading.Lock()

    def consume(self, tokens: int, agent_id: str = "") -> None:
        with self._lock:
            self._used += tokens
            if agent_id:
                self._agent_usage[agent_id] = self._agent_usage.get(agent_id, 0) + tokens

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_tokens - self._used)

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def is_exhausted(self) -> bool:
        with self._lock:
            return self._used >= self.max_tokens

    def is_agent_exhausted(self, agent_id: str) -> bool:
        """Check if a specific agent has hit its per-agent limit or the global ceiling."""
        with self._lock:
            if self._used >= self.max_tokens:
                return True
            return self._agent_usage.get(agent_id, 0) >= self.per_agent_limit

    def agent_used(self, agent_id: str) -> int:
        """Return total tokens consumed by a specific agent."""
        with self._lock:
            return self._agent_usage.get(agent_id, 0)


@dataclass
class CrewContext:
    """Accumulated context shared between crew agents during execution."""

    results: Dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_result(self, task_id: str, output: str) -> None:
        with self._lock:
            self.results[task_id] = output

    def get_context_for(self, task_ids: List[str]) -> str:
        """Build context string from completed task results."""
        with self._lock:
            parts = []
            for tid in task_ids:
                if tid in self.results:
                    parts.append(f"--- Result from task '{tid}' ---\n{self.results[tid]}")
            return "\n\n".join(parts)
