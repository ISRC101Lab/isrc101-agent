import io

from rich.console import Console

from isrc101_agent.command_router import CommandContext, _cmd_grounding


class DummyConfig:
    def __init__(self):
        self.grounded_web_mode = "strict"
        self.grounded_retry = 1
        self.grounded_visible_citations = "sources_only"
        self.grounded_context_chars = 8000
        self.grounded_search_max_seconds = 180
        self.grounded_search_max_rounds = 8
        self.grounded_search_per_round = 3
        self.grounded_fallback_to_open_web = True
        self.grounded_partial_on_timeout = True
        self.saved = False

    def save(self):
        self.saved = True


class DummyAgent:
    def __init__(self):
        self.grounded_web_mode = "strict"
        self.grounded_retry = 1
        self.grounded_visible_citations = "sources_only"
        self.grounded_context_chars = 8000
        self.grounded_search_max_seconds = 180
        self.grounded_search_max_rounds = 8
        self.grounded_search_per_round = 3
        self.grounded_fallback_to_open_web = True
        self.grounded_partial_on_timeout = True


def _ctx():
    return CommandContext(
        console=Console(file=io.StringIO(), force_terminal=False, color_system=None),
        agent=DummyAgent(),
        config=DummyConfig(),
        llm=None,
        tools=None,
    )


def test_grounding_seconds_rounds_and_per_round_commands():
    ctx = _ctx()

    _cmd_grounding(ctx, ["seconds", "240"])
    _cmd_grounding(ctx, ["rounds", "12"])
    _cmd_grounding(ctx, ["per_round", "5"])

    assert ctx.agent.grounded_search_max_seconds == 240
    assert ctx.config.grounded_search_max_seconds == 240
    assert ctx.agent.grounded_search_max_rounds == 12
    assert ctx.config.grounded_search_max_rounds == 12
    assert ctx.agent.grounded_search_per_round == 5
    assert ctx.config.grounded_search_per_round == 5


def test_grounding_fallback_and_partial_toggle_commands():
    ctx = _ctx()

    _cmd_grounding(ctx, ["fallback", "off"])
    _cmd_grounding(ctx, ["partial", "off"])

    assert ctx.agent.grounded_fallback_to_open_web is False
    assert ctx.config.grounded_fallback_to_open_web is False
    assert ctx.agent.grounded_partial_on_timeout is False
    assert ctx.config.grounded_partial_on_timeout is False
