from types import SimpleNamespace

from isrc101_agent.command_router import handle_command


class DummyConsole:
    def __init__(self):
        self.messages = []

    def print(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    def input(self, prompt: str) -> str:
        self.messages.append(((prompt,), {}))
        return "n"


class DummyConfig:
    def __init__(self):
        self.active_model = "m1"
        self.chat_mode = "code"
        self.models = {
            "m1": SimpleNamespace(name="m1", model="provider/m1", api_base=None, apply_to_env=lambda: None, get_llm_kwargs=lambda: {
                "model": "provider/m1",
                "api_base": None,
                "api_key": None,
                "temperature": 0.0,
                "max_tokens": 128,
                "context_window": 2048,
            }),
            "m2": SimpleNamespace(name="m2", model="provider/m2", api_base=None, apply_to_env=lambda: None, get_llm_kwargs=lambda: {
                "model": "provider/m2",
                "api_base": None,
                "api_key": None,
                "temperature": 0.0,
                "max_tokens": 128,
                "context_window": 2048,
            }),
        }
        self.web_display = "summary"
        self.reasoning_display = "summary"
        self.stream_profile = "ultra"
        self.web_enabled = False
        self.enabled_skills = []
        self.project_root = "."
        self.skills_dir = "skills"
        self.saved = 0

    def set_active_model(self, name: str):
        self.active_model = name
        self.saved += 1

    def get_active_preset(self):
        return self.models[self.active_model]

    def save(self):
        self.saved += 1

    def summary(self):
        return {"Active model": self.active_model}

    def list_models(self):
        return []


class DummyAgent:
    def __init__(self):
        self.conversation = []
        self.mode = "code"
        self.skill_instructions = ""
        self.web_display = "summary"
        self.reasoning_display = "summary"
        self.stream_profile = "ultra"

    def reset(self):
        self.conversation = []

    def get_stats(self):
        return {"messages": len(self.conversation)}

    def compact_conversation(self):
        return 0


class DummyLLM:
    def __init__(self):
        self.model = "provider/m1"
        self.api_base = None
        self.api_key = None
        self.temperature = 0.0
        self.max_tokens = 128
        self.context_window = 2048


def _ctx():
    console = DummyConsole()
    agent = DummyAgent()
    config = DummyConfig()
    llm = DummyLLM()
    git = SimpleNamespace(
        available=False,
        _run=lambda *a, **k: SimpleNamespace(stdout=""),
        get_current_branch=lambda: "main",
        status_short=lambda: "",
        get_log=lambda n: "",
    )
    undo = SimpleNamespace(can_undo=False)
    files = SimpleNamespace(undo=undo)
    tools = SimpleNamespace(git=git, files=files, web_enabled=False)
    return console, agent, config, llm, tools


class AgentWithToolMode(DummyAgent):
    def __init__(self, bound_tools):
        self._bound_tools = bound_tools
        super().__init__()
        self._mode = "code"

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        self._mode = value
        self._bound_tools.mode = value


def test_load_restores_mode_and_model(monkeypatch):
    console, agent, config, llm, tools = _ctx()

    session_data = {
        "name": "s1",
        "conversation": [{"role": "user", "content": "hi"}],
        "metadata": {"mode": "ask", "model": "m2"},
    }
    monkeypatch.setattr("isrc101_agent.command_router.load_session", lambda name: session_data)

    handle_command("/load s1", console=console, agent=agent, config=config, llm=llm, tools=tools)

    assert agent.mode == "ask"
    assert config.chat_mode == "ask"
    assert config.active_model == "m2"
    assert llm.model == "provider/m2"
    assert agent.conversation == session_data["conversation"]
    assert config.saved == 0


def test_load_missing_model_keeps_current(monkeypatch):
    console, agent, config, llm, tools = _ctx()

    session_data = {
        "name": "s2",
        "conversation": [{"role": "user", "content": "hi"}],
        "metadata": {"mode": "architect", "model": "missing-model"},
    }
    monkeypatch.setattr("isrc101_agent.command_router.load_session", lambda name: session_data)

    handle_command("/load s2", console=console, agent=agent, config=config, llm=llm, tools=tools)

    assert agent.mode == "architect"
    assert config.chat_mode == "architect"
    assert config.active_model == "m1"
    assert llm.model == "provider/m1"
    assert any("Saved model not found" in str(args[0]) for args, _ in console.messages if args)


def test_load_restored_mode_sets_tool_mode(monkeypatch):
    console, _agent, config, llm, tools = _ctx()
    tools.mode = "code"

    agent = AgentWithToolMode(tools)

    session_data = {
        "name": "s3",
        "conversation": [{"role": "user", "content": "hello"}],
        "metadata": {"mode": "ask"},
    }
    monkeypatch.setattr("isrc101_agent.command_router.load_session", lambda name: session_data)

    handle_command("/load s3", console=console, agent=agent, config=config, llm=llm, tools=tools)

    assert agent.mode == "ask"
    assert tools.mode == "ask"


def test_display_stream_updates_agent_and_config():
    console, agent, config, llm, tools = _ctx()
    agent.stream_profile = "ultra"
    config.stream_profile = "ultra"

    handle_command(
        "/display stream smooth",
        console=console,
        agent=agent,
        config=config,
        llm=llm,
        tools=tools,
    )

    assert agent.stream_profile == "smooth"
    assert config.stream_profile == "smooth"


def test_slash_only_defaults_to_first_command():
    console, agent, config, llm, tools = _ctx()

    import isrc101_agent.command_router as router

    original_help = router._cmd_help

    def _fake_help(ctx, args):
        ctx.console.print("help-called")
        return ""

    router.COMMAND_HANDLERS["/help"] = _fake_help
    try:
        handle_command("/", console=console, agent=agent, config=config, llm=llm, tools=tools)
    finally:
        router.COMMAND_HANDLERS["/help"] = original_help

    assert any("help-called" in str(args[0]) for args, _ in console.messages if args)
