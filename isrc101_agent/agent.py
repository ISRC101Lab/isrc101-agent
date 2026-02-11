"""Core agent loop with clear visual distinction between user and agent output."""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.status import Status

from .llm import LLMAdapter, LLMResponse, build_system_prompt
from .tools import ToolRegistry
from .logger import get_logger
from .context_window import ContextWindowManager
from .grounding import GroundingState
from .rendering import (
    render_error as _render_error_fn,
    render_tool_call as _render_tool_call_fn,
    render_result as _render_result_fn,
    render_write_diff as _render_write_diff_fn,
    render_assistant_message as _render_assistant_message_fn,
    inject_error_hint as _inject_error_hint_fn,
    confirm_tool as _confirm_tool_fn,
    handle_image_result as _handle_image_result_fn,
    AGENT_BORDER, AGENT_LABEL, TOOL_BORDER,
)
from .theme import (
    ACCENT as _T_ACCENT, BORDER as _T_BORDER, DIM as _T_DIM,
    TEXT as _T_TEXT, MUTED as _T_MUTED, SEPARATOR as _T_SEP,
    SUCCESS as _T_SUCCESS, WARN as _T_WARN, ERROR as _T_ERROR,
    INFO as _T_INFO,
)
from .stream_renderer import render_stream as _render_stream_fn
from .web_processing import (
    summarize_web_for_context as _summarize_web_for_context_fn,
    format_web_result_preview as _format_web_result_preview_fn,
)
from .url_utils import (
    SEARCH_URL_RE as _SEARCH_URL_RE,
    url_host,
    matches_official_domains,
    extract_search_links,
    normalize_text_for_match,
    render_sources_footer,
    render_grounding_refusal,
    render_grounding_partial,
)

_log = get_logger(__name__)
console = Console()

_PLAN_TITLE_RE = re.compile(r'##\s*Plan:\s*(.+)')
_PLAN_STEP_RE = re.compile(r'(\d+)\.\s*\[(\w+)\]\s*`([^`]+)`\s*[—\-]\s*(.+)')

__all__ = ["Agent", "Plan", "PlanStep"]

# ── Visual theme (imported from rendering.py) ──────


# ── Plan data structures ──────────────────────────
@dataclass
class PlanStep:
    index: int
    action: str       # "create", "edit", "delete", "run", "read"
    target: str       # file path or command
    description: str
    status: str = "pending"  # pending | executing | done | failed | skipped


@dataclass
class Plan:
    title: str
    steps: List[PlanStep] = field(default_factory=list)
    approved: bool = False


