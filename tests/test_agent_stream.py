from types import SimpleNamespace

from rich.markdown import Markdown
from rich.text import Text

import isrc101_agent.agent as agent_module
from isrc101_agent.agent import Agent
from isrc101_agent.llm import LLMResponse


class DummyLLM:
    def __init__(self, stream_factory):
        self.model = "test-model"
        self.max_tokens = 256
        self.context_window = 4096
        self._stream_factory = stream_factory

    def chat_stream(self, messages, tools=None):
        yield from self._stream_factory(messages, tools)


class FakeLive:
    instances = []

    def __init__(self, *args, **kwargs):
        self.updates = []
        self.refresh_calls = 0
        self.started = False
        self.stopped = False
        FakeLive.instances.append(self)

    def start(self):
        self.started = True

    def update(self, renderable):
        self.updates.append(renderable)

    def refresh(self):
        self.refresh_calls += 1

    def stop(self):
        self.stopped = True


class FakeConsole:
    def __init__(self):
        self.calls = []

    def print(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _build_agent(stream_factory, **kwargs):
    llm = DummyLLM(stream_factory)
    tools = SimpleNamespace(schemas=[], mode="code")
    params = {"stream_profile": "smooth"}
    params.update(kwargs)
    return Agent(llm=llm, tools=tools, **params)


def test_stream_render_throttles_small_chunks(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 100.0)

    chunks = ["a"] * 120
    expected = "".join(chunks)

    def stream_factory(_messages, _tools):
        for chunk in chunks:
            yield ("text", chunk)
        yield ("done", LLMResponse(content=expected))

    agent = _build_agent(stream_factory)
    response = agent._stream_response(messages=[])

    assert response.content == expected
    assert len(FakeLive.instances) == 1

    live = FakeLive.instances[0]
    assert live.started is True
    assert live.stopped is True
    assert len(live.updates) <= 12
    assert isinstance(live.updates[-1], Markdown)
    assert all(isinstance(item, (Text, Markdown)) for item in live.updates)


def test_stream_interrupt_returns_partial_response(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 100.0)

    def stream_factory(_messages, _tools):
        yield ("text", "partial")
        raise KeyboardInterrupt

    agent = _build_agent(stream_factory)
    response = agent._stream_response(messages=[])

    assert response.content == "partial"
    assert len(FakeLive.instances) == 1

    live = FakeLive.instances[0]
    assert live.started is True
    assert live.stopped is True
    assert len(live.updates) >= 1
    assert isinstance(live.updates[-1], Text)


def test_reasoning_summary_mode_shows_line_count(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monotonic_values = iter([100.0, 100.0, 100.0, 100.0, 100.0, 100.0])

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: next(monotonic_values))

    reasoning_chunk = ("alpha\n" * 20) + "beta\n"

    def stream_factory(_messages, _tools):
        yield ("reasoning", reasoning_chunk)
        yield ("text", "done")
        yield ("done", LLMResponse(content="done", reasoning_content=reasoning_chunk))

    agent = _build_agent(stream_factory, reasoning_display="summary")
    response = agent._stream_response(messages=[])

    assert response.content == "done"
    live = FakeLive.instances[0]
    text_updates = [item for item in live.updates if isinstance(item, Text)]
    assert text_updates
    assert any("thinking… (" in item.plain for item in text_updates)


def test_web_result_preview_and_context_summary(monkeypatch):
    fake_console = FakeConsole()
    monkeypatch.setattr(agent_module, "console", fake_console)

    def stream_factory(_messages, _tools):
        yield ("done", LLMResponse(content="ok"))

    agent = _build_agent(
        stream_factory,
        web_display="summary",
        web_preview_lines=2,
        web_preview_chars=80,
        web_context_chars=120,
    )

    web_result = "URL: https://example.com/docs\n\n" + ("line content " * 60)
    summarized = agent._summarize_web_for_context(web_result)
    assert summarized.startswith("URL: https://example.com/docs")
    assert "context summary omitted" in summarized

    agent._render_result("web_fetch", web_result, elapsed=0)
    printed = "\n".join(str(args[0]) for args, _ in fake_console.calls if args)
    assert "web: https://example.com/docs" in printed
    assert "chars omitted" in printed


def test_web_result_preview_brief_mode(monkeypatch):
    fake_console = FakeConsole()
    monkeypatch.setattr(agent_module, "console", fake_console)

    def stream_factory(_messages, _tools):
        yield ("done", LLMResponse(content="ok"))

    agent = _build_agent(
        stream_factory,
        web_display="brief",
        web_preview_lines=2,
        web_preview_chars=120,
        web_context_chars=4000,
    )

    web_result = "URL: https://example.com/api\n\n" + ("payload " * 80)
    summarized = agent._summarize_web_for_context(web_result)
    assert summarized.startswith("URL: https://example.com/api")
    assert "context summary omitted" in summarized

    agent._render_result("web_fetch", web_result, elapsed=0)
    printed = "\n".join(str(args[0]) for args, _ in fake_console.calls if args)
    assert "web: https://example.com/api |" in printed
    assert "+" in printed


def test_stream_markdown_unclosed_fence_is_safely_closed(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 100.0)

    partial_markdown = "```python\nprint('x')"

    def stream_factory(_messages, _tools):
        yield ("text", partial_markdown)
        yield ("done", LLMResponse(content=partial_markdown))

    agent = _build_agent(stream_factory)
    response = agent._stream_response(messages=[])

    assert response.content == partial_markdown
    live = FakeLive.instances[0]
    assert isinstance(live.updates[-1], Markdown)
    assert live.updates[-1].markup.endswith("\n```")


def test_stream_interrupt_keeps_text_renderable_not_markdown(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 100.0)

    def stream_factory(_messages, _tools):
        yield ("text", "```py\nprint('x')")
        raise KeyboardInterrupt

    agent = _build_agent(stream_factory)
    response = agent._stream_response(messages=[])

    assert response.content.startswith("```py")
    live = FakeLive.instances[0]
    assert isinstance(live.updates[-1], Text)


def test_stream_priority_chunk_flushes_on_cjk_punctuation(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    times = iter([100.00, 100.01, 100.02, 100.03, 100.04, 100.05, 100.06])
    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: next(times))

    chunks = ["这", "是", "。", "后续"]

    def stream_factory(_messages, _tools):
        for chunk in chunks:
            yield ("text", chunk)
        yield ("done", LLMResponse(content="".join(chunks)))

    agent = _build_agent(stream_factory)
    response = agent._stream_response(messages=[])

    assert response.content == "这是。后续"
    live = FakeLive.instances[0]
    assert len(live.updates) >= 2


def test_stream_profile_changes_refresh_thresholds(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)

    chunks = ["a"] * 60

    def stream_factory(_messages, _tools):
        for chunk in chunks:
            yield ("text", chunk)
        yield ("done", LLMResponse(content="".join(chunks)))

    times = iter([100.0] * 200)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: next(times))
    stable_agent = _build_agent(stream_factory, stream_profile="stable")
    stable_agent._stream_response(messages=[])
    stable_updates = len(FakeLive.instances[-1].updates)

    times = iter([200.0] * 200)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: next(times))
    ultra_agent = _build_agent(stream_factory, stream_profile="ultra")
    ultra_agent._stream_response(messages=[])
    ultra_updates = len(FakeLive.instances[-1].updates)

    assert ultra_updates >= stable_updates


