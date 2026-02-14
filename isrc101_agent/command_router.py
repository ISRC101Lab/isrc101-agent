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
from .rendering import get_icon
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

    # Record command usage for statistics
    if config.ui_state:
        config.ui_state.record_command_usage(cmd)

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
    """Enhanced session management with subcommands."""
    from .session import (
        list_sessions_enhanced, render_session_timeline,
        export_session_markdown, add_session_tag, get_session_tags,
        search_sessions
    )

    # No args: show list
    if not args:
        sessions = list_sessions_enhanced(10)
        if not sessions:
            ctx.console.print(f"  [{THEME_DIM}]No saved sessions[/{THEME_DIM}]")
            return ""

        table = Table(border_style=THEME_BORDER)
        table.add_column("Name", style=f"bold {THEME_ACCENT}")
        table.add_column("Messages", style="#E6EDF3", justify="right")
        table.add_column("Tags", style=THEME_INFO, max_width=20)
        table.add_column("Tokens", style=THEME_DIM, justify="right")
        table.add_column("Created", style=THEME_DIM)

        for session in sessions:
            tags_str = ", ".join(session["tags"][:3]) if session["tags"] else "-"
            if len(session["tags"]) > 3:
                tags_str += f" +{len(session['tags']) - 3}"

            table.add_row(
                session["name"],
                str(session["messages"]),
                tags_str,
                f"~{session['approx_tokens']}",
                session["created_at"]
            )

        ctx.console.print(Panel(
            table,
            title=f"[bold {THEME_ACCENT}]Recent Sessions[/bold {THEME_ACCENT}]",
            title_align="left",
            border_style=THEME_BORDER
        ))
        return ""

    subcommand = args[0].lower()

    # /session list — same as no args
    if subcommand == "list":
        return _cmd_sessions(ctx, [])

    # /session timeline — show current session timeline
    elif subcommand == "timeline":
        if not ctx.agent:
            ctx.console.print(f"  [{THEME_DIM}]No active agent session[/{THEME_DIM}]")
            return ""

        conversation = ctx.agent.conversation
        if not conversation:
            ctx.console.print(f"  [{THEME_DIM}]No messages in current session[/{THEME_DIM}]")
            return ""

        render_session_timeline(conversation, ctx.console)
        return ""

    # /session export [filename] — export current session
    elif subcommand == "export":
        if not ctx.agent:
            ctx.console.print(f"  [{THEME_DIM}]No active agent session[/{THEME_DIM}]")
            return ""

        # Get output path from args if provided
        output_path = args[1] if len(args) > 1 else None

        # Save current session first
        from .session import save_session
        metadata = {
            "model": getattr(ctx.agent.llm, 'model', 'unknown'),
            "mode": ctx.agent._mode,
            "tags": []
        }
        session_name = save_session(ctx.agent.conversation, metadata=metadata)

        # Export to markdown
        exported = export_session_markdown(session_name, output_path)
        if exported:
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Exported to: {exported}[/{THEME_SUCCESS}]")
        else:
            ctx.console.print(f"  [{THEME_ERROR}]Failed to export session[/{THEME_ERROR}]")
        return ""

    # /session tag <name> — add tag to current session
    elif subcommand == "tag":
        if len(args) < 2:
            ctx.console.print(f"  [{THEME_WARN}]Usage: /session tag <tag-name>[/{THEME_WARN}]")
            return ""

        if not ctx.agent:
            ctx.console.print(f"  [{THEME_DIM}]No active agent session[/{THEME_DIM}]")
            return ""

        # Save current session first
        from .session import save_session
        metadata = {
            "model": getattr(ctx.agent.llm, 'model', 'unknown'),
            "mode": ctx.agent._mode,
            "tags": []
        }
        session_name = save_session(ctx.agent.conversation, metadata=metadata)

        # Add tag
        tag = " ".join(args[1:])
        if add_session_tag(session_name, tag):
            ctx.console.print(f"  [{THEME_SUCCESS}]✓ Added tag: {tag}[/{THEME_SUCCESS}]")
        else:
            ctx.console.print(f"  [{THEME_ERROR}]Failed to add tag[/{THEME_ERROR}]")
        return ""

    # /session tags — show current session tags
    elif subcommand == "tags":
        if not ctx.agent:
            ctx.console.print(f"  [{THEME_DIM}]No active agent session[/{THEME_DIM}]")
            return ""

        # Save and get tags
        from .session import save_session
        metadata = {
            "model": getattr(ctx.agent.llm, 'model', 'unknown'),
            "mode": ctx.agent._mode,
            "tags": []
        }
        session_name = save_session(ctx.agent.conversation, metadata=metadata)
        tags = get_session_tags(session_name)

        if tags:
            ctx.console.print(f"  [{THEME_INFO}]Tags: {', '.join(tags)}[/{THEME_INFO}]")
        else:
            ctx.console.print(f"  [{THEME_DIM}]No tags[/{THEME_DIM}]")
        return ""

    # /session search <keyword> — search sessions
    elif subcommand == "search":
        if len(args) < 2:
            ctx.console.print(f"  [{THEME_WARN}]Usage: /session search <keyword>[/{THEME_WARN}]")
            return ""

        keyword = " ".join(args[1:])
        results = search_sessions(keyword, limit=10)

        if not results:
            ctx.console.print(f"  [{THEME_DIM}]No sessions found matching '{keyword}'[/{THEME_DIM}]")
            return ""

        table = Table(border_style=THEME_BORDER)
        table.add_column("Session", style=f"bold {THEME_ACCENT}")
        table.add_column("Matches", style="#E6EDF3", justify="right")
        table.add_column("Context", style=THEME_DIM, max_width=50)

        for result in results:
            context = result["first_match"]["context"]
            table.add_row(
                result["name"],
                str(result["matches"]),
                context
            )

        ctx.console.print(Panel(
            table,
            title=f"[bold {THEME_ACCENT}]Search Results: '{keyword}'[/bold {THEME_ACCENT}]",
            title_align="left",
            border_style=THEME_BORDER
        ))
        return ""

    else:
        ctx.console.print(f"  [{THEME_WARN}]Unknown subcommand: {subcommand}[/{THEME_WARN}]")
        ctx.console.print(f"  [{THEME_DIM}]Available: list, timeline, export, tag, tags, search[/{THEME_DIM}]")
        return ""