class Agent:
    GROUNDED_WEB_MODES = {"off", "strict"}
    GROUNDED_CITATION_MODES = {"sources_only", "inline"}
    GROUNDING_OPEN = "<grounding_json>"
    GROUNDING_CLOSE = "</grounding_json>"
    MAX_WEB_EVIDENCE_DOCS = 24
    SEARCH_URL_RE = _SEARCH_URL_RE

    def __init__(self, llm: LLMAdapter, tools: ToolRegistry, max_iterations: int = 30,
                 auto_confirm: bool = False, chat_mode: str = "agent",
                 auto_commit: bool = True,
                 skill_instructions: Optional[str] = None,
                 reasoning_display: str = "summary",
                 web_display: str = "summary",
                 answer_style: str = "concise",
                 grounded_web_mode: str = "strict",
                 grounded_retry: int = 1,
                 grounded_visible_citations: str = "sources_only",
                 grounded_context_chars: int = 8000,
                 grounded_search_max_seconds: int = 180,
                 grounded_search_max_rounds: int = 8,
                 grounded_search_per_round: int = 3,
                 grounded_official_domains: Optional[List[str]] = None,
                 grounded_fallback_to_open_web: bool = True,
                 grounded_partial_on_timeout: bool = True,
                 web_preview_lines: int = 3,
                 web_preview_chars: int = 360,
                 web_context_chars: int = 4000,
                 max_web_calls_per_turn: int = 12,
                 tool_parallelism: int = 4):
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        self.auto_confirm = auto_confirm
        self.auto_commit = auto_commit
        self.skill_instructions = skill_instructions
        self.reasoning_display = reasoning_display
        self.web_display = web_display
        self.answer_style = answer_style
        grounded_mode = str(grounded_web_mode or "strict").strip().lower()
        if grounded_mode not in self.GROUNDED_WEB_MODES:
            grounded_mode = "strict"
        citation_mode = str(grounded_visible_citations or "sources_only").strip().lower()
        if citation_mode not in self.GROUNDED_CITATION_MODES:
            citation_mode = "sources_only"
        domains = [
            str(item).strip().lower()
            for item in (grounded_official_domains or [])
            if str(item).strip()
        ]
        domains = list(dict.fromkeys(domains))
        self._grounding = GroundingState(
            web_mode=grounded_mode,
            retry=max(0, int(grounded_retry)),
            visible_citations=citation_mode,
            context_chars=max(800, int(grounded_context_chars)),
            search_max_seconds=max(20, int(grounded_search_max_seconds)),
            search_max_rounds=max(1, int(grounded_search_max_rounds)),
            search_per_round=max(1, int(grounded_search_per_round)),
            official_domains=domains,
            fallback_to_open_web=bool(grounded_fallback_to_open_web),
            partial_on_timeout=bool(grounded_partial_on_timeout),
        )
        self.web_preview_lines = max(1, int(web_preview_lines))
        self.web_preview_chars = max(80, int(web_preview_chars))
        self.web_context_chars = max(500, int(web_context_chars))
        self.max_web_calls_per_turn = max(1, int(max_web_calls_per_turn))
        self.tool_parallelism = max(1, int(tool_parallelism))
        self._ctx = ContextWindowManager(
            llm.model, llm.max_tokens,
            getattr(llm, 'context_window', 128000))
        normalized_mode = self._normalize_mode(chat_mode)
        self._mode = normalized_mode
        self.tools.mode = normalized_mode
        self.conversation: List[Dict[str, Any]] = []
        self.total_tokens = 0
        self._files_modified = False
        self.current_plan: Optional[Plan] = None
        self._web_fetch_cache: Dict[str, str] = {}  # URL → raw result (session-level)
        self._web_search_cache: Dict[str, str] = {}  # query → raw result (session-level)

    @property
    def mode(self):
        return self._mode

    @staticmethod
    def _normalize_mode(value: str) -> str:
        mode = str(value or "agent").strip().lower()
        if mode in ("code", "architect"):
            return "agent"
        if mode not in ("agent", "ask"):
            return "agent"
        return mode

    @mode.setter
    def mode(self, value):
        normalized = self._normalize_mode(value)
        self._mode = normalized
        self.tools.mode = normalized

    # ── Grounding forwarding properties (backward compat) ──────

    @property
    def _web_evidence_store(self) -> Dict[str, str]:
        return self._grounding.evidence_store

    @property
    def _web_evidence_normalized_store(self) -> Dict[str, str]:
        return self._grounding.evidence_normalized_store

    @property
    def _web_evidence_order(self) -> List[str]:
        return self._grounding.evidence_order

    @property
    def _turn_web_used(self) -> bool:
        return self._grounding.turn_web_used

    @_turn_web_used.setter
    def _turn_web_used(self, value: bool):
        self._grounding.turn_web_used = value

    @property
    def _turn_web_sources(self) -> set:
        return self._grounding.turn_web_sources

    @property
    def grounded_web_mode(self) -> str:
        return self._grounding.web_mode

    @property
    def grounded_retry(self) -> int:
        return self._grounding.retry

    @property
    def grounded_context_chars(self) -> int:
        return self._grounding.context_chars

    @property
    def grounded_search_max_seconds(self) -> int:
        return self._grounding.search_max_seconds

    @property
    def grounded_search_max_rounds(self) -> int:
        return self._grounding.search_max_rounds

    @property
    def grounded_search_per_round(self) -> int:
        return self._grounding.search_per_round

    @property
    def grounded_official_domains(self) -> List[str]:
        return self._grounding.official_domains

    @property
    def grounded_fallback_to_open_web(self) -> bool:
        return self._grounding.fallback_to_open_web

    @property
    def grounded_partial_on_timeout(self) -> bool:
        return self._grounding.partial_on_timeout

    @property
    def grounded_visible_citations(self) -> str:
        return self._grounding.visible_citations

    # ── Grounding thin wrappers ──────

    def _turn_source_urls(self) -> List[str]:
        return self._grounding.turn_source_urls()

    def _should_enforce_grounding(self) -> bool:
        return self._grounding.should_enforce()

    def _build_grounding_context_block(self) -> str:
        return self._grounding.build_context_block()

    def _compose_system_prompt(self, base_system: str, grounding_feedback: str = "") -> str:
        return self._grounding.compose_system_prompt(base_system, grounding_feedback)

    def _request_response(self, messages: list, stream: bool) -> LLMResponse:
        if stream:
            return self._stream_response(messages)
        try:
            return self.llm.chat(messages, tools=self.tools.schemas)
        except Exception as e:
            raise ConnectionError(f"Request error: {type(e).__name__}: {e}")

    def _render_assistant_message(self, content: str):
        _render_assistant_message_fn(console, content)

    def _parse_grounding_payload(self, content: str) -> Optional[dict]:
        return self._grounding.parse_payload(content)

    @staticmethod
    def _normalize_text_for_match(text: str) -> str:
        return normalize_text_for_match(text)

    @staticmethod
    def _extract_search_links(result: str) -> List[str]:
        return extract_search_links(result)

    @staticmethod
    def _url_host(url: str) -> str:
        return url_host(url)

    def _matches_official_domains(self, url: str) -> bool:
        return matches_official_domains(url, self.grounded_official_domains)

    def _safe_web_search(self, query: str, max_results: int, domains: Optional[List[str]] = None) -> str:
        args: Dict[str, Any] = {"query": query, "max_results": max(1, int(max_results))}
        filtered_domains = [d.strip() for d in (domains or []) if d and d.strip()]
        if filtered_domains:
            args["domains"] = filtered_domains
        try:
            return self.tools.execute("web_search", args)
        except Exception as e:
            return f"Web error: {type(e).__name__}: {e}"

    def _safe_web_fetch(self, url: str) -> str:
        try:
            return self.tools.execute("web_fetch", {"url": url})
        except Exception as e:
            return f"Web error: {type(e).__name__}: {e}"

    def _supplement_grounding_sources(self, user_message: str, error_hint: str) -> Tuple[int, bool]:
        if not self.tools.web_enabled:
            return 0, False
        return self._grounding.supplement_sources(
            user_message, error_hint,
            self._safe_web_search, self._safe_web_fetch,
        )

    def _quote_exists_in_source(self, quote: str, source_url: str, source_text: str) -> bool:
        return self._grounding.quote_exists_in_source(quote, source_url, source_text)

    def _render_sources_footer(self, sources: List[str]) -> str:
        return render_sources_footer(sources)

    def _render_grounding_refusal(self, reason: str) -> str:
        return render_grounding_refusal(reason, self._turn_source_urls())

    def _render_grounding_partial(self, reason: str) -> str:
        return render_grounding_partial(reason, self._turn_source_urls())

    def _finalize_assistant_content(self, raw_content: str) -> Tuple[str, Optional[str]]:
        return self._grounding.finalize_content(raw_content)

    def _extract_url_and_body(self, result: str) -> Tuple[str, str]:
        return self._grounding.extract_url_and_body(result)

    def _record_web_evidence(self, url: str, text: str):
        self._grounding.record_evidence(url, text)

    def _capture_web_fetch_evidence(self, result: str):
        self._grounding.capture_fetch_evidence(result)

    def _capture_web_search_evidence(self, result: str):
        self._grounding.capture_search_evidence(result)

    def chat(self, user_message: str) -> str:
        self.conversation.append({"role": "user", "content": user_message})
        self._files_modified = False
        self._grounding.reset_turn()
        grounding_feedback = ""
        grounding_retries_left = self.grounded_retry
        self._web_tool_calls_this_turn = 0
        self._max_web_tool_calls_per_turn = self.max_web_calls_per_turn

        base_system = build_system_prompt(
            self._mode,
            self.skill_instructions,
            self.answer_style,
        )

        for _ in range(self.max_iterations):
            system = self._compose_system_prompt(base_system, grounding_feedback)
            messages = self._prepare_messages(system)
            use_stream = not self._should_enforce_grounding()

            try:
                response = self._request_response(messages, stream=use_stream)
            except ConnectionError as e:
                _log.error("Connection error: %s", e)
                self._render_error(str(e))
                return str(e)

            if response.usage:
                self.total_tokens += response.usage.get("total_tokens", 0)

            if response.has_tool_calls():
                self._handle_tool_calls(response)
                grounding_feedback = ""
                grounding_retries_left = self.grounded_retry
                continue

            if response.content:
                finalized_content, retry_feedback = self._finalize_assistant_content(response.content)
                if retry_feedback:
                    if grounding_retries_left > 0:
                        grounding_retries_left -= 1
                        grounding_feedback = retry_feedback
                        console.print(f"  [{_T_WARN}]⚠ Grounding validation failed, retrying ({grounding_retries_left} left)…[/{_T_WARN}]")
                        continue
                    fetched_count, timed_out = self._supplement_grounding_sources(user_message, retry_feedback)
                    if fetched_count > 0:
                        grounding_feedback = retry_feedback
                        console.print(
                            f"  [{_T_INFO}]↻ Grounding supplement fetched {fetched_count} additional source(s); retrying…[/{_T_INFO}]"
                        )
                        continue
                    if timed_out and self.grounded_partial_on_timeout and self._turn_source_urls():
                        finalized_content = self._render_grounding_partial(retry_feedback)
                    else:
                        finalized_content = self._render_grounding_refusal(retry_feedback)

                assistant_msg = {"role": "assistant", "content": finalized_content}
                if response.reasoning_content is not None:
                    assistant_msg["reasoning_content"] = response.reasoning_content
                self.conversation.append(assistant_msg)
                if not use_stream:
                    self._render_assistant_message(finalized_content)

                if self._files_modified and self.auto_commit and self.tools.git.available:
                    commit_hash = self.tools.git.auto_commit()
                    if commit_hash:
                        console.print()
                        console.print(f"  [{_T_SUCCESS}]⎇[/{_T_SUCCESS}] [{_T_MUTED}]committed[/{_T_MUTED}] [bold {_T_TEXT}]{commit_hash}[/bold {_T_TEXT}]")
                    elif self.tools.git.has_changes():
                        console.print()
                        console.print("  [{warn}]⚠ auto-commit skipped[/{warn}] [{dim}](check git status)[/{dim}]".format(warn=_T_WARN, dim=_T_DIM))
                # Auto-parse structured plan output (available in all modes)
                plan = self._try_parse_plan(finalized_content)
                if plan:
                    self.current_plan = plan
                    console.print()
                    console.print(f"  [{_T_INFO}]▣[/{_T_INFO}] [{_T_MUTED}]Plan parsed:[/{_T_MUTED}] "
                                  f"[bold {_T_TEXT}]{len(plan.steps)} steps[/bold {_T_TEXT}] "
                                  f"[{_T_DIM}]— use[/{_T_DIM}] [bold {_T_INFO}]/plan execute[/bold {_T_INFO}] [{_T_DIM}]to run[/{_T_DIM}]")
                return finalized_content

            console.print(f"[{_T_DIM}]  (empty response, retrying...)[/{_T_DIM}]")

        msg = f"⚠ Reached max iterations ({self.max_iterations})."
        console.print(f"\n[{_T_WARN}]{msg}[/{_T_WARN}]")
        return msg

    # ── Context window management (delegated to ContextWindowManager) ──

    def _estimate_tokens(self, text: str) -> int:
        return self._ctx.estimate_tokens(text)

    def _estimate_message_tokens(self, msg: dict) -> int:
        return self._ctx.estimate_message_tokens(msg)

    def _assistant_tool_call_ids(self, msg: Dict[str, Any]) -> List[str]:
        return self._ctx.assistant_tool_call_ids(msg)

    def _is_safe_split_message(self, msg: Dict[str, Any]) -> bool:
        return self._ctx.is_safe_split_message(msg)

    def _repair_tool_pairs_in_suffix(self, start: int, available_tokens: Optional[int] = None) -> int:
        return self._ctx.repair_tool_pairs_in_suffix(self.conversation, start, available_tokens)

    MAX_TOOL_RESULT_CHARS = 12000  # ~4000 tokens

    def _truncate_tool_result(self, result: str) -> str:
        return self._ctx.truncate_tool_result(result)

    def _prepare_messages(self, system_prompt: str) -> list:
        return self._ctx.prepare_messages(self.conversation, system_prompt, console)

    # ── Streaming response ─────────────────────

    def _stream_response(self, messages: list) -> LLMResponse:
        """Stream LLM response (delegated to stream_renderer)."""
        return _render_stream_fn(
            console,
            self.llm.chat_stream(messages, tools=self.tools.schemas),
            reasoning_display=self.reasoning_display,
            llm_response_cls=LLMResponse,
        )

    def _execute_single_tool_call(self, tc):
        t0 = time.monotonic()
        result = self.tools.execute(tc.name, tc.arguments)
        elapsed = time.monotonic() - t0
        return result, elapsed

    def _can_batch_parallel(self, tool_calls: List[Any]) -> bool:
        if len(tool_calls) < 2:
            return False
        if self.mode not in ("agent", "ask"):
            return False
        for tc in tool_calls:
            if not self.tools.can_parallelize(tc.name):
                return False
            if ToolRegistry.needs_confirmation(tc.name):
                return False
        return True

    def _handle_parallel_tool_calls(self, tool_calls: List[Any]) -> Dict[str, tuple[str, float]]:
        max_workers = min(self.tool_parallelism, len(tool_calls))
        results: Dict[str, tuple[str, float]] = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tool") as pool:
            future_map = {
                pool.submit(self._execute_single_tool_call, tc): tc.id
                for tc in tool_calls
            }
            for future in as_completed(future_map):
                tool_id = future_map[future]
                try:
                    results[tool_id] = future.result()
                except Exception as e:
                    results[tool_id] = (f"Tool execution error: {type(e).__name__}: {e}", 0.0)
        return results

    def _handle_tool_calls(self, response: LLMResponse):
        tc_raw = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
            for tc in response.tool_calls
        ]
        assistant_msg = {
            "role": "assistant", "content": response.content, "tool_calls": tc_raw,
        }
        # DeepSeek Reasoner requires reasoning_content on ALL assistant messages
        if response.reasoning_content is not None:
            assistant_msg["reasoning_content"] = response.reasoning_content
        self.conversation.append(assistant_msg)

        parallel_results: Dict[str, tuple[str, float]] = {}
        if self._can_batch_parallel(response.tool_calls):
            parallel_results = self._handle_parallel_tool_calls(response.tool_calls)

        total_calls = len(response.tool_calls)
        batch_start = time.monotonic()

        for i, tc in enumerate(response.tool_calls, 1):
            if i > 1 and total_calls > 1:
                console.print(f"     [{_T_BORDER}]·[/{_T_BORDER}]")
            self._render_tool_call(tc.name, tc.arguments, index=i, total=total_calls)

            if not self.auto_confirm and ToolRegistry.needs_confirmation(tc.name):
                if not self._confirm(tc.name, tc.arguments):
                    self.conversation.append({"role": "tool", "tool_call_id": tc.id,
                                              "content": "⚠ User denied."})
                    console.print(f"  [{_T_WARN}]↳ skipped[/{_T_WARN}]")
                    continue

            # ── web tool call limit: prevent infinite web loops ──
            if tc.name in ("web_search", "web_fetch"):
                if self._web_tool_calls_this_turn >= self._max_web_tool_calls_per_turn:
                    limit_msg = (
                        f"⚠ Web tool call limit reached ({self._max_web_tool_calls_per_turn} calls this turn). "
                        "Please answer based on the information already gathered, or tell the user "
                        "you need more specific guidance."
                    )
                    self.conversation.append({"role": "tool", "tool_call_id": tc.id,
                                              "content": limit_msg})
                    console.print(f"  [{_T_WARN}]↳ web call limit reached[/{_T_WARN}]")
                    continue
                self._web_tool_calls_this_turn += 1

            # ── web_search dedup: return cached result if same query already searched ──
            if tc.name == "web_search":
                search_query = tc.arguments.get("query", "")
                cached_search = self._web_search_cache.get(search_query)
                if cached_search is not None:
                    result, elapsed = cached_search, 0.0
                    self._render_result(tc.name, result, elapsed)
                    note = "\n\n(Note: this query was already searched earlier — returning cached results.)"
                    self.conversation.append({"role": "tool", "tool_call_id": tc.id,
                                              "content": result + note})
                    continue

            # ── web_fetch dedup: return cached result if URL already fetched ──
            if tc.name == "web_fetch":
                fetch_url = tc.arguments.get("url", "")
                cached = self._web_fetch_cache.get(fetch_url)
                if cached is not None:
                    result, elapsed = cached, 0.0
                    self._render_result(tc.name, result, elapsed)
                    stored_result = self._summarize_web_for_context(result)
                    note = "\n\n(Note: this URL was already fetched earlier — returning cached content.)"
                    self.conversation.append({"role": "tool", "tool_call_id": tc.id,
                                              "content": stored_result + note})
                    continue

            if tc.id in parallel_results:
                result, elapsed = parallel_results[tc.id]
            else:
                with Status(f"  [{_T_DIM}]  running…[/{_T_DIM}]",
                            console=console, spinner="dots", spinner_style=_T_ACCENT):
                    result, elapsed = self._execute_single_tool_call(tc)
            self._render_result(tc.name, result, elapsed)

            # Handle image results specially for multimodal
            if tc.name == "read_image" and result.startswith("[IMAGE:"):
                self._handle_image_result(tc, result)
                continue

            if tc.name == "web_fetch":
                fetch_url = tc.arguments.get("url", "")
                if not result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
                    self._web_fetch_cache[fetch_url] = result
                self._capture_web_fetch_evidence(result)
                stored_result = self._summarize_web_for_context(result)
                self.conversation.append({"role": "tool", "tool_call_id": tc.id, "content": stored_result})
                continue

            if tc.name == "web_search":
                search_query = tc.arguments.get("query", "")
                if not result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
                    self._web_search_cache[search_query] = result
                self._capture_web_search_evidence(result)

            if tc.name in ToolRegistry.WRITE_TOOLS:
                self._files_modified = True
                self._render_write_diff(tc.name, tc.arguments)
            # Truncate large tool results in conversation to preserve context window
            stored_result = self._truncate_tool_result(result)
            stored_result = self._inject_error_hint(tc.name, tc.arguments, stored_result)
            self.conversation.append({"role": "tool", "tool_call_id": tc.id, "content": stored_result})

        if total_calls > 1:
            batch_elapsed = time.monotonic() - batch_start
            console.print(f"\n  [{_T_SEP}]─ {total_calls} tools · {batch_elapsed:.1f}s ─[/{_T_SEP}]")

    def _summarize_web_for_context(self, result: str) -> str:
        return _summarize_web_for_context_fn(
            result, self.web_display, self.web_context_chars,
            self.web_preview_lines, self._truncate_tool_result)

    def _format_web_result_preview(self, result: str) -> str:
        return _format_web_result_preview_fn(
            result, self.web_display,
            self.web_preview_lines, self.web_preview_chars)

    def _confirm(self, tool_name: str, arguments: dict) -> bool:
        result = _confirm_tool_fn(console, tool_name, arguments, self.tools.files)
        if result == "always":
            self.auto_confirm = True
            return True
        return result == "yes"

    def _build_diff_panel(self, diff: str) -> Panel:
        from .rendering import build_diff_panel
        return build_diff_panel(diff)

    def _show_edit_preview(self, tool_name: str, arguments: dict):
        from .rendering import show_edit_preview
        show_edit_preview(console, tool_name, arguments, self.tools.files)

    def _show_write_preview(self, arguments: dict):
        from .rendering import show_write_preview
        show_write_preview(console, arguments, self.tools.files)

    def _handle_image_result(self, tc, result: str):
        _handle_image_result_fn(self.conversation, tc, self.tools.files)

    # ── Rendering (delegated to rendering.py) ──────

    def _render_error(self, message: str):
        _render_error_fn(console, message)

    def _render_tool_call(self, name, args, index=None, total=None):
        _render_tool_call_fn(console, name, args, index, total)

    def _render_result(self, name, result, elapsed: float = 0):
        _render_result_fn(console, name, result, elapsed,
                          self.web_display, self._format_web_result_preview)

    def _render_write_diff(self, tool_name: str, arguments: dict):
        _render_write_diff_fn(console, tool_name, arguments)

    def _inject_error_hint(self, tool_name: str, arguments: dict, result: str) -> str:
        return _inject_error_hint_fn(tool_name, arguments, result)

    def _try_parse_plan(self, content: str) -> Optional[Plan]:
        """Try to parse a structured plan from LLM response."""
        title_match = _PLAN_TITLE_RE.search(content)
        if not title_match:
            return None

        title = title_match.group(1).strip()
        steps = []
        for m in _PLAN_STEP_RE.finditer(content):
            steps.append(PlanStep(
                index=int(m.group(1)),
                action=m.group(2),
                target=m.group(3),
                description=m.group(4).strip(),
            ))

        if not steps:
            return None
        return Plan(title=title, steps=steps)

    def get_stats(self) -> Dict:
        user_msgs = sum(1 for m in self.conversation if m.get("role") == "user")
        tool_calls = sum(len(m.get("tool_calls", []))
                         for m in self.conversation if m.get("role") == "assistant" and m.get("tool_calls"))

        # Context window usage
        context_window = getattr(self.llm, "context_window", 128000)
        conv_tokens = sum(self._estimate_message_tokens(m) for m in self.conversation)
        budget = context_window - self.llm.max_tokens - 1000
        pct = int(conv_tokens / budget * 100) if budget > 0 else 0

        return {
            "messages": len(self.conversation),
            "user_messages": user_msgs,
            "tool_calls": tool_calls,
            "total_tokens": self.total_tokens,
            "context_used": f"~{conv_tokens:,} / {budget:,} ({pct}%)",
            "context_window": f"{context_window:,}",
            "thinking_display": self.reasoning_display,
            "web_display": self.web_display,
            "answer_style": self.answer_style,
        }

    def compact_conversation(self) -> int:
        """Compact old messages into a summary, keeping a safe recent suffix."""
        keep_last = 4
        if len(self.conversation) <= keep_last:
            return 0

        split_index = len(self.conversation) - keep_last
        split_index = self._repair_tool_pairs_in_suffix(split_index)

        # Safe split starts at user, or assistant without tool calls.
        while split_index > 0 and not self._is_safe_split_message(self.conversation[split_index]):
            split_index -= 1

        if split_index <= 0:
            return 0

        old_msgs = self.conversation[:split_index]
        kept = self.conversation[split_index:]

        summary_parts = []
        for msg in old_msgs:
            role = msg.get("role", "?")
            content = (msg.get("content") or "")[:200]
            if role == "user":
                summary_parts.append(f"User: {content}")
            elif role == "assistant":
                tc = msg.get("tool_calls")
                if tc:
                    names = [t["function"]["name"] for t in tc] if isinstance(tc, list) else []
                    summary_parts.append(f"Assistant: called {', '.join(names)}")
                elif content:
                    summary_parts.append(f"Assistant: {content}")
            elif role == "tool":
                summary_parts.append(f"Tool result: {content[:100]}")

        summary_text = (
            "[Conversation summary — earlier messages compacted]\n"
            + "\n".join(summary_parts)
        )
        compacted_count = len(old_msgs)

        self.conversation = [
            {"role": "user", "content": summary_text},
            {"role": "assistant", "content": "Understood. I have the context from our earlier conversation. How can I continue helping?"},
        ] + kept

        self._ctx.invalidate_token_cache()
        return compacted_count

    def reset(self):
        self.conversation.clear()
        self.total_tokens = 0
        self._grounding.reset_turn()
        self._web_fetch_cache.clear()
