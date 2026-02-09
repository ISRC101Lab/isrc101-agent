from isrc101_agent.tools.registry import ToolRegistry


def test_registry_schema_filters_tools_by_mode_and_web(tmp_path):
    registry = ToolRegistry(str(tmp_path))

    registry.mode = "ask"
    registry.web_enabled = False
    names = {schema["function"]["name"] for schema in registry.schemas}

    assert names == {"read_file", "list_directory", "search_files"}


def test_registry_blocks_write_tool_in_ask_mode(tmp_path):
    registry = ToolRegistry(str(tmp_path))
    registry.mode = "ask"

    result = registry.execute("write_file", {"path": "a.txt", "content": "x"})

    assert "disabled in mode 'ask'" in result


def test_registry_blocks_bash_in_architect_mode(tmp_path):
    registry = ToolRegistry(str(tmp_path))
    registry.mode = "architect"

    result = registry.execute("bash", {"command": "echo hi"})

    assert "disabled in mode 'architect'" in result

