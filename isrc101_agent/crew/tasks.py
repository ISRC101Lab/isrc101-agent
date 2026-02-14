"""Task definitions for crew execution."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CrewTask:
    """A single task in the crew execution plan."""

    id: str
    description: str
    assigned_role: str
    depends_on: List[str] = field(default_factory=list)
    context_from: List[str] = field(default_factory=list)
    max_retries: int = 1
    status: str = "pending"  # pending | running | done | failed | skipped
    review_of: Optional[str] = None       # if review task, points to reviewed task_id
    assigned_worker: Optional[str] = None  # actual worker name assigned


@dataclass
class TaskResult:
    """Result of a single task execution."""

    task_id: str
    role_name: str
    status: str  # "done" | "failed"
    output: str
    tokens_used: int
    elapsed_seconds: float
    error: Optional[str] = None
