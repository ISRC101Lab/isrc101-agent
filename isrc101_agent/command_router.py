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
from .ui import SLASH_COMMANDS
from .theme import (
    ACCENT as THEME_ACCENT,
    BORDER as THEME_BORDER,
    DIM as THEME_DIM,
    SUCCESS as THEME_SUCCESS,
    WARN as THEME_WARN,
    ERROR as THEME_ERROR,
    INFO as THEME_INFO,
)

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
        return SLASH_COMMANDS[0]

    if cmd in SLASH_COMMANDS:
        return cmd
    if cmd in _SLASH_ALIASES:
        return _SLASH_ALIASES[cmd]

    matches = [candidate for candidate in SLASH_COMMANDS if candidate.startswith(cmd)]
    if matches:
        return matches[0]

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
        console.print(f"  [{THEME_WARN}]Unknown: {cmd}. Try /help[/{THEME_WARN}]")
        return ""

    return handler(ctx, args)


def _show_config_panel(console: Console, config: Config) -> None:
    table = Table(show_header=False, border_style=THEME_BORDER, padding=(0, 2), box=None)
    table.add_column("Key", style=f"bold {THEME_ACCENT}", min_width=14)
    table.add_column("Value", style="#E6EDF3")
    for key, value in config.summary().items():
        table.add_row(key, str(value))
    console.print(Panel(table, title=f"[bold {THEME_ACCENT}] Configuration [/bold {THEME_ACCENT}]",
                        title_align="left", border_style=THEME_BORDER, padding=(0, 1)))


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
    ctx.console.print(f"  [{THEME_SUCCESS}]✓[/{THEME_SUCCESS}] Switched → [bold]{name}[/bold] [{THEME_DIM}]({preset.model})[/{THEME_DIM}]")
    if preset.api_base:
        ctx.console.print(f"    [{THEME_DIM}]{preset.api_base}[/{THEME_DIM}]")


def _restore_session_metadata(ctx: CommandContext, data: dict) -> list[str]:
    restored: list[str] = []
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return restored

    mode = metadata.get("mode")
    if isinstance(mode, str):
        normalized_mode = str(mode).strip().lower()
        if normalized_mode in ("code", "architect"):
            normalized_mode = "agent"
        if normalized_mode in ("agent", "ask"):
            ctx.agent.mode = normalized_mode
            ctx.config.chat_mode = normalized_mode
            restored.append(f"mode={normalized_mode}")

    model = metadata.get("model")
    if isinstance(model, str) and model:
        if model in ctx.config.models:
            if ctx.config.active_model != model:
                _switch_model(ctx, model, persist=False)
            restored.append(f"model={model}")
        else:
            ctx.console.print(f"  [{THEME_WARN}]⚠ Saved model not found: {model}[/{THEME_WARN}]")

    return restored


def _show_model_table(ctx: CommandContext) -> None:
    table = Table(border_style=THEME_BORDER)
    table.add_column("", width=2)
    table.add_column("Name", style=f"bold {THEME_ACCENT}")
    table.add_column("Model", style="#E6EDF3")
    table.add_column("API Base", style=THEME_DIM)
    table.add_column("Key", style=THEME_DIM)
    table.add_column("Description", style="#8B949E")
    for model in ctx.config.list_models():
        marker = f"[{THEME_SUCCESS}]●[/{THEME_SUCCESS}]" if model["active"] else " "
        table.add_row(
            marker,
            model["name"],
            model["model"],
            model["api_base"],
            model["key"],
            model["desc"],
        )
    ctx.console.print(Panel(table, title=f"[bold {THEME_ACCENT}] Models [/bold {THEME_ACCENT}]",
                            title_align="left", border_style=THEME_BORDER))


def _show_skill_table(ctx: CommandContext, skills: dict) -> None:
    if not skills:
        ctx.console.print(f"  [{THEME_WARN}]No skills found. Create skills under ./skills first.[/{THEME_WARN}]")
        return

    table = Table(border_style=THEME_BORDER)
    table.add_column("", width=2)
    table.add_column("Skill", style=f"bold {THEME_ACCENT}")
    table.add_column("Description", style="#8B949E")
    table.add_column("Path", style=THEME_DIM)

    for name in sorted(skills.keys()):
        spec = skills[name]
        marker = f"[{THEME_SUCCESS}]●[/{THEME_SUCCESS}]" if name in ctx.config.enabled_skills else " "
        table.add_row(marker, name, spec.description, spec.path)

    ctx.console.print(Panel(table, title=f"[bold {THEME_ACCENT}] Skills [/bold {THEME_ACCENT}]",
                            title_align="left", border_style=THEME_BORDER))


