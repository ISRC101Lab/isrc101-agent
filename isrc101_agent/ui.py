"""Terminal UI primitives and Codex-like styling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from prompt_toolkit.completion import Completion, Completer
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style

THEME_ACCENT = "#7FA6D9"
THEME_PROMPT = "#B7C6D8"

# ── Gradient color system ─────────────────────────
GRADIENT_STOPS: List[Tuple[int, int, int]] = [
    (70, 130, 220),    # deep blue
    (127, 166, 217),   # theme accent
    (100, 200, 230),   # cyan
    (87, 219, 156),    # teal-green
]


def _lerp_color(colors: List[Tuple[int, int, int]], t: float) -> Tuple[int, int, int]:
    """Interpolate through multiple RGB color stops (t in 0..1)."""
    t = max(0.0, min(1.0, t))
    n = len(colors) - 1
    idx = min(int(t * n), n - 1)
    lt = (t * n) - idx
    r1, g1, b1 = colors[idx]
    r2, g2, b2 = colors[idx + 1]
    return int(r1 + (r2 - r1) * lt), int(g1 + (g2 - g1) * lt), int(b1 + (b2 - b1) * lt)

PTK_STYLE = Style.from_dict({
    # ── Completion menu — transparent (inherits terminal bg) ──
    "completion-menu":                            "bg:default",
    "completion-menu.completion":                  "bg:default #6E7681",
    "completion-menu.completion.current":          "bg:default #E6EDF3 bold",
    "completion-menu.meta.completion":             "bg:default #6E7681",
    "completion-menu.meta.completion.current":     "bg:default #6E7681",
    "completion-menu.multi-column-meta":           "bg:default #484F58",
    "completion-menu.multi-column-meta.current":   "bg:default #484F58",
    # ── Scrollbar ──
    "scrollbar.background": "bg:default",
    "scrollbar.button":     "bg:default #484F58",
})


@dataclass(frozen=True)
class SlashCommandSpec:
    command: str
    usage: str
    description: str
    keywords: tuple[str, ...] = ()


SLASH_COMMAND_SPECS: tuple[SlashCommandSpec, ...] = (
    SlashCommandSpec("/help",     "/help",        "Show available commands and keyboard shortcuts", ("docs", "usage", "commands")),
    SlashCommandSpec("/model",    "/model",       "Switch between configured model presets", ("llm", "provider", "preset")),
    SlashCommandSpec("/mode",     "/mode",        "Switch between agent and ask modes", ("agent", "ask", "permissions")),
    SlashCommandSpec("/plan",     "/plan",        "View current parsed plan or execute it", ("plan", "execute", "steps")),
    SlashCommandSpec("/skills",   "/skills",      "Enable or disable skill plugins for this session", ("workflow", "plugin", "ability")),
    SlashCommandSpec("/web",      "/web",         "Toggle web search and URL fetching on or off", ("fetch", "url", "docs")),
    SlashCommandSpec("/grounding", "/grounding",   "Control strict grounded web-answer validation", ("citations", "evidence", "hallucination")),
    SlashCommandSpec("/display",  "/display",     "Configure thinking display, answer style, and tool output", ("thinking", "summary", "verbose", "concise", "tools", "parallel")),
    SlashCommandSpec("/save",     "/save [name]", "Save the current conversation to a named session", ("session", "history")),
    SlashCommandSpec("/load",     "/load [name]", "Restore a previously saved conversation session", ("session", "history")),
    SlashCommandSpec("/sessions", "/sessions",    "List all saved sessions with message counts", ("session", "history")),
    SlashCommandSpec("/compact",  "/compact",     "Summarize conversation history to free up context", ("context", "tokens")),
    SlashCommandSpec("/undo",     "/undo",        "Revert the last file change made by the agent", ("revert", "rollback")),
    SlashCommandSpec("/diff",     "/diff",        "Show uncommitted changes as a unified diff", ("git", "changes", "patch")),
    SlashCommandSpec("/config",   "/config",      "Display current configuration and model settings", ("settings", "model")),
    SlashCommandSpec("/stats",    "/stats",       "Show token usage and cost for this session", ("tokens", "usage", "cost")),
    SlashCommandSpec("/git",      "/git",         "Show git branch, status, and recent commits", ("branch", "commit", "status")),
    SlashCommandSpec("/reset",    "/reset",       "Clear conversation history and start fresh", ("clear", "conversation")),
    SlashCommandSpec("/quit",     "/quit",        "Exit the session (auto-saves conversation)", ("exit",)),
)

SLASH_COMMANDS = [spec.command for spec in SLASH_COMMAND_SPECS]
MAX_SLASH_MENU_ITEMS = 18


def build_banner(version: str) -> str:
    return (
        f"[bold {THEME_ACCENT}]isrc101-agent[/bold {THEME_ACCENT}] "
        f"[#6E7681]v{version} · AI coding assistant[/#6E7681]"
    )


def render_help(console) -> None:
    """Render a polished help panel using Rich."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns

    # ── Commands table ──
    table = Table(
        show_header=False, show_edge=False, box=None,
        padding=(0, 1), pad_edge=False,
    )
    table.add_column("cmd", min_width=16, style="bold #E6EDF3")
    table.add_column("desc", style="#8B949E")

    for spec in SLASH_COMMAND_SPECS:
        table.add_row(spec.usage, spec.description)

    console.print()
    console.print(Panel(
        table,
        title=f"[bold {THEME_ACCENT}] Commands [/bold {THEME_ACCENT}]",
        title_align="left",
        border_style="#30363D",
        padding=(1, 2),
    ))

    # ── Keyboard shortcuts ──
    keys = Text()
    shortcuts = [
        ("Esc+Enter", "multi-line"),
        ("/", "command menu"),
        ("Ctrl-C", "cancel"),
        ("Ctrl-D ×2", "exit"),
    ]
    for i, (key, desc) in enumerate(shortcuts):
        if i > 0:
            keys.append("  ·  ", style="#6E7681")
        keys.append(key, style=f"bold {THEME_ACCENT}")
        keys.append(f" {desc}", style="#8B949E")

    console.print(f"  ", end="")
    console.print(keys)
    console.print()


