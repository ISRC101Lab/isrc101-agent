"""Shared token budget and crew-wide context accumulator."""

import threading
from dataclasses import dataclass, field
from typing import Dict, List


class SharedTokenBudget:
    """Thread-safe global token budget shared across all crew agents."""

    def __init__(self, max_tokens: int = 200_000):
        self.max_tokens = max_tokens
        self._used = 0
        self._lock = threading.Lock()

    def consume(self, tokens: int) -> None:
        with self._lock:
            self._used += tokens

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