def test_ultra_profile_uses_live_renderer(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 100.0)

    chunks = ["A", "B", "C"]

    def stream_factory(_messages, _tools):
        for chunk in chunks:
            yield ("text", chunk)
        yield ("done", LLMResponse(content="ABC"))

    agent = _build_agent(stream_factory, stream_profile="ultra")
    response = agent._stream_response(messages=[])

    assert response.content == "ABC"
    assert len(FakeLive.instances) >= 1
    assert FakeLive.instances[-1].updates


def test_ultra_profile_streams_reasoning_line_by_line_summary(monkeypatch):
    FakeLive.instances = []
    fake_console = FakeConsole()

    monkeypatch.setattr(agent_module, "Live", FakeLive)
    monkeypatch.setattr(agent_module, "console", fake_console)
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 100.0)

    def stream_factory(_messages, _tools):
        yield ("reasoning", "step one details\nstep two details\n")
        yield ("text", "done")
        yield ("done", LLMResponse(content="done", reasoning_content="step one details\nstep two details"))

    agent = _build_agent(stream_factory, stream_profile="ultra", reasoning_display="summary")
    response = agent._stream_response(messages=[])

    assert response.content == "done"
    assert len(FakeLive.instances) >= 1
    assert FakeLive.instances[-1].updates
