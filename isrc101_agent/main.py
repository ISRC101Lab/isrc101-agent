"""
isrc101-agent v1.0.0 — AI coding assistant for your terminal.

Command: isrc run
"""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.completion import WordCompleter

from .config import Config, CONFIG_DIR, CONFIG_FILE, ModelPreset
from .llm import LLMAdapter
from .tools import ToolRegistry
from .agent import Agent
from . import __version__

console = Console()

BANNER = rf"""[bold cyan]
   ┌─────────────────────────────────────┐
   │     isrc101-agent  v{__version__:<14s}│
   │      AI coding assistant · terminal │
   └─────────────────────────────────────┘[/bold cyan]"""

HELP_TEXT = """
[bold cyan]Commands:[/bold cyan]
  /model             Select model interactively (↑↓ Enter)
  /model list        Show all models as table
  /model add <n> <provider> <model> [api-base] [api-key]
  /model rm <n>   Remove a model preset
  /mode <m>          Switch: code | ask | architect
  /compact           Summarize old conversation to free context
  /undo              Revert last agent file changes (git checkout)
  /diff              Show uncommitted changes in project
  /config            Show configuration
  /stats             Session statistics
  /git               Git status and log
  /reset             Clear conversation
  /help              Show this help
  /quit              Exit

[bold cyan]Chat modes:[/bold cyan]
  code        Read + write + run commands (default)
  ask         Read-only analysis
  architect   Plan & discuss, no changes

[bold cyan]Tips:[/bold cyan]
  Esc → Enter   Multi-line input (or paste multi-line text)
"""

# ── Prompt styles per mode ─────────────────────────
MODE_COLORS = {"code": "#6ec1e4", "ask": "#a0d468", "architect": "#f6bb42"}


def _make_prompt(mode: str) -> HTML:
    color = MODE_COLORS.get(mode, "#6ec1e4")
    return HTML(f'<style fg="{color}" bold="true">isrc101</style>'
                f'<style fg="#888888"> [{mode}] ❯ </style>')


# ── Interactive model selector ─────────────────────

