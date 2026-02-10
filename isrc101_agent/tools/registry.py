"""Tool registry: dict-based dispatch replaces manual match/case."""
from typing import Any, Callable, Dict, List, Set
from .file_ops import FileOps, FileOperationError
from .shell import ShellExecutor
from .git_ops import GitOps
from .web_ops import WebOps, WebOpsError


class _ToolEntry:
    """Single tool registration: handler + schema + metadata."""
    __slots__ = ("handler", "schema", "mode", "writes", "confirm")

    def __init__(self, handler: Callable, schema: dict,
                 mode: str = "all", writes: bool = False, confirm: bool = False):
        self.handler = handler
        self.schema = schema
        self.mode = mode
        self.writes = writes
        self.confirm = confirm


def _schema(name: str, description: str, properties: dict,
            required: list) -> dict:
    """Build an OpenAI-compatible function schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# Shorthand helpers for property definitions
_S = lambda desc, **kw: {"type": "string", "description": desc, **kw}
_I = lambda desc, **kw: {"type": "integer", "description": desc, **kw}


class ToolRegistry:
    def __init__(self, project_root: str, blocked_commands: list = None,
                 command_timeout: int = 30, commit_prefix: str = "isrc101: ",
                 tavily_api_key: str = None):
        self.file_ops = FileOps(project_root)
        self.shell = ShellExecutor(project_root, blocked_commands, command_timeout)
        self.git = GitOps(project_root, commit_prefix=commit_prefix)
        self.web = WebOps(tavily_api_key=tavily_api_key)
        self._web_enabled = False
        self.mode = "agent"
        self._tools: Dict[str, _ToolEntry] = {}
        self._register_tools()

    def _register_tools(self):
        """Register all tools — single source of truth for schema + handler."""
        f = self.file_ops
        T = _ToolEntry
        S = _schema

        # ── File operations ──
        self._tools["read_file"] = T(
            handler=lambda **a: f.read_file(a["path"], a.get("start_line"), a.get("end_line")),
            schema=S("read_file",
                     "Read file contents with line numbers. Supports optional line range.",
                     {"path": _S("File path relative to project root"),
                      "start_line": _I("Start line (1-indexed)"),
                      "end_line": _I("End line (inclusive)")},
                     ["path"]),
            mode="all",
        )
        self._tools["create_file"] = T(
            handler=lambda **a: f.create_file(a["path"], a["content"]),
            schema=S("create_file", "Create a new file. Fails if file exists.",
                     {"path": _S("File path to create"),
                      "content": _S("Full file content")},
                     ["path", "content"]),
            mode="code", writes=True,
        )
        self._tools["str_replace"] = T(
            handler=lambda **a: f.str_replace(a["path"], a["old_str"], a["new_str"]),
            schema=S("str_replace",
                     "Replace a unique string in a file. old_str must appear EXACTLY ONCE.",
                     {"path": _S("File path to edit"),
                      "old_str": _S("Exact string to find (must be unique)"),
                      "new_str": _S("Replacement string (empty = delete)")},
                     ["path", "old_str", "new_str"]),
            mode="code", writes=True,
        )
        self._tools["write_file"] = T(
            handler=lambda **a: f.write_file(a["path"], a["content"]),
            schema=S("write_file", "Create or overwrite a file. Use str_replace for small edits.",
                     {"path": _S("File path"),
                      "content": _S("Full file content")},
                     ["path", "content"]),
            mode="code", writes=True,
        )
        self._tools["delete_file"] = T(
            handler=lambda **a: f.delete_file(a["path"]),
            schema=S("delete_file", "Delete a file.",
                     {"path": _S("File path to delete")},
                     ["path"]),
            mode="code", writes=True,
        )

        # ── Explore tools ──
        self._tools["list_directory"] = T(
            handler=lambda **a: f.list_directory(a.get("path", "."), a.get("max_depth", 3)),
            schema=S("list_directory",
                     "List files/dirs in tree format. Auto-adjusts depth for large projects.",
                     {"path": _S("Directory path (default: .)", default="."),
                      "max_depth": _I("Max depth (default 3)", default=3)},
                     []),
            mode="all",
        )
        self._tools["search_files"] = T(
            handler=lambda **a: f.search_files(
                a["pattern"], a.get("path", "."), a.get("include"),
                a.get("context_lines", 0), a.get("max_results", 80)),
            schema=S("search_files",
                     "Grep for a regex pattern across project files. Results grouped by file.",
                     {"pattern": _S("Search pattern (regex)"),
                      "path": _S("Search scope (default: .)", default="."),
                      "include": _S("File glob, e.g. '*.py'"),
                      "context_lines": _I("Lines of context around each match (0-5)", default=0),
                      "max_results": _I("Max result lines (default 80)", default=80)},
                     ["pattern"]),
            mode="all",
        )
        self._tools["find_files"] = T(
            handler=lambda **a: f.find_files(
                a["pattern"], a.get("path", "."), a.get("max_results", 50)),
            schema=S("find_files",
                     "Find files by glob pattern (e.g. '*.py', 'test_*.js'). Sorted by modification time.",
                     {"pattern": _S("Glob pattern to match filenames"),
                      "path": _S("Search root (default: .)", default="."),
                      "max_results": _I("Max files to return (default 50)", default=50)},
                     ["pattern"]),
            mode="all",
        )
        self._tools["find_symbol"] = T(
            handler=lambda **a: f.find_symbol(
                a["name"], a.get("kind", "any"), a.get("path", ".")),
            schema=S("find_symbol",
                     "Find function/class/variable definitions by name.",
                     {"name": _S("Symbol name to search for"),
                      "kind": _S("Symbol kind: 'function', 'class', or 'any' (default)", default="any"),
                      "path": _S("Search scope (default: .)", default=".")},
                     ["name"]),
            mode="all",
        )

        # ── Execution tools ──
        self._tools["bash"] = T(
            handler=lambda **a: self.shell.execute(a["command"]),
            schema=S("bash", "Execute a bash command.",
                     {"command": _S("Bash command to run")},
                     ["command"]),
            mode="code", confirm=True,
        )
        self._tools["read_image"] = T(
            handler=lambda **a: self._handle_read_image(a["path"]),
            schema=S("read_image",
                     "Read an image file for visual analysis. Supports PNG, JPG, GIF, WebP.",
                     {"path": _S("Image file path relative to project root")},
                     ["path"]),
            mode="all",
        )
        self._tools["web_fetch"] = T(
            handler=lambda **a: self._handle_web_fetch(a["url"]),
            schema=S("web_fetch",
                     "Fetch a URL and return its markdown content via Jina Reader. Available only when /web is ON.",
                     {"url": _S("URL to fetch (http/https)")},
                     ["url"]),
            mode="all",
        )
        self._tools["web_search"] = T(
            handler=lambda **a: self._handle_web_search(a["query"], a.get("max_results", 5), a.get("domains")),
            schema=S("web_search",
                     "Search the web and return results. Uses DuckDuckGo (free) by default, "
                     "Tavily when API key is configured. Available only when /web is ON.",
                     {"query": _S("Search query"),
                      "max_results": _I("Max results (default 5)", default=5),
                      "domains": _S("Optional comma-separated domains for filtering")},
                     ["query"]),
            mode="all",
        )

    # ── Helper handlers ──

    def _handle_read_image(self, path: str) -> str:
        img = self.file_ops.read_image(path)
        return f"[IMAGE:{img['path']}:{img['media_type']}:{img['size']}]"

    def _handle_web_fetch(self, url: str) -> str:
        if not self._web_enabled:
            return "Web access is disabled. Use /web to enable it."
        return self.web.fetch(url)

    def _handle_web_search(self, query: str, max_results: int = 5, domains=None) -> str:
        if not self._web_enabled:
            return "Web access is disabled. Use /web to enable it."
        if not self.web.search_available:
            return "No search backend available. Install: pip install ddgs"
        domain_list = None
        if isinstance(domains, str):
            domain_list = [item.strip() for item in domains.split(",") if item.strip()]
        elif isinstance(domains, list):
            domain_list = [str(item).strip() for item in domains if str(item).strip()]
        return self.web.search(query, max_results, domains=domain_list)

    # ── Public API ──

    @property
    def files(self):
        """Access file operations (for undo, preview, etc.)."""
        return self.file_ops

    @property
    def web_enabled(self):
        return self._web_enabled

    @web_enabled.setter
    def web_enabled(self, value: bool):
        self._web_enabled = value

    @property
    def schemas(self) -> List[dict]:
        """Return filtered JSON Schemas for the current mode."""
        result = []
        for name, entry in self._tools.items():
            # Mode filtering
            if self.mode == "ask" and entry.mode == "code":
                continue
            # Web filtering
            if not self._web_enabled and name in ("web_fetch", "web_search"):
                continue
            result.append(entry.schema)
        return result

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Dispatch a tool call by name — dict lookup, no match/case."""
        entry = self._tools.get(tool_name)
        if not entry:
            return f"Unknown tool: {tool_name}"

        # Mode check
        if self.mode == "ask" and entry.mode == "code":
            return f"Tool '{tool_name}' is disabled in mode '{self.mode}'."

        try:
            return entry.handler(**arguments)
        except FileOperationError as e:
            return f"Error: {e}"
        except WebOpsError as e:
            return f"Web error: {e}"
        except KeyError as e:
            return f"Missing argument: {e}"
        except Exception as e:
            return f"{tool_name} error: {type(e).__name__}: {e}"

    WRITE_TOOLS = {"create_file", "write_file", "str_replace", "delete_file"}
    CONFIRM_TOOLS = {"bash"}
    PARALLEL_SAFE_TOOLS = {
        "read_file",
        "list_directory",
        "search_files",
        "find_files",
        "find_symbol",
        "read_image",
        "web_fetch",
        "web_search",
    }

    @classmethod
    def needs_confirmation(cls, tool_name: str) -> bool:
        return tool_name in cls.CONFIRM_TOOLS

    @classmethod
    def can_parallelize(cls, tool_name: str) -> bool:
        return tool_name in cls.PARALLEL_SAFE_TOOLS