# Legacy compat — kept for any external references
HELP_TEXT = ""


def make_prompt_html(mode: str = "agent") -> HTML:
    mode_colors = {"agent": "#57DB9C", "ask": "#E3B341"}
    mc = mode_colors.get(mode, "#8B949E")
    return HTML(
        f'<style fg="{THEME_ACCENT}" bold="true">isrc101</style>'
        f'<style fg="#30363D"> </style>'
        f'<style fg="{mc}">{mode}</style>'
        f'<style fg="#30363D"> › </style>'
    )


def render_startup(console, config) -> None:
    from rich.panel import Panel
    from rich.style import Style as RichStyle
    from rich.table import Table
    from rich.text import Text
    from rich.color import Color

    preset = config.get_active_preset()
    key = preset.resolve_api_key()

    # ── Gradient ASCII art banner ──
    logo_lines = [
        '  ██╗███████╗██████╗  ██████╗ ██╗ ██████╗  ██╗',
        '  ██║██╔════╝██╔══██╗██╔════╝███║██╔═████╗███║',
        '  ██║███████╗██████╔╝██║     ╚██║██║██╔██║╚██║',
        '  ██║╚════██║██╔══██╗██║      ██║████╔╝██║ ██║',
        '  ██║███████║██║  ██║╚██████╗ ██║╚██████╔╝ ██║',
        '  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝ ╚═════╝  ╚═╝',
    ]
    max_len = max(len(line) for line in logo_lines)

    console.print()
    for line in logo_lines:
        text = Text()
        for col, ch in enumerate(line):
            t = col / max(max_len - 1, 1)
            r, g, b = _lerp_color(GRADIENT_STOPS, t)
            text.append(ch, style=RichStyle(color=Color.from_rgb(r, g, b), bold=True))
        console.print(text)

    # Subtitle under logo
    subtitle = Text()
    sub_str = "  AI Coding Assistant"
    for i, ch in enumerate(sub_str):
        t = i / max(len(sub_str) - 1, 1)
        r, g, b = _lerp_color(GRADIENT_STOPS, t)
        subtitle.append(ch, style=RichStyle(color=Color.from_rgb(r, g, b)))
    version = f"  v{config._version if hasattr(config, '_version') else '1.0.0'}"
    subtitle.append(version, style="#6E7681")
    console.print(subtitle)
    console.print()

    # ── Status info table ──
    key_status = "[#57DB9C]ready[/#57DB9C]" if key else "[#F85149]missing[/#F85149]"
    web_text = "[#57DB9C]ON[/#57DB9C]" if config.web_enabled else "[#6E7681]off[/#6E7681]"
    skills_list = config.enabled_skills
    skills_text = ", ".join(skills_list) if skills_list else "[#6E7681]none[/#6E7681]"
    mode_colors = {"agent": "#57DB9C", "ask": "#E3B341"}
    mode_color = mode_colors.get(config.chat_mode, "#8B949E")

    info = Table.grid(padding=(0, 2))
    info.add_column(style="#6E7681", min_width=9)
    info.add_column()

    info.add_row("model", f"[bold]{config.active_model}[/bold] [#6E7681]→[/#6E7681] {preset.model}")
    info.add_row("mode", f"[{mode_color}]{config.chat_mode}[/{mode_color}]")
    info.add_row("web", web_text)
    info.add_row("api key", key_status)
    info.add_row("context", f"{preset.context_window:,} tokens [#6E7681](max_out={preset.max_tokens:,})[/#6E7681]")
    if skills_list:
        info.add_row("skills", skills_text)
    if preset.api_base:
        info.add_row("api", f"[#6E7681]{preset.api_base}[/#6E7681]")
    info.add_row("project", f"{config.project_root}")

    console.print(
        Panel(
            info,
            border_style=THEME_ACCENT,
            padding=(0, 1),
        )
    )

    # ── Quick tips ──
    tips = Text.from_markup(
        f"[#6E7681]  Type a message to start  ·  "
        f"[{THEME_ACCENT}]/[/{THEME_ACCENT}] commands  ·  "
        f"[{THEME_ACCENT}]/help[/{THEME_ACCENT}] reference  ·  "
        f"[{THEME_ACCENT}]/mode ask[/{THEME_ACCENT}] for read-only  ·  "
        f"Esc+Enter multi-line  ·  "
        f"Ctrl-C cancel[/#6E7681]"
    )
    console.print(tips)
    console.print()