def _interactive_model_select(config: Config) -> str:
    """Interactive model selector with search, filtering, and enhanced navigation."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout

    models = list(config.models.values())
    if not models:
        return ""

    # 找到当前激活模型的索引
    current_idx = 0
    for i, m in enumerate(models):
        if m.name == config.active_model:
            current_idx = i
            break

    selected = [current_idx]  # 当前选中的模型索引
    result = [""]  # 选择结果
    search_query = [""]  # 搜索查询
    filtered_indices = [list(range(len(models)))]  # 过滤后的模型索引
    
    def filter_models():
        """根据搜索查询过滤模型"""
        if not search_query[0]:
            filtered_indices[0] = list(range(len(models)))
            return
        
        query = search_query[0].lower()
        filtered = []
        for i, m in enumerate(models):
            # 在名称、描述、模型ID中搜索
            if (query in m.name.lower() or 
                query in m.description.lower() or
                query in m.model.lower()):
                filtered.append(i)
        filtered_indices[0] = filtered
        
        # 如果当前选中的不在过滤结果中，调整到第一个可用项
        if selected[0] not in filtered_indices[0] and filtered_indices[0]:
            selected[0] = filtered_indices[0][0]

    def get_text():
        lines = []
        
        # 标题行，显示搜索状态
        title = "  Select model"
        if search_query[0]:
            title += f"  [search: {search_query[0]}]"
        title += "  (↑↓/jk move · / search · g/G first/last · Enter confirm · q cancel)"
        lines.append(("bold", title + "\n\n"))
        
        # 显示过滤后的模型
        for idx_in_filtered, model_idx in enumerate(filtered_indices[0]):
            m = models[model_idx]
            is_active = m.name == config.active_model
            is_sel = model_idx == selected[0]

            # 前缀和样式
            if is_sel:
                prefix = " ▸ "
                style = "bold reverse"
            elif is_active:
                prefix = " ● "
                style = "bold fg:ansigreen"
            else:
                prefix = "   "
                style = ""

            # API 密钥状态
            if m.resolve_api_key():
                key_icon = "🔑"
                key_style = "green"
            else:
                key_icon = "❌"
                key_style = "red"
            
            # 准备显示文本（带高亮）
            name_display = m.name
            desc_display = m.description
            
            # 搜索高亮
            if search_query[0]:
                query = search_query[0].lower()
                
                # 高亮名称中的匹配
                if query in m.name.lower():
                    start = m.name.lower().find(query)
                    highlighted = f"[reverse]{m.name[start:start+len(query)]}[/reverse]"
                    name_display = m.name[:start] + highlighted + m.name[start+len(query):]
                
                # 高亮描述中的匹配
                if query in m.description.lower():
                    start = m.description.lower().find(query)
                    highlighted = f"[reverse]{m.description[start:start+len(query)]}[/reverse]"
                    desc_display = m.description[:start] + highlighted + m.description[start+len(query):]
            
            # 构建行
            line = f"{prefix}{name_display:<18} {desc_display:<28} [{key_style}]{key_icon}[/{key_style}]"
            
            # 添加API基础信息（如果可用且不是本地）
            if m.api_base and "localhost" not in m.api_base:
                base_display = m.api_base.replace("https://", "").replace("http://", "")
                if len(base_display) > 25:
                    base_display = base_display[:22] + "..."
                line += f"  @ {base_display}"
            
            lines.append((style, line + "\n"))
        
        # 如果没有匹配结果
        if not filtered_indices[0]:
            lines.append(("fg:ansiyellow", "  No models match your search.\n"))
        
        lines.append(("", "\n"))
        
        # 底部信息栏
        info_lines = []
        info_lines.append("  ● current  ▸ cursor")
        
        if search_query[0]:
            info_lines.append(f"  Search: '{search_query[0]}' ({len(filtered_indices[0])}/{len(models)} models)")
        else:
            info_lines.append(f"  {len(models)} models available")
        
        # 快捷键提示
        shortcuts = [
            ("↑/k", "Up"),
            ("↓/j", "Down"),
            ("g", "First"),
            ("G", "Last"),
            ("/", "Search"),
            ("Esc", "Clear/Cancel"),
            ("Enter", "Select"),
            ("q", "Cancel")
        ]
        shortcut_text = "  " + "  ".join([f"{key}: {desc}" for key, desc in shortcuts])
        info_lines.append(shortcut_text)
        
        for line in info_lines:
            lines.append(("fg:ansigray", line + "\n"))
        
        return lines

    # 初始化过滤
    filter_models()
    
    kb = KeyBindings()
    is_searching = [False]  # 是否处于搜索输入模式

    # 导航快捷键
    @kb.add("up")
    @kb.add("k")
    def _up(event):
        if filtered_indices[0]:
            current_pos = filtered_indices[0].index(selected[0])
            new_pos = max(0, current_pos - 1)
            selected[0] = filtered_indices[0][new_pos]

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        if filtered_indices[0]:
            current_pos = filtered_indices[0].index(selected[0])
            new_pos = min(len(filtered_indices[0]) - 1, current_pos + 1)
            selected[0] = filtered_indices[0][new_pos]

    @kb.add("g")
    def _first(event):
        if filtered_indices[0]:
            selected[0] = filtered_indices[0][0]

    @kb.add("G")
    def _last(event):
        if filtered_indices[0]:
            selected[0] = filtered_indices[0][-1]

    # 搜索功能
    @kb.add("/")
    def _start_search(event):
        is_searching[0] = True
        search_query[0] = ""

    @kb.add("escape")
    def _escape(event):
        if is_searching[0] or search_query[0]:
            # 清除搜索
            search_query[0] = ""
            is_searching[0] = False
            filter_models()
        else:
            # 取消选择
            result[0] = ""
            event.app.exit()

    @kb.add("backspace")
    def _backspace(event):
        if search_query[0]:
            search_query[0] = search_query[0][:-1]
            filter_models()

    # 字符输入（用于搜索）
    @kb.add("<any>")
    def _any_key(event):
        if is_searching[0] and len(event.key_sequence[0].data) == 1:
            char = event.key_sequence[0].data
            # 只接受可打印字符
            if char.isprintable() and char not in ['\r', '\n', '\t']:
                search_query[0] += char
                filter_models()
        elif not is_searching[0] and event.key_sequence[0].data == "q":
            # 直接按q取消
            result[0] = ""
            event.app.exit()

    # 确认选择
    @kb.add("enter")
    def _enter(event):
        if is_searching[0]:
            # 结束搜索模式
            is_searching[0] = False
        else:
            # 确认选择
            result[0] = models[selected[0]].name
            event.app.exit()

    control = FormattedTextControl(get_text)
    window = Window(content=control, always_hide_cursor=True)
    layout = Layout(HSplit([window]))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)

    try:
        app.run()
    except (KeyboardInterrupt, EOFError):
        return ""

    return result[0]


# ── CLI ────────────────────────────────────────────

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
    console.print(BANNER)
    config = Config.load(project_dir)

    # CLI overrides
    if model:
        if model in config.models:
            config.active_model = model
        else:
            config.models["_cli"] = ModelPreset(
                name="_cli", provider="openai", model=model,
                api_base=api_base, api_key=api_key or "not-needed",
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

    preset = config.get_active_preset()
    if api_key:
        preset.api_key = api_key
    if api_base:
        preset.api_base = api_base
    preset.apply_to_env()  # fallback env vars

    project_root = Path(config.project_root).resolve()
    if not project_root.is_dir():
        console.print(f"[red]Error: '{project_dir}' is not a valid directory.[/red]")
        sys.exit(1)

    _show_startup(config)

    llm = LLMAdapter(**preset.get_llm_kwargs())
    tools = ToolRegistry(project_root=str(project_root),
                          blocked_commands=config.blocked_commands,
                          command_timeout=config.command_timeout,
                          commit_prefix=config.commit_prefix)
    agent = Agent(llm=llm, tools=tools, max_iterations=config.max_iterations,
                  auto_confirm=config.auto_confirm, chat_mode=config.chat_mode,
                  auto_commit=config.auto_commit,
                  project_instructions=config.project_instructions)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Slash command auto-completion
    slash_completer = WordCompleter(
        ["/help", "/model", "/model list", "/mode", "/mode code", "/mode ask",
         "/mode architect", "/compact", "/undo", "/diff", "/config",
         "/stats", "/git", "/reset", "/quit"],
        sentence=True,
    )

    session = PromptSession(history=FileHistory(str(CONFIG_DIR / "history.txt")),
                            multiline=False,
                            completer=slash_completer,
                            complete_while_typing=False)

    # Multi-line keybinding: Esc then Enter inserts a newline
    repl_kb = KeyBindings()

    @repl_kb.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    # ── REPL ─────────────────────────────────
    while True:
        try:
            prompt_html = _make_prompt(agent.mode)
            user_input = session.prompt(prompt_html, key_bindings=repl_kb).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break
        if not user_input:
            continue
        if user_input.startswith("/"):
            result = _handle_command(user_input, agent, config, llm, tools)
            if result == "quit":
                break
            continue
        try:
            agent.chat(user_input)
        except KeyboardInterrupt:
            console.print("\n[yellow]  Interrupted.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]  Error: {e}[/red]")
            if config.verbose:
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")


# ── Slash commands ─────────────────────────────────

# All slash commands in order of priority for prefix matching
_SLASH_COMMANDS = [
    "/help", "/model", "/mode", "/compact", "/config",
    "/stats", "/git", "/undo", "/diff", "/reset", "/quit",
]
# Aliases that should match exactly (no prefix matching)
_SLASH_ALIASES = {"/h": "/help", "/?": "/help", "/exit": "/quit", "/q": "/quit"}


def _resolve_command(raw_cmd: str) -> str:
    """Resolve a (possibly abbreviated) slash command via prefix matching.

    Rules:
      1. Exact match or known alias → return canonical command.
      2. Unique prefix match → return the matched command.
      3. Ambiguous → return empty string (caller prints hint).
      4. No match → return original (caller handles unknown).
    """
    cmd = raw_cmd.lower()
    # Exact match
    if cmd in _SLASH_COMMANDS:
        return cmd
    if cmd in _SLASH_ALIASES:
        return _SLASH_ALIASES[cmd]

    # Prefix match
    matches = [c for c in _SLASH_COMMANDS if c.startswith(cmd)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        options = ", ".join(f"[bold]{m}[/bold]" for m in matches)
        console.print(f"  [yellow]Ambiguous: {cmd} → {options}[/yellow]")
        return ""
    # No match — return as-is so caller can print "unknown"
    return cmd


def _handle_command(command: str, agent: Agent, config: Config,
                    llm: LLMAdapter, tools: ToolRegistry) -> str:
    parts = command.split()
    raw_cmd = parts[0].lower()
    args = parts[1:]

    cmd = _resolve_command(raw_cmd)
    if not cmd:
        return ""  # ambiguous, already printed hint

    if cmd == "/quit":
        console.print("[dim]Goodbye![/dim]")
        return "quit"

    elif cmd == "/help":
        console.print(HELP_TEXT)

    elif cmd == "/model":
        if not args:
            name = _interactive_model_select(config)
            if name and name != config.active_model:
                _switch_model(config, name, llm)
            elif name:
                console.print(f"  [dim]Already on '{name}'[/dim]")

        elif args[0] == "list":
            _show_model_table(config)

        elif args[0] == "add" and len(args) >= 4:
            name, provider, model_str = args[1], args[2], args[3]
            ab = args[4] if len(args) > 4 else None
            ak = args[5] if len(args) > 5 else None
            config.models[name] = ModelPreset(
                name=name, provider=provider, model=model_str,
                api_base=ab, api_key=ak, description=f"{provider}/{model_str}",
            )
            config.save()
            console.print(f"  [green]✓ Added '{name}'[/green]")

        elif args[0] == "add":
            console.print("  Usage: /model add <n> <provider> <model> [api-base] [api-key]")

        elif args[0] == "rm" and len(args) >= 2:
            name = args[1]
            if name == config.active_model:
                console.print(f"  [yellow]Cannot remove active model. Switch first.[/yellow]")
            elif name in config.models:
                del config.models[name]
                config.save()
                console.print(f"  [green]✓ Removed '{name}'[/green]")
            else:
                console.print(f"  [yellow]Not found: '{name}'[/yellow]")

        else:
            name = args[0]
            if name in config.models:
                _switch_model(config, name, llm)
            else:
                console.print(f"  [yellow]Unknown: '{name}'. Use /model to browse.[/yellow]")

    elif cmd == "/mode":
        if not args:
            console.print(f"  Current: [bold]{agent.mode}[/bold]  (code | ask | architect)")
        elif args[0] in ("code", "ask", "architect"):
            old_mode = agent.mode
            agent.mode = args[0]
            console.print(f"  [green]✓ Mode → {args[0]}[/green]")
            if old_mode != args[0] and len(agent.conversation) > 2:
                console.print("  [dim]💡 Tip: conversation history preserved. Use /reset to start fresh.[/dim]")
        else:
            console.print(f"  [yellow]Unknown: {args[0]}[/yellow]")

    elif cmd == "/config":
        table = Table(show_header=False, border_style="dim", padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for k, v in config.summary().items():
            table.add_row(k, str(v))
        console.print(Panel(table, title="[bold]Configuration[/bold]", border_style="dim"))

    elif cmd == "/stats":
        stats = agent.get_stats()
        table = Table(show_header=False, border_style="dim", padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        for k, v in stats.items():
            table.add_row(k, f"{v:,}" if isinstance(v, int) else str(v))
        console.print(Panel(table, title="[bold]Session[/bold]", border_style="dim"))

    elif cmd == "/compact":
        count = agent.compact_conversation()
        if count > 0:
            console.print(f"  [green]✓ Compacted {count} old messages into summary[/green]")
        else:
            console.print("  [dim]Nothing to compact (≤4 messages)[/dim]")

    elif cmd == "/git":
        git = tools.git
        if not git.available:
            console.print("  [yellow]Not a git repository.[/yellow]")
        else:
            console.print(f"  [bold]Branch:[/bold] {git.get_current_branch()}")
            console.print(f"  [bold]Status:[/bold]\n{git.status_short()}")
            console.print(f"  [bold]Recent:[/bold]\n{git.get_log(5)}")

    elif cmd == "/undo":
        git = tools.git
        if not git.available:
            console.print("  [yellow]Not a git repository — cannot undo.[/yellow]")
        elif not git.has_changes():
            console.print("  [dim]No uncommitted changes to undo.[/dim]")
        else:
            console.print(f"  [dim]Current changes:[/dim]")
            console.print(f"  {git.status_short()}")
            try:
                ans = console.input("  Revert all uncommitted changes? (y/n): ").strip().lower()
                if ans in ("y", "yes"):
                    git._run("checkout", ".")
                    git._run("clean", "-fd")
                    console.print("  [green]✓ Reverted all uncommitted changes[/green]")
                else:
                    console.print("  [dim]Cancelled[/dim]")
            except (KeyboardInterrupt, EOFError):
                console.print("  [dim]Cancelled[/dim]")

    elif cmd == "/diff":
        git = tools.git
        if not git.available:
            console.print("  [yellow]Not a git repository.[/yellow]")
        else:
            diff = git._run("diff", "--stat").stdout.strip()
            staged = git._run("diff", "--cached", "--stat").stdout.strip()
            if not diff and not staged:
                console.print("  [dim]No changes.[/dim]")
            else:
                if staged:
                    console.print(f"  [bold green]Staged:[/bold green]\n  {staged}")
                if diff:
                    console.print(f"  [bold yellow]Unstaged:[/bold yellow]\n  {diff}")

    elif cmd == "/reset":
        agent.reset()
        console.print("  [green]✓ Conversation cleared.[/green]")

    else:
        console.print(f"  [yellow]Unknown: {cmd}. Try /help[/yellow]")
    return ""


def _switch_model(config: Config, name: str, llm: LLMAdapter):
    config.set_active_model(name)
    preset = config.get_active_preset()
    preset.apply_to_env()  # fallback env vars
    kw = preset.get_llm_kwargs()
    llm.model = kw["model"]
    llm.api_base = kw["api_base"]
    llm.api_key = kw["api_key"]
    llm.temperature = kw["temperature"]
    llm.max_tokens = kw["max_tokens"]
    llm.context_window = kw["context_window"]
    console.print(f"  [green]✓ Switched → [bold]{name}[/bold] ({preset.model})[/green]")
    if preset.api_base:
        console.print(f"    [dim]{preset.api_base}[/dim]")


def _show_model_table(config: Config):
    table = Table(border_style="dim")
    table.add_column("", width=2)
    table.add_column("Name", style="bold")
    table.add_column("Model")
    table.add_column("API Base")
    table.add_column("Key")
    table.add_column("Description")
    for m in config.list_models():
        marker = "[green]●[/green]" if m["active"] else " "
        table.add_row(marker, m["name"], m["model"], m["api_base"], m["key"], m["desc"])
    console.print(Panel(table, title="[bold]Models[/bold]", border_style="dim"))


def _show_startup(config: Config):
    preset = config.get_active_preset()
    key = preset.resolve_api_key()

    info = (
        f"  [dim]Model[/dim]   [bold]{config.active_model}[/bold] [dim]→ {preset.model}[/dim]\n"
        f"  [dim]Mode[/dim]    [bold]{config.chat_mode}[/bold]\n"
        f"  [dim]Project[/dim] {config.project_root}\n"
    )
    if preset.api_base:
        info += f"  [dim]API[/dim]     {preset.api_base}\n"
    info += f"  [dim]Key[/dim]     {'[green]✓[/green]' if key else '[red]✗ not set[/red]'}\n"
    info += f"  [dim]Context[/dim] {preset.context_window:,} tokens (max_tokens={preset.max_tokens:,})\n"
    if config.project_instructions:
        info += f"  [dim]AGENT.md[/dim] [green]✓[/green]\n"
    info += f"  [dim]Config[/dim]  {config._config_source}"

    console.print(Panel(
        info,
        title="[bold cyan]isrc101-agent[/bold cyan]",
        subtitle="[dim]/help · /model · Ctrl+C to cancel[/dim]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print()


# ── One-shot ───────────────────────────────────────

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
    llm = LLMAdapter(**preset.get_llm_kwargs())
    tools = ToolRegistry(project_root=str(Path(config.project_root).resolve()),
                          commit_prefix=config.commit_prefix)
    agent = Agent(llm=llm, tools=tools, auto_confirm=True, chat_mode=config.chat_mode,
                  project_instructions=config.project_instructions)
    agent.chat(" ".join(message))


@cli.command("config")
def config_cmd():
    """Show configuration."""
    cfg = Config.load()
    table = Table(show_header=False, border_style="dim", padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for k, v in cfg.summary().items():
        table.add_row(k, str(v))
    console.print(Panel(table, title="[bold]Configuration[/bold]", border_style="dim"))


if __name__ == "__main__":
    cli()
