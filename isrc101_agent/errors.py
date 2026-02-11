"""Structured error types for the agent system."""


class AgentError(Exception):
    """Base error for all agent operations."""
    pass


class ToolError(AgentError):
    """Error raised during tool execution."""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"{tool_name} error: {message}")


class ShellBlockedError(AgentError):
    """Raised when a shell command is blocked by safety guards."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Blocked: {reason}")


class ShellTimeoutError(AgentError):
    """Raised when a shell command exceeds its timeout."""

    def __init__(self, timeout: int):
        self.timeout = timeout
        super().__init__(f"Timed out after {timeout}s")


class WebAccessDisabledError(AgentError):
    """Raised when web access is attempted while disabled."""

    def __init__(self):
        super().__init__("Web access is disabled. Use /web to enable it.")
