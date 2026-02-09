import time

from rich.console import Console

from isrc101_agent.startup_profiler import StartupProfiler


def test_profiler_from_env_enabled(monkeypatch):
    monkeypatch.setenv("ISRC_PROFILE_STARTUP", "1")
    profiler = StartupProfiler.from_env()
    assert profiler.enabled is True


def test_profiler_from_env_disabled(monkeypatch):
    monkeypatch.delenv("ISRC_PROFILE_STARTUP", raising=False)
    profiler = StartupProfiler.from_env()
    assert profiler.enabled is False


def test_profiler_render_includes_stage_names():
    console = Console(record=True)
    profiler = StartupProfiler(enabled=True)

    profiler.mark("config.load")
    time.sleep(0.001)
    profiler.mark("prompt.init")
    profiler.render(console)

    rendered = console.export_text()
    assert "Startup Profile" in rendered
    assert "config.load" in rendered
    assert "prompt.init" in rendered


def test_profiler_disabled_render_is_silent():
    console = Console(record=True)
    profiler = StartupProfiler(enabled=False)

    profiler.mark("stage")
    profiler.render(console)

    assert console.export_text() == ""
