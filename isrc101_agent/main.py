"""
isrc101-agent v1.0.0 — AI coding assistant for your terminal.

Command: isrc run
"""

import os
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
BANNER = (
    f"[bold #7FA6D9]isrc101-agent[/bold #7FA6D9] "
    f"[dim]v{__version__} · AI coding assistant[/dim]"
)


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
@click.option("--mode", type=click.Choice(["code", "ask", "architect"]), default=None)
@click.option("--no-git", is_flag=True, help="Disable auto-commit")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def run(model, api_key, api_base, project_dir, auto_confirm, mode, no_git, verbose):
    """Start an interactive session."""
    profiler = StartupProfiler.from_env()

    console.print(BANNER)
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")
    config = Config.load(project_dir)
    profiler.mark("config.load")

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
    if mode:
        config.chat_mode = mode
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
        console.print(f"[red]Error: '{project_dir}' is not a valid directory.[/red]")
        sys.exit(1)
    profiler.mark("project.resolve")

    skills = discover_skills(project_root, config.skills_dir)
    profiler.mark("skills.discover")

    skill_prompt, _, missing_skills = build_skill_instructions(skills, config.enabled_skills)
    profiler.mark("skills.prompt")

    from .ui import (
        MAX_SLASH_MENU_ITEMS,
        PTK_STYLE,
        SlashCommandCompleter,
        make_prompt_html,
        render_startup,
    )

    profiler.mark("ui.import")

    render_startup(console, config)
    if missing_skills:
        console.print(f"  [yellow]⚠ Missing skills in config:[/yellow] {', '.join(missing_skills)}")
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
    )
    tools.web_enabled = config.web_enabled
    profiler.mark("tools.init")

    agent = Agent(
        llm=llm,
        tools=tools,
        max_iterations=config.max_iterations,
        auto_confirm=config.auto_confirm,
        chat_mode=config.chat_mode,
        auto_commit=config.auto_commit,
        skill_instructions=skill_prompt,
        reasoning_display=config.reasoning_display,
        web_display=config.web_display,
        stream_profile=config.stream_profile,
        web_preview_lines=config.web_preview_lines,
        web_preview_chars=config.web_preview_chars,
        web_context_chars=config.web_context_chars,
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

    slash_completer = SlashCommandCompleter(max_items=MAX_SLASH_MENU_ITEMS)
    session = PromptSession(
        history=FileHistory(str(CONFIG_DIR / "history.txt")),
        multiline=False,
        completer=slash_completer,
        complete_while_typing=True,
        style=PTK_STYLE,
        complete_style=CompleteStyle.COLUMN,
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

    while True:
        try:
            prompt_html = make_prompt_html()
            user_input = session.prompt(prompt_html, key_bindings=repl_kb).strip()
            pending_ctrl_d_exit = False
        except EOFError:
            if pending_ctrl_d_exit:
                console.print("\n[dim]Goodbye![/dim]")
                break
            pending_ctrl_d_exit = True
            console.print("\n[dim]Press Ctrl-D again to exit.[/dim]")
            continue
        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

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
            console.print("\n[yellow]  Interrupted.[/yellow]")
        except Exception as error:
            console.print(f"\n[red]  Error: {error}[/red]")
            if config.verbose:
                import traceback

                console.print(f"[dim]{traceback.format_exc()}[/dim]")


@cli.command()
@click.argument("message", nargs=-1, required=True)
@click.option("--model", "-m", default=None)
@click.option("--project-dir", "-d", default=".")
@click.option("--mode", type=click.Choice(["code", "ask", "architect"]), default=None)
def ask(message, model, project_dir, mode):
    """Run a single query."""
    config = Config.load(project_dir)
    if model and model in config.models:
        config.active_model = model
    if mode:
        config.chat_mode = mode

    preset = config.get_active_preset()
    preset.apply_to_env()

    project_root = Path(config.project_root).resolve()
    skills = discover_skills(project_root, config.skills_dir)
    skill_prompt, _, _ = build_skill_instructions(skills, config.enabled_skills)

    llm = LLMAdapter(**preset.get_llm_kwargs())
    llm.warmup_async()

    tools = ToolRegistry(project_root=str(project_root), commit_prefix=config.commit_prefix)
    tools.web_enabled = config.web_enabled

    agent = Agent(
        llm=llm,
        tools=tools,
        auto_confirm=True,
        chat_mode=config.chat_mode,
        skill_instructions=skill_prompt,
        reasoning_display=config.reasoning_display,
        web_display=config.web_display,
        stream_profile=config.stream_profile,
        web_preview_lines=config.web_preview_lines,
        web_preview_chars=config.web_preview_chars,
        web_context_chars=config.web_context_chars,
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