def _refresh_skill_instructions(ctx: CommandContext, skills: dict) -> None:
    skill_prompt, _, missing = build_skill_instructions(skills, ctx.config.enabled_skills)
    ctx.agent.skill_instructions = skill_prompt
    if missing:
        ctx.console.print(f"  [{THEME_WARN}]⚠ Missing skills:[/{THEME_WARN}] {', '.join(missing)}")


def _cmd_quit(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    ctx.console.print(f"[{THEME_DIM}]Goodbye![/{THEME_DIM}]")
    return "quit"


def _cmd_help(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    from .ui import render_help

    render_help(ctx.console)
    return ""


def _cmd_model(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        from .ui import select_model_interactive

        name = select_model_interactive(ctx.config)
        if name and name != ctx.config.active_model:
            _switch_model(ctx, name)
        elif name:
            ctx.console.print(f"  [{THEME_DIM}]Already on '{name}'[/{THEME_DIM}]")
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
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ Added '{name}'[/{THEME_SUCCESS}]")
        return ""

    if args[0] == "add":
        ctx.console.print("  Usage: /model add <n> <provider> <model> [api-base] [api-key]")
        return ""

    if args[0] == "rm" and len(args) >= 2:
        name = args[1]
        if name == ctx.config.active_model:
            ctx.console.print(f"  [{THEME_WARN}]Cannot remove active model. Switch first.[/{THEME_WARN}]")
        elif name in ctx.config.models:
            del ctx.config.models[name]
            ctx.config.save()
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Removed '{name}'[/{THEME_SUCCESS}]")
        else:
            ctx.console.print(f"  [{THEME_WARN}]Not found: '{name}'[/{THEME_WARN}]")
        return ""

    name = args[0]
    if name in ctx.config.models:
        _switch_model(ctx, name)
    else:
        ctx.console.print(f"  [{THEME_WARN}]Unknown: '{name}'. Use /model to browse.[/{THEME_WARN}]")
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
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Enabled skills:[/{THEME_SUCCESS}] {', '.join(selected)}")
        else:
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Skills disabled[/{THEME_SUCCESS}]")
        return ""

    if args[0] == "list":
        _show_skill_table(ctx, skills)
        return ""

    if args[0] == "on" and len(args) >= 2:
        name = args[1]
        if name not in skills:
            ctx.console.print(f"  [{THEME_WARN}]Unknown skill: '{name}'. Use /skills list[/{THEME_WARN}]")
        else:
            if name not in ctx.config.enabled_skills:
                ctx.config.enabled_skills.append(name)
                ctx.config.save()
            _refresh_skill_instructions(ctx, skills)
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Skill enabled:[/{THEME_SUCCESS}] {name}")
        return ""

    if args[0] == "off" and len(args) >= 2:
        name = args[1]
        if name in ctx.config.enabled_skills:
            ctx.config.enabled_skills = [item for item in ctx.config.enabled_skills if item != name]
            ctx.config.save()
        _refresh_skill_instructions(ctx, skills)
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ Skill disabled:[/{THEME_SUCCESS}] {name}")
        return ""

    if args[0] == "clear":
        ctx.config.enabled_skills = []
        ctx.config.save()
        _refresh_skill_instructions(ctx, skills)
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ All skills disabled[/{THEME_SUCCESS}]")
        return ""

    ctx.console.print("  Usage: /skills | /skills list | /skills on <name> | /skills off <name> | /skills clear")
    return ""


def _cmd_mode(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        mode_colors = {"agent": THEME_SUCCESS, "ask": THEME_WARN}
        mc = mode_colors.get(ctx.agent.mode, THEME_DIM)
        ctx.console.print(f"  [{mc}]●[/{mc}] [{mc}]{ctx.agent.mode}[/{mc}]  [{THEME_DIM}](agent | ask)[/{THEME_DIM}]")
        return ""

    requested_mode = args[0].strip().lower()
    if requested_mode in ("code", "architect"):
        requested_mode = "agent"

    if requested_mode in ("agent", "ask"):
        old_mode = ctx.agent.mode
        ctx.agent.mode = requested_mode
        ctx.config.chat_mode = requested_mode
        ctx.config.save()
        mode_colors = {"agent": THEME_SUCCESS, "ask": THEME_WARN}
        mc = mode_colors.get(requested_mode, THEME_DIM)
        ctx.console.print(f"  [{THEME_SUCCESS}]✓[/{THEME_SUCCESS}] Mode → [{mc}]{requested_mode}[/{mc}]")
        if old_mode != requested_mode and len(ctx.agent.conversation) > 2:
            ctx.console.print(f"  [{THEME_DIM}]Tip: conversation preserved — use /reset to start fresh[/{THEME_DIM}]")
    else:
        ctx.console.print(f"  [{THEME_WARN}]Unknown mode: {args[0]} (use: agent | ask)[/{THEME_WARN}]")
    return ""


def _cmd_save(ctx: CommandContext, args: list[str]) -> str:
    if not ctx.agent.conversation:
        ctx.console.print(f"  [{THEME_DIM}]Nothing to save (empty conversation)[/{THEME_DIM}]")
        return ""

    name = args[0] if args else None
    metadata = {"mode": ctx.agent.mode, "model": ctx.config.active_model}
    filename = save_session(ctx.agent.conversation, name, metadata)
    ctx.console.print(f"  [{THEME_SUCCESS}]✓ Saved session: {filename}[/{THEME_SUCCESS}]")
    return ""


def _cmd_load(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        sessions = list_sessions(5)
        if not sessions:
            ctx.console.print(f"  [{THEME_DIM}]No saved sessions[/{THEME_DIM}]")
        else:
            ctx.console.print("  [bold]Recent sessions:[/bold]")
            for session in sessions:
                ctx.console.print(
                    f"    {session['name']} ({session['messages']} msgs, {session['created_at']})"
                )
            ctx.console.print(f"  [{THEME_DIM}]Use /load <name> to load[/{THEME_DIM}]")
        return ""

    data = load_session(args[0])
    if data:
        ctx.agent.conversation = data.get("conversation", [])
        restored = _restore_session_metadata(ctx, data)
        ctx.console.print(
            f"  [{THEME_SUCCESS}]✓ Loaded: {data.get('name')} ({len(ctx.agent.conversation)} messages)[/{THEME_SUCCESS}]"
        )
        if restored:
            ctx.console.print(f"  [{THEME_DIM}]↳ restored {', '.join(restored)}[/{THEME_DIM}]")
    else:
        ctx.console.print(f"  [{THEME_WARN}]Session not found: {args[0]}[/{THEME_WARN}]")
    return ""


def _cmd_sessions(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    sessions = list_sessions(10)
    if not sessions:
        ctx.console.print(f"  [{THEME_DIM}]No saved sessions[/{THEME_DIM}]")
        return ""

    table = Table(border_style=THEME_BORDER)
    table.add_column("Name", style=f"bold {THEME_ACCENT}")
    table.add_column("Messages", style="#E6EDF3")
    table.add_column("Created", style=THEME_DIM)
    for session in sessions:
        table.add_row(session["name"], str(session["messages"]), session["created_at"])
    ctx.console.print(Panel(table, title=f"[bold {THEME_ACCENT}] Sessions [/bold {THEME_ACCENT}]",
                            title_align="left", border_style=THEME_BORDER))
    return ""


def _cmd_config(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    _show_config_panel(ctx.console, ctx.config)
    return ""


def _cmd_stats(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    stats = ctx.agent.get_stats()
    table = Table(show_header=False, border_style=THEME_BORDER, padding=(0, 2), box=None)
    table.add_column("Metric", style=f"bold {THEME_ACCENT}", min_width=16)
    table.add_column("Value", style="#E6EDF3")
    for key, value in stats.items():
        table.add_row(key, f"{value:,}" if isinstance(value, int) else str(value))
    ctx.console.print(Panel(table, title=f"[bold {THEME_ACCENT}] Session [/bold {THEME_ACCENT}]",
                            title_align="left", border_style=THEME_BORDER, padding=(0, 1)))

    # Tool metrics
    metrics = ctx.tools.get_metrics()
    if metrics:
        ctx.console.print()
        tool_table = Table(show_header=True, border_style=THEME_BORDER, padding=(0, 1), box=None)
        tool_table.add_column("Tool", style=f"bold {THEME_ACCENT}", min_width=16)
        tool_table.add_column("Calls", justify="right", style="#E6EDF3")
        tool_table.add_column("Errors", justify="right", style=THEME_ERROR)
        tool_table.add_column("Time (ms)", justify="right", style=THEME_DIM)
        for tool_name in sorted(metrics.keys()):
            m = metrics[tool_name]
            tool_table.add_row(
                tool_name,
                f"{m.total_calls}",
                f"{m.total_errors}" if m.total_errors > 0 else "—",
                f"{m.total_time_ms:.0f}"
            )
        ctx.console.print(Panel(tool_table, title=f"[bold {THEME_ACCENT}] Tool Metrics [/bold {THEME_ACCENT}]",
                                title_align="left", border_style=THEME_BORDER, padding=(0, 1)))
    return ""


def _cmd_compact(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    count = ctx.agent.compact_conversation()
    if count > 0:
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ Compacted {count} old messages into summary[/{THEME_SUCCESS}]")
    else:
        ctx.console.print(f"  [{THEME_DIM}]Nothing to compact (≤4 messages)[/{THEME_DIM}]")
    return ""


def _cmd_git(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    git = ctx.tools.git
    if not git.available:
        ctx.console.print(f"  [{THEME_WARN}]Not a git repository.[/{THEME_WARN}]")
        return ""

    ctx.console.print(f"  [bold {THEME_ACCENT}]branch[/bold {THEME_ACCENT}]  {git.get_current_branch()}")
    ctx.console.print(f"  [bold {THEME_ACCENT}]status[/bold {THEME_ACCENT}]")
    for line in git.status_short().strip().splitlines():
        ctx.console.print(f"    [{THEME_DIM}]{line}[/{THEME_DIM}]")
    ctx.console.print(f"  [bold {THEME_ACCENT}]recent[/bold {THEME_ACCENT}]")
    for line in git.get_log(5).strip().splitlines():
        ctx.console.print(f"    [{THEME_DIM}]{line}[/{THEME_DIM}]")
    return ""


def _cmd_undo(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    undo = ctx.tools.files.undo
    if not undo.can_undo:
        ctx.console.print(f"  [{THEME_DIM}]No file changes to undo.[/{THEME_DIM}]")
        return ""

    history = undo.get_history(5)
    ctx.console.print(f"  [{THEME_DIM}]Recent changes ({undo.undo_count} total):[/{THEME_DIM}]")
    for index, item in enumerate(history):
        marker = "→" if index == 0 else " "
        ctx.console.print(f"  {marker} {item['operation']}: {item['path']}")
    try:
        answer = ctx.console.input("  Undo last change? (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            result = undo.undo_last()
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ {result}[/{THEME_SUCCESS}]")
        else:
            ctx.console.print(f"  [{THEME_DIM}]Cancelled[/{THEME_DIM}]")
    except (KeyboardInterrupt, EOFError):
        ctx.console.print(f"  [{THEME_DIM}]Cancelled[/{THEME_DIM}]")
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
                if mode in ("brief", "summary", "full"):
                    ctx.config.web_display = mode
                    ctx.agent.web_display = mode
                else:
                    ctx.console.print(
                        "  [{THEME_WARN}]Usage: /web [on|off] [brief|summary|full] | /web [brief|summary|full][/{THEME_WARN}]"
                    )
                    return ""
        elif head in ("brief", "summary", "full"):
            ctx.config.web_display = head
            ctx.agent.web_display = head
        else:
            ctx.console.print(
                "  [{THEME_WARN}]Usage: /web [on|off] [brief|summary|full] | /web [brief|summary|full][/{THEME_WARN}]"
            )
            return ""

    ctx.config.web_enabled = ctx.tools.web_enabled
    ctx.config.save()
    status = f"[{THEME_SUCCESS}]ON[/{THEME_SUCCESS}]" if ctx.tools.web_enabled else f"[{THEME_DIM}]OFF[/{THEME_DIM}]"
    ctx.console.print(f"  Web access: {status} [{THEME_DIM}](display: {ctx.agent.web_display})[/{THEME_DIM}]")
    return ""


def _cmd_grounding(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        ctx.console.print(
            "  "
            f"grounded_web_mode=[bold]{ctx.agent.grounded_web_mode}[/bold] "
            f"retry=[bold]{ctx.agent.grounded_retry}[/bold] "
            f"citations=[bold]{ctx.agent.grounded_visible_citations}[/bold] "
            f"context=[bold]{ctx.agent.grounded_context_chars}[/bold] "
            f"seconds=[bold]{ctx.agent.grounded_search_max_seconds}[/bold] "
            f"rounds=[bold]{ctx.agent.grounded_search_max_rounds}[/bold] "
            f"per_round=[bold]{ctx.agent.grounded_search_per_round}[/bold] "
            f"fallback=[bold]{'on' if ctx.agent.grounded_fallback_to_open_web else 'off'}[/bold] "
            f"partial=[bold]{'on' if ctx.agent.grounded_partial_on_timeout else 'off'}[/bold]"
        )
        ctx.console.print(
            "  Usage: /grounding <on|off|strict|status> "
            "| /grounding retry <0-3> | /grounding citations <sources_only|inline> "
            "| /grounding context <800-40000> "
            "| /grounding seconds <20-1200> | /grounding rounds <1-30> "
            "| /grounding per_round <1-8> | /grounding fallback <on|off> "
            "| /grounding partial <on|off>"
        )
        return ""

    head = args[0].lower()
    if head in ("status",):
        return _cmd_grounding(ctx, [])

    if head in ("on", "strict"):
        ctx.config.grounded_web_mode = "strict"
        ctx.agent.grounded_web_mode = "strict"
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded web mode → strict[/{THEME_SUCCESS}]")
        return ""

    if head in ("off",):
        ctx.config.grounded_web_mode = "off"
        ctx.agent.grounded_web_mode = "off"
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded web mode → off[/{THEME_SUCCESS}]")
        return ""

    if head == "retry":
        if len(args) < 2:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding retry <0-3>[/{THEME_WARN}]")
            return ""
        try:
            value = int(args[1])
        except ValueError:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding retry <0-3>[/{THEME_WARN}]")
            return ""
        value = max(0, min(3, value))
        ctx.config.grounded_retry = value
        ctx.agent.grounded_retry = value
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded retry → {value}[/{THEME_SUCCESS}]")
        return ""

    if head == "citations":
        if len(args) < 2 or args[1].lower() not in ("sources_only", "inline"):
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding citations <sources_only|inline>[/{THEME_WARN}]")
            return ""
        mode = args[1].lower()
        ctx.config.grounded_visible_citations = mode
        ctx.agent.grounded_visible_citations = mode
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded citations → {mode}[/{THEME_SUCCESS}]")
        return ""

    if head == "context":
        if len(args) < 2:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding context <800-40000>[/{THEME_WARN}]")
            return ""
        try:
            value = int(args[1])
        except ValueError:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding context <800-40000>[/{THEME_WARN}]")
            return ""
        value = max(800, min(40000, value))
        ctx.config.grounded_context_chars = value
        ctx.agent.grounded_context_chars = value
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded context chars → {value}[/{THEME_SUCCESS}]")
        return ""

    if head == "seconds":
        if len(args) < 2:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding seconds <20-1200>[/{THEME_WARN}]")
            return ""
        try:
            value = int(args[1])
        except ValueError:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding seconds <20-1200>[/{THEME_WARN}]")
            return ""
        value = max(20, min(1200, value))
        ctx.config.grounded_search_max_seconds = value
        ctx.agent.grounded_search_max_seconds = value
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded search seconds → {value}[/{THEME_SUCCESS}]")
        return ""

    if head == "rounds":
        if len(args) < 2:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding rounds <1-30>[/{THEME_WARN}]")
            return ""
        try:
            value = int(args[1])
        except ValueError:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding rounds <1-30>[/{THEME_WARN}]")
            return ""
        value = max(1, min(30, value))
        ctx.config.grounded_search_max_rounds = value
        ctx.agent.grounded_search_max_rounds = value
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded search rounds → {value}[/{THEME_SUCCESS}]")
        return ""

    if head == "per_round":
        if len(args) < 2:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding per_round <1-8>[/{THEME_WARN}]")
            return ""
        try:
            value = int(args[1])
        except ValueError:
            ctx.console.print("  [{THEME_WARN}]Usage: /grounding per_round <1-8>[/{THEME_WARN}]")
            return ""
        value = max(1, min(8, value))
        ctx.config.grounded_search_per_round = value
        ctx.agent.grounded_search_per_round = value
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ grounded search per_round → {value}[/{THEME_SUCCESS}]")
        return ""

    if head in ("fallback", "partial"):
        if len(args) < 2 or args[1].lower() not in ("on", "off"):
            ctx.console.print(f"  [{THEME_WARN}]Usage: /grounding {head} <on|off>[/{THEME_WARN}]")
            return ""
        enabled = args[1].lower() == "on"
        if head == "fallback":
            ctx.config.grounded_fallback_to_open_web = enabled
            ctx.agent.grounded_fallback_to_open_web = enabled
            label = "grounded fallback"
        else:
            ctx.config.grounded_partial_on_timeout = enabled
            ctx.agent.grounded_partial_on_timeout = enabled
            label = "grounded partial"
        ctx.config.save()
        mode_label = "on" if enabled else "off"
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ {label} → {mode_label}[/{THEME_SUCCESS}]")
        return ""

    ctx.console.print(
        "  [{THEME_WARN}]Usage: /grounding <on|off|strict|status> "
        "| /grounding retry <0-3> | /grounding citations <sources_only|inline> "
        "| /grounding context <800-40000> "
        "| /grounding seconds <20-1200> | /grounding rounds <1-30> "
        "| /grounding per_round <1-8> | /grounding fallback <on|off> "
        "| /grounding partial <on|off>[/{THEME_WARN}]"
    )
    return ""


def _cmd_display(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        ctx.console.print(
            f"  thinking: [bold]{ctx.agent.reasoning_display}[/bold]"
            f"  | web: [bold]{ctx.agent.web_display}[/bold]"
            f"  | answer: [bold]{ctx.agent.answer_style}[/bold]"
            f"  | tools: [bold]{ctx.agent.tool_parallelism}[/bold]"
            f"  | grounding: [bold]{ctx.agent.grounded_web_mode}[/bold]"
        )
        ctx.console.print("  Usage: /display thinking <off|summary|full> | /display web <brief|summary|full> | /display answer <concise|balanced|detailed> | /display tools <1-12>")
        return ""

    target = args[0].lower()
    if target == "thinking":
        if len(args) < 2 or args[1].lower() not in ("off", "summary", "full"):
            ctx.console.print("  [{THEME_WARN}]Usage: /display thinking <off|summary|full>[/{THEME_WARN}]")
            return ""
        mode = args[1].lower()
        ctx.config.reasoning_display = mode
        ctx.agent.reasoning_display = mode
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ thinking display → {mode}[/{THEME_SUCCESS}]")
        return ""

    if target == "web":
        if len(args) < 2 or args[1].lower() not in ("brief", "summary", "full"):
            ctx.console.print("  [{THEME_WARN}]Usage: /display web <brief|summary|full>[/{THEME_WARN}]")
            return ""
        mode = args[1].lower()
        ctx.config.web_display = mode
        ctx.agent.web_display = mode
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ web display → {mode}[/{THEME_SUCCESS}]")
        return ""

    if target == "answer":
        if len(args) < 2 or args[1].lower() not in ("concise", "balanced", "detailed"):
            ctx.console.print("  [{THEME_WARN}]Usage: /display answer <concise|balanced|detailed>[/{THEME_WARN}]")
            return ""
        style = args[1].lower()
        ctx.config.answer_style = style
        ctx.agent.answer_style = style
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ answer style → {style}[/{THEME_SUCCESS}]")
        return ""

    if target == "tools":
        if len(args) < 2:
            ctx.console.print("  [{THEME_WARN}]Usage: /display tools <1-12>[/{THEME_WARN}]")
            return ""
        try:
            value = int(args[1])
        except ValueError:
            ctx.console.print("  [{THEME_WARN}]Usage: /display tools <1-12>[/{THEME_WARN}]")
            return ""
        value = max(1, min(12, value))
        ctx.config.tool_parallelism = value
        ctx.agent.tool_parallelism = value
        ctx.config.save()
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ tool parallelism → {value}[/{THEME_SUCCESS}]")
        return ""

    ctx.console.print(f"  [{THEME_WARN}]Usage: /display thinking <off|summary|full> | /display web <brief|summary|full> | /display answer <concise|balanced|detailed> | /display stream <stable|smooth|ultra> | /display tools <1-12>[/{THEME_WARN}]")
    return ""


def _cmd_diff(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    git = ctx.tools.git
    if not git.available:
        ctx.console.print(f"  [{THEME_WARN}]Not a git repository.[/{THEME_WARN}]")
        return ""

    diff = git._run("diff", "--stat").stdout.strip()
    staged = git._run("diff", "--cached", "--stat").stdout.strip()
    if not diff and not staged:
        ctx.console.print(f"  [{THEME_DIM}]No changes.[/{THEME_DIM}]")
        return ""

    if staged:
        ctx.console.print(f"  [bold {THEME_SUCCESS}]staged[/bold {THEME_SUCCESS}]")
        for line in staged.splitlines():
            ctx.console.print(f"    [{THEME_DIM}]{line}[/{THEME_DIM}]")
    if diff:
        ctx.console.print(f"  [bold {THEME_WARN}]unstaged[/bold {THEME_WARN}]")
        for line in diff.splitlines():
            ctx.console.print(f"    [{THEME_DIM}]{line}[/{THEME_DIM}]")
    return ""


def _cmd_plan(ctx: CommandContext, args: list[str]) -> str:
    plan = ctx.agent.current_plan
    if not args:
        if not plan:
            ctx.console.print(f"  [{THEME_DIM}]No plan yet. Ask me to draft one first.[/{THEME_DIM}]")
            return ""
        ctx.console.print(f"\n  [bold {THEME_ACCENT}]▣ {plan.title}[/bold {THEME_ACCENT}]")
        status_icons = {"pending": "○", "executing": "◉", "done": "✓", "failed": "✗", "skipped": "–"}
        status_colors = {"done": THEME_SUCCESS, "failed": THEME_ERROR, "executing": THEME_WARN, "pending": THEME_DIM, "skipped": THEME_DIM}
        for step in plan.steps:
            icon = status_icons.get(step.status, "?")
            color = status_colors.get(step.status, THEME_DIM)
            ctx.console.print(
                f"  [{color}]{icon}[/{color}] [{THEME_DIM}]{step.index}.[/{THEME_DIM}] "
                f"[{THEME_INFO}][{step.action}][/{THEME_INFO}] "
                f"[#E6EDF3]`{step.target}`[/#E6EDF3] [{THEME_DIM}]— {step.description}[/{THEME_DIM}]"
            )
        ctx.console.print()
        return ""

    if args[0] == "execute":
        if not plan:
            ctx.console.print(f"  [{THEME_WARN}]No plan to execute. Ask for a plan first.[/{THEME_WARN}]")
            return ""
        if ctx.agent.mode != "agent":
            ctx.agent.mode = "agent"
            ctx.config.chat_mode = "agent"
            ctx.config.save()
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Switched to agent mode — executing plan...[/{THEME_SUCCESS}]")
        else:
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Executing plan in agent mode...[/{THEME_SUCCESS}]")

        steps_text = "\n".join(
            f"{s.index}. [{s.action}] `{s.target}` — {s.description}"
            for s in plan.steps if s.status == "pending"
        )
        instruction = (
            f"Execute this plan step by step. After each step, verify it succeeded "
            f"before moving to the next. Report progress as [N/{len(plan.steps)}].\n\n"
            f"## Plan: {plan.title}\n{steps_text}"
        )
        ctx.agent.chat(instruction)
        return ""

    if args[0] == "clear":
        ctx.agent.current_plan = None
        ctx.console.print(f"  [{THEME_SUCCESS}]✓ Plan cleared[/{THEME_SUCCESS}]")
        return ""

    ctx.console.print(f"  [{THEME_DIM}]Usage: /plan | /plan execute | /plan clear[/{THEME_DIM}]")
    return ""


def _cmd_reset(ctx: CommandContext, args: list[str]) -> str:
    _ = args
    ctx.agent.reset()
    ctx.console.print(f"  [{THEME_SUCCESS}]✓ Conversation cleared.[/{THEME_SUCCESS}]")
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
    "/grounding": _cmd_grounding,
    "/display": _cmd_display,
    "/diff": _cmd_diff,
    "/plan": _cmd_plan,
    "/reset": _cmd_reset,
}
