"""SharedScratchpad: thread-safe key-value store for inter-agent knowledge sharing."""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .tasks import CrewTask


@dataclass
class ScratchEntry:
    """A single entry in the shared scratchpad."""

    key: str
    value: str
    author: str          # agent/worker name
    task_id: str = ""
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)


class SharedScratchpad:
    """Thread-safe key-value store for inter-agent knowledge sharing.

    Agents can write findings, intermediate results, or shared context
    that other agents can query by key or by tags.
    """

    def __init__(self):
        self._entries: Dict[str, ScratchEntry] = {}
        self._lock = threading.Lock()

    def write(
        self,
        key: str,
        value: str,
        author: str,
        task_id: str = "",
        tags: Optional[List[str]] = None,
    ) -> None:
        """Add or overwrite an entry in the scratchpad."""
        with self._lock:
            self._entries[key] = ScratchEntry(
                key=key,
                value=value,
                author=author,
                task_id=task_id,
                tags=tags or [],
            )

    def read(self, key: str) -> Optional[ScratchEntry]:
        """Get a single entry by key."""
        with self._lock:
            return self._entries.get(key)

    def query_by_tags(self, tags: Set[str], limit: int = 10) -> List[ScratchEntry]:
        """Find entries matching any of the given tags, most recent first."""
        with self._lock:
            matches = [
                entry for entry in self._entries.values()
                if tags & set(entry.tags)
            ]
        matches.sort(key=lambda e: e.timestamp, reverse=True)
        return matches[:limit]

    def get_relevant_for_task(self, task: CrewTask, max_chars: int = 8000) -> str:
        """Get entries from dependency tasks + role-tagged entries.

        Builds a context string from:
        1. Entries written by dependency tasks (by task_id)
        2. Entries tagged with the task's assigned role
        """
        with self._lock:
            dep_ids = set(task.context_from if task.context_from else task.depends_on)
            relevant: List[ScratchEntry] = []
            seen_keys: Set[str] = set()

            # Entries from dependency tasks
            for entry in self._entries.values():
                if entry.task_id in dep_ids and entry.key not in seen_keys:
                    relevant.append(entry)
                    seen_keys.add(entry.key)

            # Entries tagged with this task's role
            for entry in self._entries.values():
                if (task.assigned_role in entry.tags
                        and entry.key not in seen_keys):
                    relevant.append(entry)
                    seen_keys.add(entry.key)

        if not relevant:
            return ""

        relevant.sort(key=lambda e: e.timestamp)
        parts: List[str] = []
        total = 0
        for entry in relevant:
            chunk = f"[{entry.key}] (by {entry.author}): {entry.value}"
            if total + len(chunk) > max_chars:
                break
            parts.append(chunk)
            total += len(chunk)

        if not parts:
            return ""
        return "## Shared Knowledge\n" + "\n".join(parts)
