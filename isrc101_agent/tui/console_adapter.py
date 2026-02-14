"""TUIConsole — Rich Console compatible adapter that routes output to Textual RichLog.

Performance-critical: streaming LLM output goes through _TUIStream at high
frequency.  Key optimisations over a naive implementation:

1. Non-blocking cross-thread posting via ``loop.call_soon_threadsafe`` instead
   of the blocking ``App.call_from_thread`` (which wraps asyncio Future.result).
2. Debounced ``scroll_end`` — at most one scroll per 30 ms regardless of how
   many lines arrive.
3. Fast-path ``print()`` that hands Rich renderables / markup strings directly
   to ``RichLog.write()`` without the Console→ANSI→Text.from_ansi roundtrip.
"""

from __future__ import annotations

import io
import threading
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.text import Text

if TYPE_CHECKING:
    from .app import ISRCApp

# ---------------------------------------------------------------------------
# Thread-safe helpers
# ---------------------------------------------------------------------------

def _post_to_app(app: "ISRCApp", callback, *args) -> None:
    """Schedule *callback* on the Textual event-loop thread **without blocking**.

    Falls back to a direct call when invoked from the main thread or when the
    loop is not yet available (e.g. during ``on_mount``).
    """
    try:
        if app._thread_id == threading.get_ident():
            callback(*args)
        else:
            app._loop.call_soon_threadsafe(callback, *args)
    except (RuntimeError, AttributeError):
        # Loop not running / app shutting down — best-effort direct call
        try:
            callback(*args)
        except Exception:
            pass


def _call_on_app_blocking(app: "ISRCApp", callback, *args):
    """Run *callback* on the Textual event-loop and **block** until it returns.

    Only used for operations that need a return value (e.g. ``input()``).
    """
    try:
        if app._thread_id == threading.get_ident():
            return callback(*args)
        return app.call_from_thread(callback, *args)
    except RuntimeError:
        try:
            return callback(*args)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# _TUIStream — streaming text for stream_renderer._write_raw()
# ---------------------------------------------------------------------------

