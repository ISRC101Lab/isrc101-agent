"""@tool decorator — auto-generates JSON Schema and dispatch from function signatures.

Usage:
    @tool(description="Read file contents", mode="all")
    def read_file(path: str, start_line: int = None, end_line: int = None) -> str:
        ...

This replaces the manual triple-sync of schemas.py + registry.py match/case + implementation.
"""

import inspect
from typing import Optional, Dict, Any, List, Callable, get_type_hints

# Global registry: name -> {func, schema, mode, category}
_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Python type -> JSON Schema type
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def tool(description: str, mode: str = "all", category: str = "general",
         confirm: bool = False, writes: bool = False):
    """Decorator to register a function as an LLM-callable tool.

    Args:
        description: Tool description shown to the LLM.
        mode: "all" (available in both modes), "code" (restricted in ask mode).
        category: Grouping label for display.
        confirm: Whether to require user confirmation before execution.
        writes: Whether this tool modifies files (for undo tracking).
    """
    def decorator(func: Callable) -> Callable:
        name = func.__name__
        schema = _build_schema(func, name, description)
        _TOOL_REGISTRY[name] = {
            "func": func,
            "schema": schema,
            "mode": mode,
            "category": category,
            "confirm": confirm,
            "writes": writes,
        }
        func._tool_name = name
        return func

    return decorator


def _build_schema(func: Callable, name: str, description: str) -> dict:
    """Auto-generate OpenAI-compatible JSON Schema from function signature."""
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        # Skip 'self' parameter
        if param_name == "self":
            continue

        prop: Dict[str, Any] = {}
        hint = hints.get(param_name)

        # Resolve Optional[X] -> X
        origin = getattr(hint, "__origin__", None)
        if origin is type(None):
            hint = None
        args = getattr(hint, "__args__", None)
        if args and type(None) in args:
            # Optional[X] — extract X
            hint = next((a for a in args if a is not type(None)), None)

        # Map type to JSON Schema
        if hint in _TYPE_MAP:
            prop["type"] = _TYPE_MAP[hint]
        else:
            prop["type"] = "string"

        # Extract description from docstring param lines
        doc_desc = _extract_param_doc(func, param_name)
        if doc_desc:
            prop["description"] = doc_desc

        # Handle defaults
        if param.default is not inspect.Parameter.empty:
            if param.default is not None:
                prop["default"] = param.default
        else:
            required.append(param_name)

        properties[param_name] = prop

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


def _extract_param_doc(func: Callable, param_name: str) -> str:
    """Extract parameter description from docstring (Google/numpy style)."""
    doc = func.__doc__
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{param_name}:") or stripped.startswith(f"{param_name} :"):
            _, _, desc = stripped.partition(":")
            return desc.strip()
    return ""


def get_registered_tools() -> Dict[str, Dict[str, Any]]:
    """Return the full tool registry."""
    return _TOOL_REGISTRY


def get_tool_schemas(web_enabled: bool = False, mode: str = "agent") -> List[dict]:
    """Return filtered JSON Schemas for the current mode."""
    schemas = []
    for name, entry in _TOOL_REGISTRY.items():
        tool_mode = entry["mode"]

        # Mode filtering
        if mode == "ask" and tool_mode == "code":
            continue

        # Web filtering
        if not web_enabled and name == "web_fetch":
            continue

        schemas.append(entry["schema"])
    return schemas


def execute_tool(name: str, arguments: Dict[str, Any],
                 context: Dict[str, Any]) -> str:
    """Dispatch a tool call by name. Context provides bound instances."""
    entry = _TOOL_REGISTRY.get(name)
    if not entry:
        return f"Unknown tool: {name}"

    func = entry["func"]
    # Bind 'self' from context based on which class owns the method
    owner = getattr(func, "_tool_owner", None)
    instance = context.get(owner) if owner else None

    if instance:
        return func(instance, **arguments)
    return func(**arguments)


def get_write_tools() -> set:
    """Return names of tools that modify files."""
    return {name for name, e in _TOOL_REGISTRY.items() if e["writes"]}


def get_confirm_tools() -> set:
    """Return names of tools that require user confirmation."""
    return {name for name, e in _TOOL_REGISTRY.items() if e["confirm"]}