def _cmd_config(ctx: CommandContext, args: list[str]) -> str:
    from .config import CONFIG_FIELDS

    # No args: show all config
    if not args:
        _show_config_panel(ctx.console, ctx.config)
        return ""

    subcommand = args[0].lower()

    # /config diff — show differences from defaults
    if subcommand == "diff":
        diff = ctx.config.get_config_diff()
        modified = diff["modified"]
        defaults = diff["default"]

        if not modified:
            ctx.console.print(f"  [{THEME_DIM}]All settings at default values[/{THEME_DIM}]")
            return ""

        table = Table(border_style=THEME_BORDER, show_header=True, padding=(0, 1))
        table.add_column("Key", style=f"bold {THEME_ACCENT}", min_width=24)
        table.add_column("Current", style="#E6EDF3", min_width=16)
        table.add_column("Default", style=THEME_DIM, min_width=16)
        table.add_column("Status", style=THEME_WARN, width=8)

        for key in sorted(modified.keys()):
            info = modified[key]
            current_str = str(info["current"])
            if isinstance(info["current"], list):
                current_str = ", ".join(info["current"])
            default_str = str(info["default"])
            if isinstance(info["default"], list):
                default_str = ", ".join(info["default"])

            # Truncate long values
            if len(current_str) > 32:
                current_str = current_str[:29] + "..."
            if len(default_str) > 32:
                default_str = default_str[:29] + "..."

            table.add_row(key, current_str, default_str, f"[{THEME_WARN}]Modified[/{THEME_WARN}]")

        from rich.panel import Panel
        ctx.console.print()
        ctx.console.print(Panel(
            table,
            title=f"[bold {THEME_ACCENT}] Configuration Differences [/bold {THEME_ACCENT}]",
            title_align="left",
            border_style=THEME_BORDER,
            padding=(0, 1)
        ))
        ctx.console.print(f"  [{THEME_DIM}]{len(modified)} modified • {len(defaults)} at default[/{THEME_DIM}]")
        return ""

    # /config help <key> — show field documentation
    if subcommand == "help" and len(args) >= 2:
        key = args[1]
        if key not in CONFIG_FIELDS:
            ctx.console.print(f"  [{THEME_ERROR}]Unknown configuration key: {key}[/{THEME_ERROR}]")
            ctx.console.print(f"  [{THEME_DIM}]Use /config to see all available keys[/{THEME_DIM}]")
            return ""

        spec = CONFIG_FIELDS[key]
        current_value = ctx.config.get_config_value(key)

        # Format value for display
        value_str = str(current_value)
        if isinstance(current_value, list):
            value_str = ", ".join(current_value)

        ctx.console.print()
        ctx.console.print(f"  [bold {THEME_ACCENT}]{key}[/bold {THEME_ACCENT}]")
        ctx.console.print(f"  [{THEME_DIM}]{spec.description}[/{THEME_DIM}]")
        ctx.console.print()
        ctx.console.print(f"  Type:    [{THEME_INFO}]{spec.value_type}[/{THEME_INFO}]")
        ctx.console.print(f"  Current: [bold]{value_str}[/bold]")
        ctx.console.print(f"  Default: [{THEME_DIM}]{spec.default}[/{THEME_DIM}]")

        # Show valid values for enums
        if spec.value_type == "str" and spec.validator:
            # Try to extract valid values from error message
            is_valid, _, error_msg = spec.validator("__invalid__")
            if not is_valid and "Must be one of:" in error_msg:
                valid_part = error_msg.split("Must be one of:")[-1].strip()
                ctx.console.print(f"  Valid:   [{THEME_INFO}]{valid_part}[/{THEME_INFO}]")
        elif spec.value_type == "int" and spec.validator:
            # Try to extract range from error message
            is_valid, _, error_msg = spec.validator(-999999)
            if not is_valid and "between" in error_msg:
                ctx.console.print(f"  Range:   [{THEME_INFO}]{error_msg.replace('Must be ', '')}[/{THEME_INFO}]")

        ctx.console.print()
        return ""

    # /config set <key> <value> — set configuration value
    if subcommand == "set" and len(args) >= 3:
        key = args[1]
        value_str = " ".join(args[2:])

        if key not in CONFIG_FIELDS:
            ctx.console.print(f"  [{THEME_ERROR}]Unknown configuration key: {key}[/{THEME_ERROR}]")
            ctx.console.print(f"  [{THEME_DIM}]Use /config to see all available keys[/{THEME_DIM}]")
            return ""

        spec = CONFIG_FIELDS[key]

        # Coerce value to correct type
        if spec.value_type == "bool":
            # Parse boolean
            if value_str.lower() in ("true", "yes", "on", "1"):
                value = True
            elif value_str.lower() in ("false", "no", "off", "0"):
                value = False
            else:
                ctx.console.print(f"  [{THEME_ERROR}]Invalid boolean value. Use: true/false, yes/no, on/off, 1/0[/{THEME_ERROR}]")
                return ""
        elif spec.value_type == "int":
            try:
                value = int(value_str)
            except ValueError:
                ctx.console.print(f"  [{THEME_ERROR}]Invalid integer value[/{THEME_ERROR}]")
                return ""
        elif spec.value_type == "list":
            value = value_str
        else:
            value = value_str

        success, error_msg = ctx.config.set_config_value(key, value)
        if not success:
            ctx.console.print(f"  [{THEME_ERROR}]{error_msg}[/{THEME_ERROR}]")
            return ""

        # Get the coerced value for display
        final_value = ctx.config.get_config_value(key)
        value_display = str(final_value)
        if isinstance(final_value, list):
            value_display = ", ".join(final_value)

        ctx.console.print(f"  [{THEME_SUCCESS}]✓ Set {key} → {value_display}[/{THEME_SUCCESS}]")
        return ""

    # /config reset <key> — reset to default
    if subcommand == "reset" and len(args) >= 2:
        key = args[1]

        if key not in CONFIG_FIELDS:
            ctx.console.print(f"  [{THEME_ERROR}]Unknown configuration key: {key}[/{THEME_ERROR}]")
            ctx.console.print(f"  [{THEME_DIM}]Use /config to see all available keys[/{THEME_DIM}]")
            return ""

        spec = CONFIG_FIELDS[key]
        success, error_msg = ctx.config.reset_config_value(key)
        if not success:
            ctx.console.print(f"  [{THEME_ERROR}]{error_msg}[/{THEME_ERROR}]")
            return ""

        default_display = str(spec.default)
        if isinstance(spec.default, list):
            default_display = ", ".join(spec.default)

        ctx.console.print(f"  [{THEME_SUCCESS}]✓ Reset {key} → {default_display}[/{THEME_SUCCESS}]")
        return ""

    # /config <key> — show single config value details
    if len(args) == 1:
        key = args[0]
        if key not in CONFIG_FIELDS:
            ctx.console.print(f"  [{THEME_ERROR}]Unknown configuration key: {key}[/{THEME_ERROR}]")
            ctx.console.print(f"  [{THEME_DIM}]Use /config to see all available keys[/{THEME_DIM}]")
            return ""

        spec = CONFIG_FIELDS[key]
        current_value = ctx.config.get_config_value(key)

        # Format value for display
        value_str = str(current_value)
        if isinstance(current_value, list):
            value_str = ", ".join(current_value)

        is_modified = current_value != spec.default
        status_color = THEME_WARN if is_modified else THEME_DIM
        status_text = "Modified" if is_modified else "Default"

        ctx.console.print()
        ctx.console.print(f"  [bold {THEME_ACCENT}]{key}[/bold {THEME_ACCENT}]")
        ctx.console.print(f"  [{THEME_DIM}]{spec.description}[/{THEME_DIM}]")
        ctx.console.print()
        ctx.console.print(f"  Type:    [{THEME_INFO}]{spec.value_type}[/{THEME_INFO}]")
        ctx.console.print(f"  Current: [bold]{value_str}[/bold]")
        ctx.console.print(f"  Default: [{THEME_DIM}]{spec.default}[/{THEME_DIM}]")
        ctx.console.print(f"  Status:  [{status_color}]{status_text}[/{status_color}]")

        # Show valid values/range
        if spec.value_type == "str" and spec.validator:
            is_valid, _, error_msg = spec.validator("__invalid__")
            if not is_valid and "Must be one of:" in error_msg:
                valid_part = error_msg.split("Must be one of:")[-1].strip()
                ctx.console.print(f"  Valid:   [{THEME_INFO}]{valid_part}[/{THEME_INFO}]")
        elif spec.value_type == "int" and spec.validator:
            is_valid, _, error_msg = spec.validator(-999999)
            if not is_valid and "between" in error_msg:
                ctx.console.print(f"  Range:   [{THEME_INFO}]{error_msg.replace('Must be ', '')}[/{THEME_INFO}]")

        ctx.console.print()
        ctx.console.print(f"  [{THEME_DIM}]Use /config set {key} <value> to change[/{THEME_DIM}]")
        ctx.console.print(f"  [{THEME_DIM}]Use /config reset {key} to restore default[/{THEME_DIM}]")
        ctx.console.print()
        return ""

    # Invalid usage
    ctx.console.print("  Usage:")
    ctx.console.print("    /config                      Show all configuration")
    ctx.console.print("    /config <key>                Show details for one key")
    ctx.console.print("    /config set <key> <value>    Set configuration value")
    ctx.console.print("    /config reset <key>          Reset to default")
    ctx.console.print("    /config diff                 Show differences from defaults")
    ctx.console.print("    /config help <key>           Show field documentation")
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

    # Command usage statistics (from UI state)
    if ctx.config.ui_state:
        ui_stats = ctx.config.ui_state.get_stats_summary()
        top_commands = ui_stats.get("top_commands", [])

        if top_commands:
            ctx.console.print()
            cmd_table = Table(show_header=True, border_style=THEME_BORDER, padding=(0, 1), box=None)
            cmd_table.add_column("Command", style=f"bold {THEME_ACCENT}", min_width=16)
            cmd_table.add_column("Usage", justify="right", style="#E6EDF3")

            for cmd, count in top_commands:
                cmd_table.add_row(cmd, f"{count}")

            ctx.console.print(Panel(
                cmd_table,
                title=f"[bold {THEME_ACCENT}] Top Commands (All Time) [/bold {THEME_ACCENT}]",
                title_align="left",
                border_style=THEME_BORDER,
                padding=(0, 1)
            ))

            # Show summary stats
            ctx.console.print()
            summary_text = (
                f"  Total commands executed: [bold]{ui_stats.get('total_commands_executed', 0):,}[/bold]  |  "
                f"Unique commands used: [bold]{ui_stats.get('unique_commands_used', 0)}[/bold]  |  "
                f"Projects tracked: [bold]{ui_stats.get('projects_tracked', 0)}[/bold]"
            )
            ctx.console.print(f"[{THEME_DIM}]{summary_text}[/{THEME_DIM}]")

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
        if ctx.config.ui_state:
            ctx.config.ui_state.set_project_setting("reasoning_display", mode)
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
        if ctx.config.ui_state:
            ctx.config.ui_state.set_project_setting("web_display", mode)
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
        status_icons = {
            "pending": get_icon("○"),
            "executing": get_icon("◉"),
            "done": get_icon("✓"),
            "failed": get_icon("✗"),
            "skipped": get_icon("–")
        }
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


