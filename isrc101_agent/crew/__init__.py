"""Multi-agent crew collaboration system."""

from .roles import RoleSpec, create_agent_for_role
from .tasks import CrewTask, TaskResult
from .context import SharedTokenBudget, CrewContext
from .messages import MessageBus, MessageType, CrewMessage
from .board import TaskBoard, TaskState
from .worker import AgentWorker
from .coordinator import Coordinator
from .crew import Crew

__all__ = [
    "RoleSpec",
    "create_agent_for_role",
    "CrewTask",
    "TaskResult",
    "SharedTokenBudget",
    "CrewContext",
    "MessageBus",
    "MessageType",
    "CrewMessage",
    "TaskBoard",
    "TaskState",
    "AgentWorker",
    "Coordinator",
    "Crew",
]
