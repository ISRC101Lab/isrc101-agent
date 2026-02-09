"""Slash-command routing and handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agent import Agent
from .config import Config, ModelPreset
from .llm import LLMAdapter
from .session import list_sessions, load_session, save_session
from .skills import build_skill_instructions, discover_skills
from .tools import ToolRegistry

THEME_ACCENT = "#7FA6D9"

_SLASH_COMMAND_NAMES = [
    "/help",
    "/model",
    "/mode",
    "/skills",
    "/web",
    "/display",
    "/save",
    "/load",
    "/sessions",
    "/compact",
    "/undo",
    "/diff",
    "/config",
    "/stats",
    "/git",
    "/reset",
    "/quit",
]

_SLASH_ALIASES = {"/h": "/help", "/?": "/help", "/exit": "/quit", "/q": "/quit"}


@dataclass
class CommandContext:
    console: Console
    agent: Agent
    config: Config
    llm: LLMAdapter
    tools: ToolRegistry


CommandHandler = Callable[[CommandContext, list[str]], str]


def _resolve_command(raw_cmd: str, console: Console) -> str:
    """Resolve abbreviated slash commands via exact/alias/prefix matching."""
    cmd = raw_cmd.lower()

    # UX: pressing Enter immediately after '/' should trigger the first command.
    if cmd == "/":
        return _SLASH_COMMAND_NAMES[0]

    if cmd in _SLASH_COMMAND_NAMES:
        return cmd
    if cmd in _SLASH_ALIASES:
        return _SLASH_ALIASES[cmd]

    matches = [candidate for candidate in _SLASH_COMMAND_NAMES if candidate.startswith(cmd)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        options = ", ".join(f"[bold]{item}[/bold]" for item in matches)
        console.print(f"  [yellow]Ambiguous: {cmd} → {options}[/yellow]")
        return ""

    return cmd


def handle_command(
    command: str,
    *,
    console: Console,
    agent: Agent,
    config: Config,
    llm: LLMAdapter,
    tools: ToolRegistry,
) -> str:
    """Handle one slash command string."""
    parts = command.split()
    if not parts:
        return ""

    raw_cmd = parts[0].lower()
    args = parts[1:]

    cmd = _resolve_command(raw_cmd, console)
    if not cmd:
        return ""

    ctx = CommandContext(console=console, agent=agent, config=config, llm=llm, tools=tools)
    handler = COMMAND_HANDLERS.get(cmd)
    if not handler:
        console.print(f"  [yellow]Unknown: {cmd}. Try /help[/yellow]")
        return ""

    return handler(ctx, args)


def _show_config_panel(console: Console, config: Config) -> None:
    table = Table(show_header=False, border_style=THEME_ACCENT, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for key, value in config.summary().items():
        table.add_row(key, str(value))
    console.print(Panel(table, title="[bold]Configuration[/bold]", border_style=THEME_ACCENT))


def show_config_panel(console: Console, config: Config) -> None:
    _show_config_panel(console, config)


def _switch_model(ctx: CommandContext, name: str, persist: bool = True) -> None:
    if persist:
        ctx.config.set_active_model(name)
    else:
        if name not in ctx.config.models:
            return
        ctx.config.active_model = name

    preset = ctx.config.get_active_preset()
    preset.apply_to_env()
    kwargs = preset.get_llm_kwargs()
    ctx.llm.model = kwargs["model"]
    ctx.llm.api_base = kwargs["api_base"]
    ctx.llm.api_key = kwargs["api_key"]
    ctx.llm.temperature = kwargs["temperature"]
    ctx.llm.max_tokens = kwargs["max_tokens"]
    ctx.llm.context_window = kwargs["context_window"]
    ctx.console.print(f"  [green]✓ Switched → [bold]{name}[/bold] ({preset.model})[/green]")
    if preset.api_base:
        ctx.console.print(f"    [dim]{preset.api_base}[/dim]")


def _restore_session_metadata(ctx: CommandContext, data: dict) -> list[str]:
    restored: list[str] = []
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return restored

    mode = metadata.get("mode")
    if isinstance(mode, str) and mode in ("code", "ask", "architect"):
        ctx.agent.mode = mode
        ctx.config.chat_mode = mode
        restored.append(f"mode={mode}")

    model = metadata.get("model")
    if isinstance(model, str) and model:
        if model in ctx.config.models:
            if ctx.config.active_model != model:
                _switch_model(ctx, model, persist=False)
            restored.append(f"model={model}")
        else:
            ctx.console.print(f"  [yellow]⚠ Saved model not found: {model}[/yellow]")

    return restored


def _show_model_table(ctx: CommandContext) -> None:
    table = Table(border_style=THEME_ACCENT)
    table.add_column("", width=2)
    table.add_column("Name", style="bold")
    table.add_column("Model")
    table.add_column("API Base")
    table.add_column("Key")
    table.add_column("Description")
    for model in ctx.config.list_models():
        marker = "[green]●[/green]" if model["active"] else " "
        table.add_row(
            marker,
            model["name"],
            model["model"],
            model["api_base"],
            model["key"],
            model["desc"],
        )
    ctx.console.print(Panel(table, title="[bold]Models[/bold]", border_style=THEME_ACCENT))


def _show_skill_table(ctx: CommandContext, skills: dict) -> None:
    if not skills:
        ctx.console.print("  [yellow]No skills found. Create skills under ./skills first.[/yellow]")
        return

    table = Table(border_style=THEME_ACCENT)
    table.add_column("", width=2)
    table.add_column("Skill", style="bold")
    table.add_column("Description")
    table.add_column("Path")

    for name in sorted(skills.keys()):
        spec = skills[name]
        marker = "[green]●[/green]" if name in ctx.config.enabled_skills else " "
        table.add_row(marker, name, spec.description, spec.path)

    ctx.console.print(Panel(table, title="[bold]Skills[/bold]", border_style=THEME_ACCENT))


def _refresh_skill_instructions(ctx: CommandContext, skills: dict) -> None:
    skill_prompt, _, missing = build_skill_instructions(skills, ctx.config.enabled_skills)
    ctx.agent.skill_instructions = skill_prompt
    if missing:
        ctx.console.print(f"  [yellow]⚠ Missing skills:[/yellow] {', '.join(missing)}")


def _cmd_quit(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    ctx.console.print("[dim]Goodbye![/dim]")
    return "quit"


def _cmd_help(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    from .ui import HELP_TEXT

    ctx.console.print(HELP_TEXT)
    return ""


def _cmd_model(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        from .ui import select_model_interactive

        name = select_model_interactive(ctx.config)
        if name and name != ctx.config.active_model:
            _switch_model(ctx, name)
        elif name:
            ctx.console.print(f"  [dim]Already on '{name}'[/dim]")
        return ""

    if args[0] == "list":
        _show_model_table(ctx)
        return ""

    if args[0] == "add" and len(args) >= 4:
        name, provider, model_str = args[1], args[2], args[3]
        api_base = args[4] if len(args) > 4 else None
        api_key = args[5] if len(args) > 5 else None
        ctx.config.models[name] = ModelPreset(
            name=name,
            provider=provider,
            model=model_str,
            api_base=api_base,
            api_key=api_key,
            description=f"{provider}/{model_str}",
        )
        ctx.config.save()
        ctx.console.print(f"  [green]✓ Added '{name}'[/green]")
        return ""

    if args[0] == "add":
        ctx.console.print("  Usage: /model add <n> <provider> <model> [api-base] [api-key]")
        return ""

    if args[0] == "rm" and len(args) >= 2:
        name = args[1]
        if name == ctx.config.active_model:
            ctx.console.print("  [yellow]Cannot remove active model. Switch first.[/yellow]")
        elif name in ctx.config.models:
            del ctx.config.models[name]
            ctx.config.save()
            ctx.console.print(f"  [green]✓ Removed '{name}'[/green]")
        else:
            ctx.console.print(f"  [yellow]Not found: '{name}'[/yellow]")
        return ""

    name = args[0]
    if name in ctx.config.models:
        _switch_model(ctx, name)
    else:
        ctx.console.print(f"  [yellow]Unknown: '{name}'. Use /model to browse.[/yellow]")
    return ""


def _cmd_skills(ctx: CommandContext, args: list[str]) -> str:
    project_root = Path(ctx.config.project_root).resolve()
    skills = discover_skills(project_root, ctx.config.skills_dir)

    if not args:
        from .ui import select_skills_interactive

        selected = select_skills_interactive(ctx.config, skills)
        ctx.config.enabled_skills = selected
        ctx.config.save()
        _refresh_skill_instructions(ctx, skills)
        if selected:
            ctx.console.print(f"  [green]✓ Enabled skills:[/green] {', '.join(selected)}")
        else:
            ctx.console.print("  [green]✓ Skills disabled[/green]")
        return ""

    if args[0] == "list":
        _show_skill_table(ctx, skills)
        return ""

    if args[0] == "on" and len(args) >= 2:
        name = args[1]
        if name not in skills:
            ctx.console.print(f"  [yellow]Unknown skill: '{name}'. Use /skills list[/yellow]")
        else:
            if name not in ctx.config.enabled_skills:
                ctx.config.enabled_skills.append(name)
                ctx.config.save()
            _refresh_skill_instructions(ctx, skills)
            ctx.console.print(f"  [green]✓ Skill enabled:[/green] {name}")
        return ""

    if args[0] == "off" and len(args) >= 2:
        name = args[1]
        if name in ctx.config.enabled_skills:
            ctx.config.enabled_skills = [item for item in ctx.config.enabled_skills if item != name]
            ctx.config.save()
        _refresh_skill_instructions(ctx, skills)
        ctx.console.print(f"  [green]✓ Skill disabled:[/green] {name}")
        return ""

    if args[0] == "clear":
        ctx.config.enabled_skills = []
        ctx.config.save()
        _refresh_skill_instructions(ctx, skills)
        ctx.console.print("  [green]✓ All skills disabled[/green]")
        return ""

    ctx.console.print("  Usage: /skills | /skills list | /skills on <name> | /skills off <name> | /skills clear")
    return ""


def _cmd_mode(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        ctx.console.print(f"  Current: [bold]{ctx.agent.mode}[/bold]  (code | ask | architect)")
        return ""

    if args[0] in ("code", "ask", "architect"):
        old_mode = ctx.agent.mode
        ctx.agent.mode = args[0]
        ctx.console.print(f"  [green]✓ Mode → {args[0]}[/green]")
        if old_mode != args[0] and len(ctx.agent.conversation) > 2:
            ctx.console.print("  [dim]💡 Tip: conversation history preserved. Use /reset to start fresh.[/dim]")
    else:
        ctx.console.print(f"  [yellow]Unknown: {args[0]}[/yellow]")
    return ""


def _cmd_save(ctx: CommandContext, args: list[str]) -> str:
    if not ctx.agent.conversation:
        ctx.console.print("  [dim]Nothing to save (empty conversation)[/dim]")
        return ""

    name = args[0] if args else None
    metadata = {"mode": ctx.agent.mode, "model": ctx.config.active_model}
    filename = save_session(ctx.agent.conversation, name, metadata)
    ctx.console.print(f"  [green]✓ Saved session: {filename}[/green]")
    return ""


def _cmd_load(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        sessions = list_sessions(5)
        if not sessions:
            ctx.console.print("  [dim]No saved sessions[/dim]")
        else:
            ctx.console.print("  [bold]Recent sessions:[/bold]")
            for session in sessions:
                ctx.console.print(
                    f"    {session['name']} ({session['messages']} msgs, {session['created_at']})"
                )
            ctx.console.print("  [dim]Use /load <name> to load[/dim]")
        return ""

    data = load_session(args[0])
    if data:
        ctx.agent.conversation = data.get("conversation", [])
        restored = _restore_session_metadata(ctx, data)
        ctx.console.print(
            f"  [green]✓ Loaded: {data.get('name')} ({len(ctx.agent.conversation)} messages)[/green]"
        )
        if restored:
            ctx.console.print(f"  [dim]↳ restored {', '.join(restored)}[/dim]")
    else:
        ctx.console.print(f"  [yellow]Session not found: {args[0]}[/yellow]")
    return ""


def _cmd_sessions(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    sessions = list_sessions(10)
    if not sessions:
        ctx.console.print("  [dim]No saved sessions[/dim]")
        return ""

    table = Table(border_style=THEME_ACCENT)
    table.add_column("Name", style="bold")
    table.add_column("Messages")
    table.add_column("Created")
    for session in sessions:
        table.add_row(session["name"], str(session["messages"]), session["created_at"])
    ctx.console.print(Panel(table, title="[bold]Saved Sessions[/bold]", border_style=THEME_ACCENT))
    return ""


def _cmd_config(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    _show_config_panel(ctx.console, ctx.config)
    return ""


def _cmd_stats(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    stats = ctx.agent.get_stats()
    table = Table(show_header=False, border_style=THEME_ACCENT, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    for key, value in stats.items():
        table.add_row(key, f"{value:,}" if isinstance(value, int) else str(value))
    ctx.console.print(Panel(table, title="[bold]Session[/bold]", border_style=THEME_ACCENT))
    return ""


def _cmd_compact(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    count = ctx.agent.compact_conversation()
    if count > 0:
        ctx.console.print(f"  [green]✓ Compacted {count} old messages into summary[/green]")
    else:
        ctx.console.print("  [dim]Nothing to compact (≤4 messages)[/dim]")
    return ""


def _cmd_git(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    git = ctx.tools.git
    if not git.available:
        ctx.console.print("  [yellow]Not a git repository.[/yellow]")
        return ""

    ctx.console.print(f"  [bold]Branch:[/bold] {git.get_current_branch()}")
    ctx.console.print(f"  [bold]Status:[/bold]\n{git.status_short()}")
    ctx.console.print(f"  [bold]Recent:[/bold]\n{git.get_log(5)}")
    return ""


def _cmd_undo(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    undo = ctx.tools.files.undo
    if not undo.can_undo:
        ctx.console.print("  [dim]No file changes to undo.[/dim]")
        return ""

    history = undo.get_history(5)
    ctx.console.print(f"  [dim]Recent changes ({undo.undo_count} total):[/dim]")
    for index, item in enumerate(history):
        marker = "→" if index == 0 else " "
        ctx.console.print(f"  {marker} {item['operation']}: {item['path']}")
    try:
        answer = ctx.console.input("  Undo last change? (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            result = undo.undo_last()
            ctx.console.print(f"  [green]✓ {result}[/green]")
        else:
            ctx.console.print("  [dim]Cancelled[/dim]")
    except (KeyboardInterrupt, EOFError):
        ctx.console.print("  [dim]Cancelled[/dim]")
    return ""


def _cmd_web(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        ctx.tools.web_enabled = not ctx.tools.web_enabled
    else:
        head = args[0].lower()
        if head in ("on", "off"):
            ctx.tools.web_enabled = head == "on"
            if len(args) >= 2:
                mode = args[1].lower()
                if mode in ("summary", "full"):
                    ctx.config.web_display = mode
                    ctx.agent.web_display = mode
                else:
                    ctx.console.print(
                        "  [yellow]Usage: /web [on|off] [summary|full] | /web [summary|full][/yellow]"
                    )
                    return ""
        elif head in ("summary", "full"):
            ctx.config.web_display = head
            ctx.agent.web_display = head
        else:
            ctx.console.print(
                "  [yellow]Usage: /web [on|off] [summary|full] | /web [summary|full][/yellow]"
            )
            return ""

    ctx.config.web_enabled = ctx.tools.web_enabled
    ctx.config.save()
    status = "[green]ON[/green]" if ctx.tools.web_enabled else "[dim]OFF[/dim]"
    ctx.console.print(f"  Web access: {status} [dim](display: {ctx.agent.web_display})[/dim]")
    return ""


def _cmd_display(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        ctx.console.print(
            f"  thinking: [bold]{ctx.agent.reasoning_display}[/bold]"
            f"  | web: [bold]{ctx.agent.web_display}[/bold]"
            f"  | stream: [bold]{ctx.agent.stream_profile}[/bold]"
        )
        ctx.console.print("  Usage: /display thinking <off|summary|full> | /display web <summary|full> | /display stream <stable|smooth|ultra>")
        return ""

    target = args[0].lower()
    if target == "thinking":
        if len(args) < 2 or args[1].lower() not in ("off", "summary", "full"):
            ctx.console.print("  [yellow]Usage: /display thinking <off|summary|full>[/yellow]")
            return ""
        mode = args[1].lower()
        ctx.config.reasoning_display = mode
        ctx.agent.reasoning_display = mode
        ctx.config.save()
        ctx.console.print(f"  [green]✓ thinking display → {mode}[/green]")
        return ""

    if target == "web":
        if len(args) < 2 or args[1].lower() not in ("summary", "full"):
            ctx.console.print("  [yellow]Usage: /display web <summary|full>[/yellow]")
            return ""
        mode = args[1].lower()
        ctx.config.web_display = mode
        ctx.agent.web_display = mode
        ctx.config.save()
        ctx.console.print(f"  [green]✓ web display → {mode}[/green]")
        return ""

    if target == "stream":
        if len(args) < 2 or args[1].lower() not in ("stable", "smooth", "ultra"):
            ctx.console.print("  [yellow]Usage: /display stream <stable|smooth|ultra>[/yellow]")
            return ""
        profile = args[1].lower()
        ctx.config.stream_profile = profile
        ctx.agent.stream_profile = profile
        ctx.config.save()
        ctx.console.print(f"  [green]✓ stream profile → {profile}[/green]")
        return ""

    ctx.console.print("  [yellow]Usage: /display thinking <off|summary|full> | /display web <summary|full> | /display stream <stable|smooth|ultra>[/yellow]")
    return ""


def _cmd_diff(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    git = ctx.tools.git
    if not git.available:
        ctx.console.print("  [yellow]Not a git repository.[/yellow]")
        return ""

    diff = git._run("diff", "--stat").stdout.strip()
    staged = git._run("diff", "--cached", "--stat").stdout.strip()
    if not diff and not staged:
        ctx.console.print("  [dim]No changes.[/dim]")
        return ""

    if staged:
        ctx.console.print(f"  [bold green]Staged:[/bold green]\n  {staged}")
    if diff:
        ctx.console.print(f"  [bold yellow]Unstaged:[/bold yellow]\n  {diff}")
    return ""


def _cmd_reset(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    ctx.agent.reset()
    ctx.console.print("  [green]✓ Conversation cleared.[/green]")
    return ""


COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "/quit": _cmd_quit,
    "/help": _cmd_help,
    "/model": _cmd_model,
    "/skills": _cmd_skills,
    "/mode": _cmd_mode,
    "/save": _cmd_save,
    "/load": _cmd_load,
    "/sessions": _cmd_sessions,
    "/config": _cmd_config,
    "/stats": _cmd_stats,
    "/compact": _cmd_compact,
    "/git": _cmd_git,
    "/undo": _cmd_undo,
    "/web": _cmd_web,
    "/display": _cmd_display,
    "/diff": _cmd_diff,
    "/reset": _cmd_reset,
}
