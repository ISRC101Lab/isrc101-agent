"""Terminal UI primitives and Codex-like styling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from prompt_toolkit.completion import Completion, Completer
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style

THEME_ACCENT = "#7FA6D9"
THEME_PROMPT = "#B7C6D8"

PTK_STYLE = Style.from_dict({
    "completion-menu": "bg:default",
    "completion-menu.completion": "bg:default #C8D8EE",
    "completion-menu.completion.current": "bg:#1E2834 #E7EEF8",
    "completion-menu.meta.completion": "bg:default #7AA7E8",
    "completion-menu.meta.completion.current": "bg:#1E2834 #7AA7E8",
    "completion-menu.multi-column-meta": "bg:default #7AA7E8",
    "completion-menu.multi-column-meta.current": "bg:#1E2834 #7AA7E8",
    "completion-menu.command": "#57DB9C",
    "completion-menu.args": "#9BB0C9",
    "completion-menu.description": "#7AA7E8",
    "scrollbar.background": "bg:default",
    "scrollbar.button": "bg:default",
})


@dataclass(frozen=True)
class SlashCommandSpec:
    command: str
    usage: str
    description: str
    keywords: tuple[str, ...] = ()


SLASH_COMMAND_SPECS: tuple[SlashCommandSpec, ...] = (
    SlashCommandSpec("/help", "/help", "Show help", ("docs", "usage", "commands")),
    SlashCommandSpec("/model", "/model", "Switch model", ("llm", "provider", "preset")),
    SlashCommandSpec("/mode", "/mode", "Switch mode", ("code", "ask", "architect")),
    SlashCommandSpec("/skills", "/skills", "Manage skills", ("workflow", "plugin", "ability")),
    SlashCommandSpec("/web", "/web", "Toggle web", ("fetch", "url", "docs")),
    SlashCommandSpec("/display", "/display", "Display/answer mode", ("thinking", "summary", "verbose", "concise")),
    SlashCommandSpec("/save", "/save [name]", "Save session", ("session", "history")),
    SlashCommandSpec("/load", "/load [name]", "Load session", ("session", "history")),
    SlashCommandSpec("/sessions", "/sessions", "List sessions", ("session", "history")),
    SlashCommandSpec("/compact", "/compact", "Compact context", ("context", "tokens")),
    SlashCommandSpec("/undo", "/undo", "Undo last change", ("revert", "rollback")),
    SlashCommandSpec("/diff", "/diff", "Show git diff", ("git", "changes", "patch")),
    SlashCommandSpec("/config", "/config", "Show config", ("settings", "model")),
    SlashCommandSpec("/stats", "/stats", "Session stats", ("tokens", "usage", "cost")),
    SlashCommandSpec("/git", "/git", "Git status", ("branch", "commit", "status")),
    SlashCommandSpec("/reset", "/reset", "Reset chat", ("clear", "conversation")),
    SlashCommandSpec("/quit", "/quit", "Quit", ("exit",)),
)

SLASH_COMMANDS = [spec.command for spec in SLASH_COMMAND_SPECS]
MAX_SLASH_MENU_ITEMS = 16


def build_banner(version: str) -> str:
    return (
        f"[bold {THEME_ACCENT}]isrc101-agent[/bold {THEME_ACCENT}] "
        f"[dim]v{version} · AI coding assistant[/dim]"
    )


def build_help_text() -> str:
    usage_width = max(len(spec.usage) for spec in SLASH_COMMAND_SPECS)
    lines = ["", f"[bold {THEME_ACCENT}]Commands:[/bold {THEME_ACCENT}]"]
    for spec in SLASH_COMMAND_SPECS:
        lines.append(f"  {spec.usage:<{usage_width}}  {spec.description}")

    lines.extend([
        "",
        f"[bold {THEME_ACCENT}]Tips:[/bold {THEME_ACCENT}]",
        "  Esc → Enter   Multi-line input (or paste multi-line text)",
        "  /              Show command menu (prefix + fuzzy)",
        "  Ctrl-D ×2      Exit safely",
    ])
    return "\n".join(lines)


HELP_TEXT = build_help_text()


def make_prompt_html() -> HTML:
    return HTML(
        f'<style fg="{THEME_PROMPT}">isrc101</style>'
        f'<style fg="#66788A"> › </style>'
    )


def render_startup(console, config) -> None:
    preset = config.get_active_preset()
    key = preset.resolve_api_key()

    key_status = "[green]✓[/green]" if key else "[red]✗[/red]"
    skills_text = ", ".join(config.enabled_skills) if config.enabled_skills else "(none)"
    web_text = "[green]ON[/green]" if config.web_enabled else "[dim]OFF[/dim]"

    console.print(
        f"[dim]model[/dim] [bold]{config.active_model}[/bold] [dim]→[/dim] {preset.model}"
        f" [dim]• mode[/dim] {config.chat_mode}"
        f" [dim]• web[/dim] {web_text}"
        f" [dim]• answer[/dim] {config.answer_style}"
        f" [dim]• key[/dim] {key_status}"
    )
    console.print(
        f"[dim]context[/dim] {preset.context_window:,} (max_tokens={preset.max_tokens:,})"
        f" [dim]• skills[/dim] {skills_text}"
    )
    console.print(f"[dim]project[/dim] {config.project_root}")
    if preset.api_base:
        console.print(f"[dim]api[/dim] {preset.api_base}")
    console.print(f"[dim]config[/dim] {config._config_source}")
    console.print("[dim]/help · /model · /skills · Ctrl+C to cancel[/dim]")
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
    """Codex-like compact slash-command palette with prefix+fuzzy matching."""

    def __init__(
        self,
        specs: Sequence[SlashCommandSpec] = SLASH_COMMAND_SPECS,
        max_items: int = MAX_SLASH_MENU_ITEMS,
    ):
        self.specs = list(specs)
        self.max_items = max_items
        self.order_map = {spec.command: index for index, spec in enumerate(self.specs)}
        self.usage_width = max(len(spec.usage) for spec in self.specs)

    def _usage_fragments(self, spec: SlashCommandSpec):
        if spec.usage == spec.command:
            return [("class:completion-menu.command", spec.command)]

        args = spec.usage[len(spec.command):]
        return [
            ("class:completion-menu.command", spec.command),
            ("class:completion-menu.args", args),
        ]

    def _display(self, spec: SlashCommandSpec):
        left = self._usage_fragments(spec)
        used_width = len(spec.usage)
        gap = " " * max(2, self.usage_width - used_width + 1)
        display = list(left)
        display.append(("", gap))
        display.append(("class:completion-menu.description", spec.description))
        return display

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
