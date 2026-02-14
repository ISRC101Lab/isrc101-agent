"""
isrc101-agent v1.0.0 — AI coding assistant for your terminal.

Command: isrc run
"""

import os
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console

from . import __version__
from .agent import Agent
from .config import CONFIG_DIR, Config, ModelPreset
from .llm import LLMAdapter
from .skills import build_skill_instructions, discover_skills
from .startup_profiler import StartupProfiler
from .tools import ToolRegistry

console = Console()


def _normalize_cli_mode(value):
    if value is None:
        return None
    mode = str(value).strip().lower()
    if mode in ("code", "architect"):
        return "agent"
    if mode in ("agent", "ask"):
        return mode
    raise click.UsageError("Invalid --mode. Use: agent | ask")


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """isrc101-agent — AI coding assistant for your terminal."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
@click.option("--model", "-m", default=None, help="Model preset name")
@click.option("--api-key", "-k", default=None, help="API key override")
@click.option("--api-base", "-b", default=None, help="API base override")
@click.option("--project-dir", "-d", default=".", help="Project directory")
@click.option("--auto-confirm", "-y", is_flag=True, help="Auto-confirm all")
@click.option("--mode", default=None, help="Mode: agent or ask")
@click.option("--no-git", is_flag=True, help="Disable auto-commit")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--no-unicode", is_flag=True, help="Use ASCII icons instead of Unicode")
@click.option("--high-contrast", is_flag=True, help="Use high contrast theme")
def run(model, api_key, api_base, project_dir, auto_confirm, mode, no_git, verbose, no_unicode, high_contrast):
    """Start an interactive session."""
    profiler = StartupProfiler.from_env()

    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")
    config = Config.load(project_dir)
    profiler.mark("config.load")

    # Initialize theme system
    from . import theme
    from .rendering import set_use_unicode

    # Handle high-contrast mode
    if high_contrast:
        theme.set_theme("high_contrast")
    else:
        theme.set_theme(config.theme)

    # Handle Unicode/ASCII mode
    if no_unicode:
        config.use_unicode = False
    set_use_unicode(config.use_unicode)

    profiler.mark("theme.init")

    if model:
        if model in config.models:
            config.active_model = model
        else:
            config.models["_cli"] = ModelPreset(
                name="_cli",
                provider="openai",
                model=model,
                api_base=api_base,
                api_key=api_key or "not-needed",
            )
            config.active_model = "_cli"
    if auto_confirm:
        config.auto_confirm = True
    normalized_mode = _normalize_cli_mode(mode)
    if normalized_mode:
        config.chat_mode = normalized_mode
    if no_git:
        config.auto_commit = False
    if verbose:
        config.verbose = True

    profiler.set_enabled(config.verbose)
    profiler.mark("cli.overrides")

    preset = config.get_active_preset()
    if api_key:
        preset.api_key = api_key
    if api_base:
        preset.api_base = api_base
    preset.apply_to_env()
    profiler.mark("model.resolve")

    project_root = Path(config.project_root).resolve()
    if not project_root.is_dir():
        console.print(f"[#F85149]Error: '{project_dir}' is not a valid directory.[/#F85149]")
        sys.exit(1)
    profiler.mark("project.resolve")

    skills = discover_skills(project_root, config.skills_dir)
    profiler.mark("skills.discover")

    skill_prompt, _, missing_skills = build_skill_instructions(skills, config.enabled_skills)
    profiler.mark("skills.prompt")

    from .theme import SEPARATOR
    from .ui import (
        ContextToolbar,
        MAX_SLASH_MENU_ITEMS,
        PTK_STYLE,
        SlashCommandCompleter,
        make_prompt_html,
        render_startup,
    )

    profiler.mark("ui.import")

    render_startup(console, config)
    if missing_skills:
        console.print(f"  [#E3B341]⚠ Missing skills in config:[/#E3B341] {', '.join(missing_skills)}")
    profiler.mark("startup.render")

    llm = LLMAdapter(**preset.get_llm_kwargs())
    profiler.mark("llm.init")

    llm.warmup_async()
    profiler.mark("llm.warmup")

    tools = ToolRegistry(
        project_root=str(project_root),
        blocked_commands=config.blocked_commands,
        command_timeout=config.command_timeout,
        commit_prefix=config.commit_prefix,
        config=config,
    )
    tools.web_enabled = config.web_enabled
    profiler.mark("tools.init")

    agent = Agent(
        llm=llm,
        tools=tools,
        auto_confirm=config.auto_confirm,
        chat_mode=config.chat_mode,
        auto_commit=config.auto_commit,
        skill_instructions=skill_prompt,
        reasoning_display=config.reasoning_display,
        web_display=config.web_display,
        answer_style=config.answer_style,
        grounded_web_mode=config.grounded_web_mode,
        grounded_retry=config.grounded_retry,
        grounded_visible_citations=config.grounded_visible_citations,
        grounded_context_chars=config.grounded_context_chars,
        grounded_search_max_seconds=config.grounded_search_max_seconds,
        grounded_search_max_rounds=config.grounded_search_max_rounds,
        grounded_search_per_round=config.grounded_search_per_round,
        grounded_official_domains=config.grounded_official_domains,
        grounded_fallback_to_open_web=config.grounded_fallback_to_open_web,
        grounded_partial_on_timeout=config.grounded_partial_on_timeout,
        web_preview_lines=config.web_preview_lines,
        web_preview_chars=config.web_preview_chars,
        web_context_chars=config.web_context_chars,
        max_web_calls_per_turn=config.max_web_calls_per_turn,
        tool_parallelism=config.tool_parallelism,
        result_truncation_mode=config.result_truncation_mode,
        display_file_tree=config.display_file_tree,
        config=config,
    )
    profiler.mark("agent.init")

    from .command_router import handle_command

    profiler.mark("router.import")

    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.shortcuts import CompleteStyle

    profiler.mark("prompt_toolkit.import")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    slash_completer = SlashCommandCompleter(
        max_items=MAX_SLASH_MENU_ITEMS,
        ui_state_manager=config.ui_state
    )
    context_toolbar = ContextToolbar(
        agent_ref=lambda: agent,
        config_ref=lambda: config,
    )
    session = PromptSession(
        history=FileHistory(str(CONFIG_DIR / "history.txt")),
        multiline=False,
        completer=slash_completer,
        complete_while_typing=True,
        style=PTK_STYLE,
        complete_style=CompleteStyle.COLUMN,
        bottom_toolbar=context_toolbar,
    )
    profiler.mark("prompt.init")
    profiler.render(console)

    repl_kb = KeyBindings()

    @repl_kb.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    @repl_kb.add("/")
    def _slash_menu(event):
        buffer = event.current_buffer
        buffer.insert_text("/")
        if buffer.document.text == "/":
            buffer.start_completion(select_first=True)

    pending_ctrl_d_exit = False

    from .session import save_session

    def _print_separator():
        cols = shutil.get_terminal_size().columns
        console.print(f"[{SEPARATOR}]{'─' * cols}[/{SEPARATOR}]")

    while True:
        try:
            prompt_html = make_prompt_html(agent.mode)
            user_input = session.prompt(
                prompt_html,
                key_bindings=repl_kb,
                refresh_interval=1.0,  # Refresh toolbar every second
            ).strip()
            pending_ctrl_d_exit = False
        except EOFError:
            if pending_ctrl_d_exit:
                console.print("\n[#6E7681]Goodbye![/#6E7681]")
                break
            pending_ctrl_d_exit = True
            console.print("\n[#6E7681]Press Ctrl-D again to exit.[/#6E7681]")
            continue
        except KeyboardInterrupt:
            console.print("\n[#6E7681]Goodbye![/#6E7681]")
            break

        if not user_input:
            continue

        _print_separator()

        if user_input.startswith("/"):
            result = handle_command(
                user_input,
                console=console,
                agent=agent,
                config=config,
                llm=llm,
                tools=tools,
            )
            if result == "quit":
                break
            continue

        try:
            agent.chat(user_input)
        except KeyboardInterrupt:
            console.print("\n[#E3B341]  Interrupted.[/#E3B341]")
        except Exception as error:
            console.print(f"\n[#F85149]  Error: {error}[/#F85149]")
            if config.verbose:
                import traceback

                console.print(f"[#6E7681]{traceback.format_exc()}[/#6E7681]")

        # Context usage hint after each turn
        try:
            ctx_info = agent.get_context_info()
            pct = ctx_info["pct"]
            if pct >= 90:
                console.print(f"\n  [#F85149]Context {pct}% full — run /compact to free space[/#F85149]")
            elif pct >= 70:
                console.print(f"\n  [#6E7681]Context {pct}% used (~{ctx_info['remaining']:,} tokens remaining)[/#6E7681]")
        except Exception:
            pass

    # ── Auto-save session on exit ──
    if agent.conversation:
        # Generate auto-save session name
        import time
        auto_session_name = f"auto_{int(time.time())}"

        metadata = {
            "mode": agent.mode,
            "model": config.active_model,
            "project_root": str(project_root),
        }
        try:
            save_session(agent.conversation, auto_session_name, metadata)
            console.print(f"  [#6E7681]Session saved ({len(agent.conversation)} messages)[/#6E7681]")
        except Exception:
            pass


@cli.command()
@click.argument("message", nargs=-1, required=True)
@click.option("--model", "-m", default=None)
@click.option("--project-dir", "-d", default=".")
@click.option("--mode", default=None, help="Mode: agent or ask")
def ask(message, model, project_dir, mode):
    """Run a single query."""
    config = Config.load(project_dir)
    if model and model in config.models:
        config.active_model = model
    normalized_mode = _normalize_cli_mode(mode)
    if normalized_mode:
        config.chat_mode = normalized_mode

    preset = config.get_active_preset()
    preset.apply_to_env()

    project_root = Path(config.project_root).resolve()
    skills = discover_skills(project_root, config.skills_dir)
    skill_prompt, _, _ = build_skill_instructions(skills, config.enabled_skills)

    llm = LLMAdapter(**preset.get_llm_kwargs())
    llm.warmup_async()

    tools = ToolRegistry(
        project_root=str(project_root),
        commit_prefix=config.commit_prefix,
        config=config,
    )
    tools.web_enabled = config.web_enabled

    agent = Agent(
        llm=llm,
        tools=tools,
        auto_confirm=True,
        chat_mode=config.chat_mode,
        skill_instructions=skill_prompt,
        reasoning_display=config.reasoning_display,
        web_display=config.web_display,
        answer_style=config.answer_style,
        grounded_web_mode=config.grounded_web_mode,
        grounded_retry=config.grounded_retry,
        grounded_visible_citations=config.grounded_visible_citations,
        grounded_context_chars=config.grounded_context_chars,
        grounded_search_max_seconds=config.grounded_search_max_seconds,
        grounded_search_max_rounds=config.grounded_search_max_rounds,
        grounded_search_per_round=config.grounded_search_per_round,
        grounded_official_domains=config.grounded_official_domains,
        grounded_fallback_to_open_web=config.grounded_fallback_to_open_web,
        grounded_partial_on_timeout=config.grounded_partial_on_timeout,
        web_preview_lines=config.web_preview_lines,
        web_preview_chars=config.web_preview_chars,
        web_context_chars=config.web_context_chars,
        max_web_calls_per_turn=config.max_web_calls_per_turn,
        tool_parallelism=config.tool_parallelism,
        result_truncation_mode=config.result_truncation_mode,
        display_file_tree=config.display_file_tree,
        config=config,
    )
    agent.chat(" ".join(message))


@cli.command("config")
def config_cmd():
    """Show configuration."""
    from .command_router import show_config_panel

    cfg = Config.load()
    show_config_panel(console, cfg)


if __name__ == "__main__":
    cli()
