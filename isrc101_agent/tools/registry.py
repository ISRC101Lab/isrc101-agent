"""Tool registry: dispatches tool calls to implementations."""
from typing import Any, Dict
from .file_ops import FileOps, FileOperationError
from .shell import ShellExecutor
from .git_ops import GitOps
from .schemas import get_tools_for_mode

class ToolRegistry:
    def __init__(self, project_root: str, blocked_commands: list = None,
                 command_timeout: int = 30, commit_prefix: str = "isrc101: "):
        self.file_ops = FileOps(project_root)
        self.shell = ShellExecutor(project_root, blocked_commands, command_timeout)
        self.git = GitOps(project_root, commit_prefix=commit_prefix)
        self._mode = "code"

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        self._mode = value

    @property
    def schemas(self):
        return get_tools_for_mode(self._mode)

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        try:
            match tool_name:
                case "read_file":
                    return self.file_ops.read_file(arguments["path"],
                        arguments.get("start_line"), arguments.get("end_line"))
                case "create_file":
                    return self.file_ops.create_file(arguments["path"], arguments["content"])
                case "write_file":
                    return self.file_ops.write_file(arguments["path"], arguments["content"])
                case "str_replace":
                    return self.file_ops.str_replace(arguments["path"],
                        arguments["old_str"], arguments["new_str"])
                case "delete_file":
                    return self.file_ops.delete_file(arguments["path"])
                case "list_directory":
                    return self.file_ops.list_directory(
                        arguments.get("path", "."), arguments.get("max_depth", 3))
                case "search_files":
                    return self.file_ops.search_files(arguments["pattern"],
                        arguments.get("path", "."), arguments.get("include"))
                case "bash":
                    return self.shell.execute(arguments["command"])
                case _:
                    return f"Unknown tool: {tool_name}"
        except FileOperationError as e:
            return f"Error: {e}"
        except KeyError as e:
            return f"Missing argument: {e}"
        except Exception as e:
            return f"{tool_name} error: {type(e).__name__}: {e}"

    WRITE_TOOLS = {"create_file", "write_file", "str_replace", "delete_file"}
    CONFIRM_TOOLS = {"bash"}

    @classmethod
    def needs_confirmation(cls, tool_name: str) -> bool:
        return tool_name in cls.CONFIRM_TOOLS