def _fuzzy_span_score(query: str, candidate: str) -> int | None:
    query_chars = query.lower().lstrip("/")
    candidate_chars = candidate.lower().lstrip("/")

    if not query_chars:
        return 0

    positions = []
    cursor = 0
    for char in query_chars:
        index = candidate_chars.find(char, cursor)
        if index < 0:
            return None
        positions.append(index)
        cursor = index + 1

    return positions[-1] - positions[0] + 1


def _command_sort_key(token: str, spec: SlashCommandSpec, order_map: dict[str, int]):
    lowered = token.lower().lstrip("/")
    command_only = spec.command.lower().lstrip("/")

    if not lowered:
        return (0, 0, order_map[spec.command])

    if command_only.startswith(lowered):
        return (0, 0, order_map[spec.command])

    contains_pos = command_only.find(lowered)
    if contains_pos >= 0:
        return (1, contains_pos, order_map[spec.command])

    fuzzy_span = _fuzzy_span_score(lowered, command_only)
    if fuzzy_span is not None:
        return (2, fuzzy_span, order_map[spec.command])

    haystack = " ".join((spec.description, *spec.keywords)).lower()
    keyword_pos = haystack.find(lowered)
    if keyword_pos >= 0:
        return (3, keyword_pos, order_map[spec.command])

    return None