def _cmd_theme(ctx: CommandContext, args: list[str]) -> str:
    from . import theme

    if not args:
        available = theme.list_themes()
        current = ctx.config.theme
        ctx.console.print(f"  Current theme: [bold {THEME_ACCENT}]{current}[/bold {THEME_ACCENT}]")
        ctx.console.print(f"  [{THEME_DIM}]Available:[/{THEME_DIM}] {', '.join(available)}")
        ctx.console.print(f"  [{THEME_DIM}]Usage: /theme <name> | /theme list[/{THEME_DIM}]")
        return ""

    if args[0] == "list":
        available = theme.list_themes()
        current = ctx.config.theme
        table = Table(border_style=THEME_BORDER)
        table.add_column("", width=2)
        table.add_column("Theme", style=f"bold {THEME_ACCENT}")
        for name in available:
            marker = f"[{THEME_SUCCESS}]●[/{THEME_SUCCESS}]" if name == current else " "
            table.add_row(marker, name)
        ctx.console.print(Panel(table, title=f"[bold {THEME_ACCENT}] Themes [/bold {THEME_ACCENT}]",
                                title_align="left", border_style=THEME_BORDER))
        return ""

    theme_name = args[0].lower()
    if theme.set_theme(theme_name):
        ctx.config.theme = theme_name
        ctx.config.save()

        # Save theme preference to UI state
        if ctx.config.ui_state:
            ctx.config.ui_state.set_project_setting("theme", theme_name)

        ctx.console.print(f"  [{THEME_SUCCESS}]✓ Theme switched to: {theme_name}[/{THEME_SUCCESS}]")
        ctx.console.print(f"  [{THEME_DIM}]Note: Restart the agent to see full theme changes[/{THEME_DIM}]")
    else:
        available = theme.list_themes()
        ctx.console.print(f"  [{THEME_WARN}]Unknown theme: {theme_name}[/{THEME_WARN}]")
        ctx.console.print(f"  [{THEME_DIM}]Available:[/{THEME_DIM}] {', '.join(available)}")
    return ""


def _cmd_crew(ctx: CommandContext, args: list[str]) -> str:
    from .crew import Crew
    crew = Crew(ctx.config, ctx.console)
    result = crew.run(" ".join(args))
    if result:
        from .rendering import render_assistant_message
        render_assistant_message(ctx.console, result)
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
    "/theme": _cmd_theme,
    "/crew": _cmd_crew,
}
