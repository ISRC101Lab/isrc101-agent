import io

from rich.console import Console

from isrc101_agent.agent import Plan, PlanStep
from isrc101_agent.command_router import CommandContext, _cmd_mode, _cmd_plan
from isrc101_agent.config import Config
from isrc101_agent.tools.registry import ToolRegistry


class DummyConfig:
    def __init__(self, chat_mode: str = "ask"):
        self.chat_mode = chat_mode
        self.saved = False

    def save(self):
        self.saved = True


class DummyAgent:
    def __init__(self, mode: str = "ask", plan: Plan | None = None):
        self.mode = mode
        self.current_plan = plan
        self.conversation = []
        self.last_instruction = ""

    def chat(self, instruction: str):
        self.last_instruction = instruction


def _console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


def test_config_mode_normalization_legacy_values_map_to_agent():
    cfg = Config()
    assert cfg._normalize_chat_mode("agent") == "agent"
    assert cfg._normalize_chat_mode("ask") == "ask"
    assert cfg._normalize_chat_mode("code") == "agent"
    assert cfg._normalize_chat_mode("architect") == "agent"
    assert cfg._normalize_chat_mode("unknown") == "agent"


def test_cmd_mode_accepts_legacy_alias_and_switches_to_agent():
    agent = DummyAgent(mode="ask")
    config = DummyConfig(chat_mode="ask")
    ctx = CommandContext(console=_console(), agent=agent, config=config, llm=None, tools=None)

    _cmd_mode(ctx, ["code"])

    assert agent.mode == "agent"
    assert config.chat_mode == "agent"
    assert config.saved is True


def test_plan_execute_switches_ask_to_agent_before_execution():
    plan = Plan(
        title="Apply refactor",
        steps=[
            PlanStep(index=1, action="write_file", target="a.txt", description="update content", status="pending")
        ],
    )
    agent = DummyAgent(mode="ask", plan=plan)
    config = DummyConfig(chat_mode="ask")
    ctx = CommandContext(console=_console(), agent=agent, config=config, llm=None, tools=None)

    _cmd_plan(ctx, ["execute"])

    assert agent.mode == "agent"
    assert config.chat_mode == "agent"
    assert config.saved is True
    assert "Execute this plan step by step" in agent.last_instruction
    assert "## Plan: Apply refactor" in agent.last_instruction


def test_tool_registry_blocks_write_and_shell_in_ask_mode(tmp_path):
    registry = ToolRegistry(project_root=str(tmp_path), blocked_commands=[], command_timeout=5)
    registry.mode = "ask"

    create_result = registry.execute("create_file", {"path": "new.txt", "content": "hello"})
    bash_result = registry.execute("bash", {"command": "echo hi"})

    (tmp_path / "ok.txt").write_text("ok\n", encoding="utf-8")
    read_result = registry.execute("read_file", {"path": "ok.txt"})

    assert "disabled in mode 'ask'" in create_result
    assert "disabled in mode 'ask'" in bash_result
    assert "-- ok.txt" in read_result
