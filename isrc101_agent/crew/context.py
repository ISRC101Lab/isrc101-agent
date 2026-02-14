"""Shared token budget and crew-wide context accumulator."""

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


class SharedTokenBudget:
    """Thread-safe global token budget shared across all crew agents.

    Supports per-agent tracking: each agent has an independent budget
    (``per_agent_limit``) so one agent's consumption doesn't starve others.
    The global ``max_tokens`` ceiling acts as a safety cap.

    Enhanced with:
    - Role-based budget multipliers (e.g. reviewer gets 0.4x of per_agent_limit)
    - Threshold-based warning notifications
    - Budget reallocation from finished agents
    """

    def __init__(
        self,
        max_tokens: int = 200_000,
        per_agent_limit: int = 200_000,
        role_multipliers: Optional[Dict[str, float]] = None,
    ):
        self.max_tokens = max_tokens
        self.per_agent_limit = per_agent_limit
        self.role_multipliers = role_multipliers or {}
        self._used = 0
        self._agent_usage: Dict[str, int] = {}
        self._agent_limits: Dict[str, int] = {}       # computed per-agent limits
        self._warned_thresholds: Dict[str, Set[int]] = {}  # agent_id -> warned %s
        self._lock = threading.Lock()

    def register_agent(self, agent_id: str, role_name: str) -> int:
        """Compute and store per-agent limit using role multiplier.

        Returns the computed limit for the agent.
        """
        with self._lock:
            multiplier = self.role_multipliers.get(role_name, 1.0)
            limit = int(self.per_agent_limit * multiplier)
            self._agent_limits[agent_id] = limit
            self._warned_thresholds[agent_id] = set()
            return limit

    def get_agent_limit(self, agent_id: str) -> int:
        """Return the per-agent limit (registered or default)."""
        with self._lock:
            return self._agent_limits.get(agent_id, self.per_agent_limit)

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
            limit = self._agent_limits.get(agent_id, self.per_agent_limit)
            return self._agent_usage.get(agent_id, 0) >= limit

    def agent_used(self, agent_id: str) -> int:
        """Return total tokens consumed by a specific agent."""
        with self._lock:
            return self._agent_usage.get(agent_id, 0)

    def check_warnings(self, agent_id: str, thresholds: List[int]) -> Optional[int]:
        """Return threshold percentage if a new threshold was crossed, else None.

        Example: thresholds=[50, 75, 90] — returns 50 the first time agent
        crosses 50% of its budget, 75 for 75%, etc.
        """
        with self._lock:
            limit = self._agent_limits.get(agent_id, self.per_agent_limit)
            if limit <= 0:
                return None
            used = self._agent_usage.get(agent_id, 0)
            pct = int(used / limit * 100)
            warned = self._warned_thresholds.get(agent_id, set())
            for t in sorted(thresholds):
                if pct >= t and t not in warned:
                    warned.add(t)
                    self._warned_thresholds[agent_id] = warned
                    return t
            return None

    def reallocate_from(self, agent_id: str) -> int:
        """Reclaim unused budget from a finished agent and add to global pool.

        Returns the amount reclaimed.
        """
        with self._lock:
            limit = self._agent_limits.get(agent_id, self.per_agent_limit)
            used = self._agent_usage.get(agent_id, 0)
            unused = max(0, limit - used)
            if unused > 0:
                # Increase global ceiling by the reclaimed amount
                self.max_tokens += unused
            return unused


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