class SlashCommandCompleter(Completer):
    """Full-width slash-command palette — spans the entire terminal."""

    def __init__(
        self,
        specs: Sequence[SlashCommandSpec] = SLASH_COMMAND_SPECS,
        max_items: int = 18,
    ):
        self.specs = list(specs)
        self.max_items = max_items
        self.order_map = {spec.command: index for index, spec in enumerate(self.specs)}
        self.usage_width = max(len(spec.usage) for spec in self.specs)

    def _display(self, spec: SlashCommandSpec):
        """Single row: command + wide gap + description. No right padding."""
        cmd_text = spec.usage
        # Wide gap between command and description for clear two-column feel
        gap = " " * max(4, self.usage_width - len(cmd_text) + 6)
        return [
            ("bold #E6EDF3", cmd_text),
            ("", gap),
            ("#6E7681", spec.description),
        ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        token = text.split(" ", 1)[0]
        if not token.startswith("/"):
            return

        ranked = []
        for spec in self.specs:
            key = _command_sort_key(token, spec, self.order_map)
            if key is not None:
                ranked.append((key, spec))

        ranked.sort(key=lambda item: item[0])
        replace_len = len(token)

        for _, spec in ranked[: self.max_items]:
            yield Completion(
                text=spec.command,
                start_position=-replace_len,
                display=self._display(spec),
                display_meta="",
            )


# ── Shared interactive pickers (Codex-style) ─────────────────

def _short(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _safe_api_host(api_base: str | None) -> str:
    if not api_base:
        return ""
    host = api_base.replace("https://", "").replace("http://", "")
    return _short(host.rstrip("/"), 28)


def select_model_interactive(config) -> str:
    """Codex-like minimal model picker with inline filtering."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout

    models = list(config.models.values())
    if not models:
        return ""

    active_index = 0
    for idx, model in enumerate(models):
        if model.name == config.active_model:
            active_index = idx
            break

    query = [""]
    visible = [list(range(len(models)))]
    cursor = [0]
    result = [""]

    def refresh_visible():
        lowered = query[0].strip().lower()
        if not lowered:
            visible[0] = list(range(len(models)))
        else:
            visible[0] = [
                idx
                for idx, model in enumerate(models)
                if lowered in model.name.lower()
                or lowered in (model.description or "").lower()
                or lowered in model.model.lower()
                or lowered in (model.provider or "").lower()
            ]

        if not visible[0]:
            cursor[0] = 0
            return

        try:
            active_pos = visible[0].index(active_index)
        except ValueError:
            active_pos = 0

        cursor[0] = min(max(cursor[0], 0), len(visible[0]) - 1)
        if not query[0]:
            cursor[0] = min(active_pos, len(visible[0]) - 1)

    def _current_model_index() -> int | None:
        if not visible[0]:
            return None
        return visible[0][cursor[0]]

    def get_text():
        lines = []
        lines.append((f"bold {THEME_ACCENT}", " model\n"))
        lines.append(("#66788A", " ↑↓/jk move • type filter • Enter select • Esc clear/cancel\n"))

        q = query[0].strip()
        query_text = q if q else "(all)"
        query_style = "#7AA7E8" if q else "#66788A"
        lines.append((query_style, f" filter: {query_text}\n"))
        lines.append(("", "\n"))

        if not visible[0]:
            lines.append(("#D08770", " no matching models\n"))
            lines.append(("#66788A", f"\n {len(visible[0])}/{len(models)} shown"))
            return lines

        name_width = max(12, min(18, max(len(models[idx].name) for idx in visible[0]) + 1))

        for pos, model_index in enumerate(visible[0]):
            model = models[model_index]
            is_current = pos == cursor[0]
            is_active = model.name == config.active_model

            pointer = "›" if is_current else " "
            active_mark = "●" if is_active else " "
            key_mark = "✓" if model.resolve_api_key() else "·"
            provider = _short(model.provider or "-", 9)
            desc = model.description.strip() if model.description else model.model
            desc = _short(desc, 30)
            api_host = _safe_api_host(model.api_base)

            if is_current:
                row_style = "bold #E7EEF8"
            elif is_active:
                row_style = "#57DB9C"
            else:
                row_style = "#C8D8EE"

            line = f" {pointer} {active_mark} {model.name:<{name_width}} {provider:<9} {desc:<30} {key_mark}"
            if api_host and "localhost" not in api_host:
                line += f"  @{api_host}"
            lines.append((row_style, line + "\n"))

        lines.append(("#66788A", f"\n {len(visible[0])}/{len(models)} shown • active=● • key=✓"))
        return lines

    refresh_visible()

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(_event):
        if visible[0]:
            cursor[0] = max(0, cursor[0] - 1)

    @kb.add("down")
    @kb.add("j")
    def _down(_event):
        if visible[0]:
            cursor[0] = min(len(visible[0]) - 1, cursor[0] + 1)

    @kb.add("backspace")
    def _backspace(_event):
        if query[0]:
            query[0] = query[0][:-1]
            refresh_visible()

    @kb.add("c-u")
    def _clear_query(_event):
        if query[0]:
            query[0] = ""
            refresh_visible()

    @kb.add("escape")
    def _escape(event):
        if query[0]:
            query[0] = ""
            refresh_visible()
            return
        result[0] = ""
        event.app.exit()

    @kb.add("c-c")
    def _cancel(event):
        result[0] = ""
        event.app.exit()

    @kb.add("enter")
    def _enter(event):
        model_index = _current_model_index()
        if model_index is None:
            return
        result[0] = models[model_index].name
        event.app.exit()

    @kb.add("<any>")
    def _type(event):
        data = event.key_sequence[0].data
        if not data or len(data) != 1:
            return
        if not data.isprintable() or data in ("\r", "\n", "\t", " "):
            return
        query[0] += data
        refresh_visible()

    control = FormattedTextControl(get_text)
    window = Window(content=control, always_hide_cursor=True)
    app = Application(layout=Layout(HSplit([window])), key_bindings=kb, full_screen=False)

    try:
        app.run()
    except (KeyboardInterrupt, EOFError):
        return ""

    return result[0]


def select_skills_interactive(config, available_skills: dict) -> list[str]:
    """Codex-like compact multi-select skill picker."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout

    names = sorted(available_skills.keys())
    if not names:
        return list(config.enabled_skills)

    enabled = set(config.enabled_skills)
    query = [""]
    visible = [list(range(len(names)))]
    cursor = [0]
    result = [None]

    def refresh_visible():
        lowered = query[0].strip().lower()
        if not lowered:
            visible[0] = list(range(len(names)))
        else:
            visible[0] = [
                idx
                for idx, name in enumerate(names)
                if lowered in name.lower()
                or lowered in available_skills[name].description.lower()
            ]

        if not visible[0]:
            cursor[0] = 0
            return
        cursor[0] = min(max(cursor[0], 0), len(visible[0]) - 1)

    def _current_name() -> str | None:
        if not visible[0]:
            return None
        return names[visible[0][cursor[0]]]

    def get_text():
        lines = []
        lines.append((f"bold {THEME_ACCENT}", " skills\n"))
        lines.append(("#66788A", " ↑↓/jk move • Space toggle • a all • c clear • Enter save • Esc clear/cancel\n"))

        q = query[0].strip()
        query_text = q if q else "(all)"
        query_style = "#7AA7E8" if q else "#66788A"
        lines.append((query_style, f" filter: {query_text}\n"))
        lines.append(("", "\n"))

        if not visible[0]:
            lines.append(("#D08770", " no matching skills\n"))
            lines.append(("#66788A", f"\n enabled {len(enabled)}/{len(names)}"))
            return lines

        name_width = max(16, min(24, max(len(names[idx]) for idx in visible[0]) + 1))

        for pos, name_index in enumerate(visible[0]):
            name = names[name_index]
            spec = available_skills[name]
            checked = name in enabled
            is_current = pos == cursor[0]

            pointer = "›" if is_current else " "
            marker = "✓" if checked else "·"
            desc = _short(spec.description.strip(), 54)

            if is_current:
                row_style = "bold #E7EEF8"
            elif checked:
                row_style = "#57DB9C"
            else:
                row_style = "#C8D8EE"

            line = f" {pointer} {marker} {name:<{name_width}} {desc}"
            lines.append((row_style, line + "\n"))

        lines.append(("#66788A", f"\n enabled {len(enabled)}/{len(names)} • checked=✓"))
        return lines

    refresh_visible()

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(_event):
        if visible[0]:
            cursor[0] = max(0, cursor[0] - 1)

    @kb.add("down")
    @kb.add("j")
    def _down(_event):
        if visible[0]:
            cursor[0] = min(len(visible[0]) - 1, cursor[0] + 1)

    @kb.add(" ")
    def _toggle(_event):
        name = _current_name()
        if not name:
            return
        if name in enabled:
            enabled.remove(name)
        else:
            enabled.add(name)

    @kb.add("a")
    def _all(_event):
        enabled.clear()
        enabled.update(names)

    @kb.add("c")
    def _clear(_event):
        enabled.clear()

    @kb.add("backspace")
    def _backspace(_event):
        if query[0]:
            query[0] = query[0][:-1]
            refresh_visible()

    @kb.add("c-u")
    def _clear_query(_event):
        if query[0]:
            query[0] = ""
            refresh_visible()

    @kb.add("escape")
    def _escape(event):
        if query[0]:
            query[0] = ""
            refresh_visible()
            return
        result[0] = None
        event.app.exit()

    @kb.add("c-c")
    def _cancel(event):
        result[0] = None
        event.app.exit()

    @kb.add("enter")
    def _save(event):
        result[0] = sorted(enabled)
        event.app.exit()

    @kb.add("<any>")
    def _type(event):
        data = event.key_sequence[0].data
        if not data or len(data) != 1:
            return
        if not data.isprintable() or data in ("\r", "\n", "\t", " "):
            return
        query[0] += data
        refresh_visible()

    control = FormattedTextControl(get_text)
    window = Window(content=control, always_hide_cursor=True)
    app = Application(layout=Layout(HSplit([window])), key_bindings=kb, full_screen=False)

    try:
        app.run()
    except (KeyboardInterrupt, EOFError):
        return list(config.enabled_skills)

    return result[0] if result[0] is not None else list(config.enabled_skills)