class _TUIStream:
    """File-like object that routes write()/flush() to the Textual RichLog.

    ``stream_renderer._write_raw`` calls ``stream.write(chunk); stream.flush()``
    for every line.  Each pair must be cheap, so we use non-blocking posting and
    debounced scrolling.
    """

    _SCROLL_DEBOUNCE_S = 0.03          # ≈ 33 fps cap for auto-scroll

    def __init__(self, app: "ISRCApp"):
        self._app = app
        self._buffer = ""
        self._scroll_timer: threading.Timer | None = None
        self._scroll_lock = threading.Lock()

    # -- file-like interface -------------------------------------------------

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            _post_to_app(self._app, self._append_line, line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            text = self._buffer
            self._buffer = ""
            _post_to_app(self._app, self._append_line, text)
        self._request_scroll()

    @property
    def encoding(self):
        return "utf-8"

    # -- internal ------------------------------------------------------------

    def _append_line(self, line: str) -> None:
        """Runs on the Textual main thread."""
        try:
            self._app.query_one("#messages").write(line)
        except Exception:
            pass

    def _request_scroll(self) -> None:
        """Debounce scroll_end: at most once per ``_SCROLL_DEBOUNCE_S``."""
        with self._scroll_lock:
            if self._scroll_timer is not None:
                return                        # already scheduled
            self._scroll_timer = threading.Timer(
                self._SCROLL_DEBOUNCE_S, self._do_scroll,
            )
            self._scroll_timer.daemon = True
            self._scroll_timer.start()

    def _do_scroll(self) -> None:
        with self._scroll_lock:
            self._scroll_timer = None
        _post_to_app(self._app, self._scroll_widget)

    def _scroll_widget(self) -> None:
        try:
            self._app.query_one("#messages").scroll_end(animate=False)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# TUIConsole — drop-in for ``rich.Console``
# ---------------------------------------------------------------------------

class TUIConsole:
    """Rich-Console compatible adapter that routes output to Textual RichLog.

    Fast-paths avoid the expensive Console→ANSI→Text.from_ansi round-trip for
    the most common call patterns found in the codebase:

    * ``console.print()``                  → blank line
    * ``console.print(Panel(...))``        → direct renderable
    * ``console.print(text_obj)``          → direct Text
    * ``console.print("[markup]s[/]")``    → Text.from_markup
    * everything else                      → ANSI fallback
    """

    _is_tui = True

    def __init__(self, app: "ISRCApp"):
        self._app = app
        self._file = _TUIStream(app)
        # Lazy-init: only created when the ANSI fallback path is first needed
        self._inner: Console | None = None
        self._render_buf: io.StringIO | None = None

    @property
    def file(self):
        return self._file

    # ------------------------------------------------------------------ print

    def print(self, *objects: Any, **kwargs: Any) -> None:     # noqa: A003
        """Rich Console.print() compatible — routes to RichLog."""
        # Flush pending stream bytes so ordering is preserved
        self._file.flush()

        if not objects:
            _post_to_app(self._app, self._write_and_scroll, Text(""))
            return

        end = kwargs.get("end", "\n")
        markup = kwargs.get("markup", True)
        style = kwargs.get("style")
        highlight = kwargs.get("highlight")

        # --- Fast path: single Rich renderable (Panel, Table, Tree …) ------
        if (
            len(objects) == 1
            and not isinstance(objects[0], str)
            and end == "\n"
            and not style
        ):
            _post_to_app(self._app, self._write_and_scroll, objects[0])
            return

        # --- Fast path: single markup string, default kwargs ----------------
        if (
            len(objects) == 1
            and isinstance(objects[0], str)
            and markup
            and end == "\n"
            and not style
            and not highlight
        ):
            s: str = objects[0]
            if not s.strip():
                _post_to_app(self._app, self._write_and_scroll, Text(""))
                return
            try:
                text_obj = Text.from_markup(s)
                _post_to_app(self._app, self._write_and_scroll, text_obj)
                return
            except Exception:
                pass  # fall through to ANSI path

        # --- General ANSI fallback ------------------------------------------
        self._ensure_inner()
        self._render_buf.truncate(0)
        self._render_buf.seek(0)
        self._inner.print(*objects, **kwargs)
        rendered = self._render_buf.getvalue()
        self._render_buf.truncate(0)
        self._render_buf.seek(0)

        if not rendered or not rendered.strip():
            _post_to_app(self._app, self._write_and_scroll, Text(""))
            return

        text_obj = Text.from_ansi(rendered.rstrip("\n"))
        _post_to_app(self._app, self._write_and_scroll, text_obj)

    # ------------------------------------------------------------------ input

    def input(self, prompt: str = "") -> str:
        """Blocking input — used by ``confirm_tool()``."""
        result_event = threading.Event()
        result_holder: list[str] = [""]

        def _request():
            self._app._request_confirm(prompt, result_holder, result_event)

        _post_to_app(self._app, _request)
        result_event.wait()
        return result_holder[0]

    # ------------------------------------------------------------------ Live/Status stubs

    def set_live(self, live) -> None:
        """No-op: Rich Status/Live widgets call this. TUI ignores it."""
        pass

    def clear_live(self) -> None:
        """No-op: paired with set_live."""
        pass

    # ------------------------------------------------------------------ misc

    @property
    def width(self) -> int:
        if self._inner is not None:
            return self._inner.width
        return 120

    @width.setter
    def width(self, value: int):
        self._ensure_inner()
        self._inner.width = value

    # ------------------------------------------------------------------ priv

    def _ensure_inner(self) -> None:
        if self._inner is None:
            self._render_buf = io.StringIO()
            self._inner = Console(
                file=self._render_buf,
                force_terminal=True,
                width=120,
                color_system="truecolor",
            )

    def _write_and_scroll(self, content) -> None:
        """Runs on the Textual main thread: append to RichLog + scroll."""
        try:
            log = self._app.query_one("#messages")
            log.write(content)
            log.scroll_end(animate=False)
        except Exception:
            pass
