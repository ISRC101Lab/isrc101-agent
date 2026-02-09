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
    {"type": "function", "function": {
        "name": "read_image",
        "description": "Read an image file for visual analysis. Supports PNG, JPG, GIF, WebP.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Image file path relative to project root"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "Fetch a URL and return its text content. Use for docs/API refs. Available only when /web is ON.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "URL to fetch (http/https)"},
        }, "required": ["url"]},
    }},
]


def get_all_tools() -> list:
    """Return all available tools."""
    return TOOL_SCHEMAS


def get_tools_filtered(web_enabled: bool = False, mode: str = "code") -> list:
    """Return tools filtered by web toggle and chat mode."""
    mode_allowed = {
        schema.get("function", {}).get("name")
        for schema in get_tools_for_mode(mode)
    }

    filtered = []
    for schema in TOOL_SCHEMAS:
        name = schema.get("function", {}).get("name")
        if name not in mode_allowed:
            continue
        if not web_enabled and name == "web_fetch":
            continue
        filtered.append(schema)
    return filtered


def get_tools_for_mode(mode: str) -> list:
    """Return tools allowed in the given chat mode."""
    if mode == "code":
        return TOOL_SCHEMAS

    if mode in ("ask", "architect"):
        read_only = {
            "read_file",
            "list_directory",
            "search_files",
        }
        return [
            schema
            for schema in TOOL_SCHEMAS
            if schema.get("function", {}).get("name") in read_only
        ]

    return TOOL_SCHEMAS
