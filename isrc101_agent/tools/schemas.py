"""Tool JSON Schema definitions for the LLM."""

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read file contents with line numbers. Supports optional line range. Always read before editing.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path relative to project root"},
            "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
            "end_line": {"type": "integer", "description": "End line (inclusive)"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "create_file",
        "description": "Create a new file. Fails if file exists.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path to create"},
            "content": {"type": "string", "description": "Full file content"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "str_replace",
        "description": "Replace a unique string in a file. old_str must appear EXACTLY ONCE.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path to edit"},
            "old_str": {"type": "string", "description": "Exact string to find (must be unique)"},
            "new_str": {"type": "string", "description": "Replacement string (empty = delete)"},
        }, "required": ["path", "old_str", "new_str"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file. Use str_replace for small edits.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Full file content"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "delete_file",
        "description": "Delete a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path to delete"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "list_directory",
        "description": "List files/dirs in tree format. Auto-adjusts depth for large projects.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory path (default: .)", "default": "."},
            "max_depth": {"type": "integer", "description": "Max depth (default 3)", "default": 3},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Grep for a regex pattern across project files.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Search pattern (regex)"},
            "path": {"type": "string", "description": "Search scope (default: .)", "default": "."},
            "include": {"type": "string", "description": "File glob, e.g. '*.py'"},
        }, "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "bash",
        "description": "Execute a bash command.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "Bash command to run"},
        }, "required": ["command"]},
    }},
]

READ_ONLY_TOOLS = ["read_file", "list_directory", "search_files"]

def get_tools_for_mode(mode: str) -> list:
    if mode == "ask":
        return [t for t in TOOL_SCHEMAS if t["function"]["name"] in READ_ONLY_TOOLS]
    elif mode == "architect":
        return [t for t in TOOL_SCHEMAS
                if t["function"]["name"] in ("read_file", "list_directory", "search_files")]
    return TOOL_SCHEMAS
