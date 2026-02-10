"""Core agent loop with clear visual distinction between user and agent output."""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.status import Status

from .llm import LLMAdapter, LLMResponse, build_system_prompt
from .tools import ToolRegistry
from .logger import get_logger
from .tokenizer import estimate_tokens, estimate_message_tokens

_log = get_logger(__name__)
console = Console()

__all__ = ["Agent", "Plan", "PlanStep"]

# ── Visual theme ───────────────────────────────────
AGENT_BORDER = "cyan"
AGENT_LABEL = "[bold cyan]isrc101[/bold cyan]"
TOOL_BORDER = "dim"


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

    STREAM_PROFILES = {
        "stable": {
            "interval": 0.08,
            "min_chars": 20,
            "priority_interval": 0.025,
            "priority_chars": 6,
            "max_silent_ms": 300,
        },
        "smooth": {
            "interval": 0.06,
            "min_chars": 12,
            "priority_interval": 0.015,
            "priority_chars": 3,
            "max_silent_ms": 250,
        },
        "ultra": {
            "interval": 0.04,
            "min_chars": 4,
            "priority_interval": 0.008,
            "priority_chars": 1,
            "max_silent_ms": 200,
        },
    }

    def __init__(self, llm: LLMAdapter, tools: ToolRegistry, max_iterations: int = 30,
                 auto_confirm: bool = False, chat_mode: str = "agent",
                 auto_commit: bool = True,
                 skill_instructions: Optional[str] = None,
                 reasoning_display: str = "summary",
                 web_display: str = "summary",
                 answer_style: str = "concise",
                 stream_profile: str = "ultra",
                 grounded_web_mode: str = "strict",
                 grounded_retry: int = 1,
                 grounded_visible_citations: str = "sources_only",
                 grounded_context_chars: int = 8000,
                 web_preview_lines: int = 3,
                 web_preview_chars: int = 360,
                 web_context_chars: int = 4000,
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
        self._stream_profile = "ultra"
        self.stream_profile = stream_profile
        grounded_mode = str(grounded_web_mode or "strict").strip().lower()
        if grounded_mode not in self.GROUNDED_WEB_MODES:
            grounded_mode = "strict"
        self.grounded_web_mode = grounded_mode
        self.grounded_retry = max(0, int(grounded_retry))
        citation_mode = str(grounded_visible_citations or "sources_only").strip().lower()
        if citation_mode not in self.GROUNDED_CITATION_MODES:
            citation_mode = "sources_only"
        self.grounded_visible_citations = citation_mode
        self.grounded_context_chars = max(800, int(grounded_context_chars))
        self.web_preview_lines = max(1, int(web_preview_lines))
        self.web_preview_chars = max(80, int(web_preview_chars))
        self.web_context_chars = max(500, int(web_context_chars))
        self.tool_parallelism = max(1, int(tool_parallelism))
        normalized_mode = self._normalize_mode(chat_mode)
        self._mode = normalized_mode
        self.tools.mode = normalized_mode
        self.conversation: List[Dict[str, Any]] = []
        self.total_tokens = 0
        self._files_modified = False
        self.current_plan: Optional[Plan] = None
        self._web_evidence_store: Dict[str, str] = {}
        self._web_evidence_order: List[str] = []
        self._turn_web_used = False
        self._turn_web_sources: set[str] = set()

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

    @property
    def stream_profile(self) -> str:
        return self._stream_profile

    @stream_profile.setter
    def stream_profile(self, value: str):
        profile = str(value or "ultra").strip().lower()
        if profile not in self.STREAM_PROFILES:
            profile = "ultra"
        self._stream_profile = profile

    def _stream_profile_setting(self, key: str):
        return self.STREAM_PROFILES[self._stream_profile][key]

    def _turn_source_urls(self) -> List[str]:
        return [url for url in self._web_evidence_order if url in self._turn_web_sources]

    def _should_enforce_grounding(self) -> bool:
        return (
            self.grounded_web_mode == "strict"
            and self._turn_web_used
            and bool(self._turn_web_sources)
        )

    def _build_grounding_context_block(self) -> str:
        sources = self._turn_source_urls()
        if not sources:
            return ""

        remaining = self.grounded_context_chars
        blocks: List[str] = []
        for url in sources:
            if remaining <= 0:
                break
            raw = (self._web_evidence_store.get(url) or "").strip()
            if not raw:
                continue
            take = min(len(raw), remaining)
            excerpt = raw[:take].strip()
            if not excerpt:
                continue
            blocks.append(f"[SOURCE] {url}\n{excerpt}\n[/SOURCE]")
            remaining -= len(excerpt)
        return "\n\n".join(blocks)

    def _compose_system_prompt(self, base_system: str, grounding_feedback: str = "") -> str:
        if not self._should_enforce_grounding():
            return base_system

        sources = self._turn_source_urls()
        evidence_block = self._build_grounding_context_block()
        if not sources or not evidence_block:
            return base_system

        source_lines = "\n".join(f"- {url}" for url in sources)
        protocol = (
            "\n\n## Strict web-grounding protocol (mandatory for this turn)\n"
            "- You MUST answer using only the provided SOURCE blocks and this turn's web tool outputs.\n"
            "- Do not use training memory or unstated assumptions.\n"
            "- Return EXACTLY one JSON object wrapped by tags below, and no other text:\n"
            f"  {self.GROUNDING_OPEN}\n"
            "  {\"answer\":\"...\",\"claims\":[{\"text\":\"...\",\"source_url\":\"...\",\"evidence_quote\":\"...\"}],\"sources\":[\"...\"]}\n"
            f"  {self.GROUNDING_CLOSE}\n"
            "- If evidence is insufficient, return:\n"
            f"  {self.GROUNDING_OPEN}\n"
            "  {\"insufficient_evidence\":true,\"reason\":\"...\",\"sources\":[\"...\"]}\n"
            f"  {self.GROUNDING_CLOSE}\n"
            "- Every claim must include source_url from allowed list and an exact evidence_quote substring from that source.\n"
            "- Allowed source URLs for this turn:\n"
            f"{source_lines}\n"
            "- Evidence documents:\n"
            f"{evidence_block}"
        )

        if grounding_feedback:
            protocol += (
                "\n\n## Grounding validation feedback from previous attempt\n"
                f"- {grounding_feedback}\n"
                "- Fix the issue and regenerate the tagged JSON payload only."
            )

        return base_system + protocol

    def _request_response(self, messages: list, stream: bool) -> LLMResponse:
        if stream:
            return self._stream_response(messages)
        try:
            return self.llm.chat(messages, tools=self.tools.schemas)
        except Exception as e:
            raise ConnectionError(f"Request error: {type(e).__name__}: {e}")

    def _render_assistant_message(self, content: str):
        console.print()
        if content.strip():
            console.print(Markdown(content))
        else:
            console.print(content)

    def _parse_grounding_payload(self, content: str) -> Optional[dict]:
        pattern = (
            re.escape(self.GROUNDING_OPEN)
            + r"\s*(\{.*?\})\s*"
            + re.escape(self.GROUNDING_CLOSE)
        )
        m = re.search(pattern, content, flags=re.DOTALL)
        raw_json = m.group(1) if m else content.strip()
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _normalize_text_for_match(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip().lower()

    def _quote_exists_in_source(self, quote: str, source_text: str) -> bool:
        q = self._normalize_text_for_match(quote)
        s = self._normalize_text_for_match(source_text)
        if not q or not s:
            return False
        return q in s

    def _render_sources_footer(self, sources: List[str]) -> str:
        if not sources:
            return ""
        lines = "\n".join(f"- {url}" for url in sources)
        return f"\n\nSources:\n{lines}"

    def _render_grounding_refusal(self, reason: str) -> str:
        msg = "I cannot verify a reliable answer from the fetched sources in this turn."
        detail = f"\n\nReason: {reason}" if reason else ""
        hint = "\n\nPlease provide a more specific official URL or ask me to fetch additional sources."
        footer = self._render_sources_footer(self._turn_source_urls())
        return msg + detail + hint + footer

    def _finalize_assistant_content(self, raw_content: str) -> Tuple[str, Optional[str]]:
        if not self._should_enforce_grounding():
            return raw_content, None

        payload = self._parse_grounding_payload(raw_content)
        if payload is None:
            return "", "Missing or invalid grounded JSON payload."

        if payload.get("insufficient_evidence"):
            reason = str(payload.get("reason", "")).strip()
            return self._render_grounding_refusal(reason), None

        answer = str(payload.get("answer", "")).strip()
        if not answer:
            return "", "Grounded payload must include a non-empty answer field."

        claims = payload.get("claims")
        if not isinstance(claims, list) or not claims:
            return "", "Grounded payload must include at least one claim with evidence."

        errors: List[str] = []
        valid_claim_sources: List[str] = []
        for index, claim in enumerate(claims, 1):
            if not isinstance(claim, dict):
                errors.append(f"Claim #{index} is not an object.")
                continue
            claim_text = str(claim.get("text", "")).strip()
            source_url = str(claim.get("source_url", "")).strip()
            evidence_quote = str(claim.get("evidence_quote", "")).strip()
            if not claim_text:
                errors.append(f"Claim #{index} is missing text.")
            if not source_url:
                errors.append(f"Claim #{index} is missing source_url.")
                continue
            if source_url not in self._turn_web_sources:
                errors.append(f"Claim #{index} uses non-turn source URL: {source_url}")
                continue
            source_doc = self._web_evidence_store.get(source_url, "")
            if not source_doc:
                errors.append(f"Claim #{index} source text is unavailable: {source_url}")
                continue
            if len(evidence_quote) < 8:
                errors.append(f"Claim #{index} evidence_quote is too short.")
                continue
            if not self._quote_exists_in_source(evidence_quote, source_doc):
                errors.append(f"Claim #{index} evidence_quote not found in source: {source_url}")
                continue
            valid_claim_sources.append(source_url)

        if errors:
            return "", "; ".join(errors)

        sources: List[str] = []
        declared = payload.get("sources")
        if isinstance(declared, list):
            for item in declared:
                url = str(item).strip()
                if url in self._turn_web_sources and url not in sources:
                    sources.append(url)
        for url in valid_claim_sources:
            if url not in sources:
                sources.append(url)

        if not sources:
            sources = self._turn_source_urls()

        rendered = answer
        if self.grounded_visible_citations in ("sources_only", "inline"):
            rendered += self._render_sources_footer(sources)
        return rendered, None

    def _extract_url_and_body(self, result: str) -> Tuple[str, str]:
        text = result.strip()
        if not text:
            return "", ""
        lines = text.splitlines()
        if not lines:
            return "", ""
        first = lines[0].strip()
        if first.lower().startswith("url:"):
            url = first[4:].strip()
            body = "\n".join(lines[1:]).strip()
            return url, body
        return "", text

    def _record_web_evidence(self, url: str, text: str):
        clean_url = (url or "").strip()
        if not clean_url.lower().startswith(("http://", "https://")):
            return
        clean_text = (text or "").strip()
        if not clean_text:
            return

        if len(clean_text) > self.grounded_context_chars:
            clean_text = clean_text[:self.grounded_context_chars] + "\n... (truncated)"

        self._web_evidence_store[clean_url] = clean_text
        if clean_url in self._web_evidence_order:
            self._web_evidence_order.remove(clean_url)
        self._web_evidence_order.append(clean_url)

        while len(self._web_evidence_order) > self.MAX_WEB_EVIDENCE_DOCS:
            oldest = self._web_evidence_order.pop(0)
            self._web_evidence_store.pop(oldest, None)

        self._turn_web_used = True
        self._turn_web_sources.add(clean_url)

    def _capture_web_fetch_evidence(self, result: str):
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return
        url, body = self._extract_url_and_body(result)
        if not url:
            return
        self._record_web_evidence(url, body)

    def _capture_web_search_evidence(self, result: str):
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return

        links = re.findall(r"\[[^\]]+\]\((https?://[^)\s]+)\)", result)
        if not links:
            return

        lines = result.splitlines()
        snippets: Dict[str, List[str]] = {}
        current_url = ""
        for raw in lines:
            line = raw.rstrip()
            m = re.search(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", line)
            if m:
                title = m.group(1).strip()
                current_url = m.group(2).strip()
                snippets.setdefault(current_url, [])
                if title:
                    snippets[current_url].append(title)
                continue

            if not current_url:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("Search:") or stripped.startswith("**Summary:**"):
                continue
            snippets[current_url].append(stripped)
            if len(" ".join(snippets[current_url])) >= 500:
                current_url = ""

        for url in links:
            snippet_text = "\n".join(snippets.get(url, []))
            if not snippet_text:
                snippet_text = "Search result source (no snippet provided)."
            self._record_web_evidence(url, snippet_text)

    def chat(self, user_message: str) -> str:
        self.conversation.append({"role": "user", "content": user_message})
        self._files_modified = False
        self._turn_web_used = False
        self._turn_web_sources.clear()
        grounding_feedback = ""
        grounding_retries_left = self.grounded_retry

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
                        console.print(f"  [#E3B341]⚠ Grounding validation failed, retrying ({grounding_retries_left} left)…[/#E3B341]")
                        continue
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
                        console.print(f"  [#57DB9C]⎇[/#57DB9C] [#8B949E]committed[/#8B949E] [bold #E6EDF3]{commit_hash}[/bold #E6EDF3]")
                    elif self.tools.git.has_changes():
                        console.print()
                        console.print("  [#E3B341]⚠ auto-commit skipped[/#E3B341] [#6E7681](check git status)[/#6E7681]")
                # Auto-parse structured plan output (available in all modes)
                plan = self._try_parse_plan(finalized_content)
                if plan:
                    self.current_plan = plan
                    console.print()
                    console.print(f"  [#58A6FF]▣[/#58A6FF] [#8B949E]Plan parsed:[/#8B949E] "
                                  f"[bold #E6EDF3]{len(plan.steps)} steps[/bold #E6EDF3] "
                                  f"[#6E7681]— use[/#6E7681] [bold #58A6FF]/plan execute[/bold #58A6FF] [#6E7681]to run[/#6E7681]")
                return finalized_content

            console.print("[#6E7681]  (empty response, retrying...)[/#6E7681]")

        msg = f"⚠ Reached max iterations ({self.max_iterations})."
        console.print(f"\n[#E3B341]{msg}[/#E3B341]")
        return msg

    # ── Context window management ──────────────

    def _estimate_tokens(self, text: str) -> int:
        """Token estimate using tiktoken when available."""
        return estimate_tokens(text, self.llm.model)

    def _estimate_message_tokens(self, msg: dict) -> int:
        """Estimate tokens for a conversation message."""
        return estimate_message_tokens(msg, self.llm.model)

    def _assistant_tool_call_ids(self, msg: Dict[str, Any]) -> List[str]:
        """Return tool_call ids from an assistant message."""
        if msg.get("role") != "assistant":
            return []
        tool_calls = msg.get("tool_calls")
        if not isinstance(tool_calls, list):
            return []

        call_ids: List[str] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                call_id = tc.get("id")
                if call_id:
                    call_ids.append(call_id)
        return call_ids

    def _find_parent_assistant_index(self, tool_call_id: str, before_index: int) -> Optional[int]:
        """Find the assistant message index that created a given tool_call id."""
        if not tool_call_id:
            return None

        for idx in range(before_index, -1, -1):
            if tool_call_id in self._assistant_tool_call_ids(self.conversation[idx]):
                return idx
        return None

    def _sum_message_tokens(self, start: int, end: int) -> int:
        """Token estimate for self.conversation[start:end]."""
        if start >= end:
            return 0
        return sum(self._estimate_message_tokens(msg) for msg in self.conversation[start:end])

    def _is_safe_split_message(self, msg: Dict[str, Any]) -> bool:
        """Safe split starts at user message or assistant message without tool calls."""
        role = msg.get("role")
        if role == "user":
            return True
        if role == "assistant" and not msg.get("tool_calls"):
            return True
        return False

    def _repair_tool_pairs_in_suffix(self, start: int, available_tokens: Optional[int] = None) -> int:
        """Adjust suffix start so tool_call/tool_result pairs stay valid."""
        total = len(self.conversation)
        start = max(0, min(start, total))

        while start < total:
            assistant_by_call_id: Dict[str, int] = {}
            assistant_calls_by_index: Dict[int, List[str]] = {}
            for idx in range(start, total):
                call_ids = self._assistant_tool_call_ids(self.conversation[idx])
                if not call_ids:
                    continue
                assistant_calls_by_index[idx] = call_ids
                for call_id in call_ids:
                    assistant_by_call_id[call_id] = idx

            result_indexes_by_call_id: Dict[str, List[int]] = {}
            orphan_tool_index: Optional[int] = None
            orphan_parent_index: Optional[int] = None
            for idx in range(start, total):
                msg = self.conversation[idx]
                if msg.get("role") != "tool":
                    continue

                tool_call_id = msg.get("tool_call_id")
                if not tool_call_id:
                    orphan_tool_index = idx
                    break

                if tool_call_id not in assistant_by_call_id:
                    orphan_tool_index = idx
                    orphan_parent_index = self._find_parent_assistant_index(tool_call_id, idx - 1)
                    break

                result_indexes_by_call_id.setdefault(tool_call_id, []).append(idx)

            if orphan_tool_index is not None:
                # Prefer pulling in the parent assistant message when budget allows.
                if orphan_parent_index is not None and orphan_parent_index < start:
                    if available_tokens is None:
                        start = orphan_parent_index
                        continue

                    current_tokens = self._sum_message_tokens(start, total)
                    extra_tokens = self._sum_message_tokens(orphan_parent_index, start)
                    if current_tokens + extra_tokens <= available_tokens:
                        start = orphan_parent_index
                        continue

                # If we cannot include the parent, drop the orphaned tool message(s).
                start = orphan_tool_index + 1
                continue

            missing_drop_index: Optional[int] = None
            for assistant_index, call_ids in assistant_calls_by_index.items():
                missing = [call_id for call_id in call_ids if call_id not in result_indexes_by_call_id]
                if not missing:
                    continue

                # Keep pairs consistent by removing this incomplete assistant turn.
                related_result_indexes = [
                    result_index
                    for call_id in call_ids
                    for result_index in result_indexes_by_call_id.get(call_id, [])
                ]
                drop_until = max(related_result_indexes) + 1 if related_result_indexes else assistant_index + 1
                missing_drop_index = drop_until
                break

            if missing_drop_index is not None:
                start = missing_drop_index
                continue

            break

        return start

    MAX_TOOL_RESULT_CHARS = 12000  # ~4000 tokens

    def _truncate_tool_result(self, result: str) -> str:
        """Truncate large tool results to prevent context window bloat."""
        if len(result) <= self.MAX_TOOL_RESULT_CHARS:
            return result
        half = self.MAX_TOOL_RESULT_CHARS // 2
        lines_total = result.count("\n") + 1
        return (result[:half]
                + f"\n\n... [truncated: {lines_total} lines, {len(result):,} chars → keeping first/last portions] ...\n\n"
                + result[-half:])

    def _prepare_messages(self, system_prompt: str) -> list:
        """Build messages list, truncating old messages to fit context window."""
        system_msg = {"role": "system", "content": system_prompt}

        context_window = getattr(self.llm, "context_window", 128000)
        max_tokens = self.llm.max_tokens
        budget = context_window - max_tokens - 1000  # reserve for overhead

        system_tokens = self._estimate_tokens(system_prompt) + 4
        available = budget - system_tokens

        # Walk backwards to keep the most recent messages that fit
        kept: List[Dict[str, Any]] = []
        used = 0
        start_index = len(self.conversation)
        for msg in reversed(self.conversation):
            msg_tokens = self._estimate_message_tokens(msg)
            if used + msg_tokens > available:
                break
            kept.insert(0, msg)
            used += msg_tokens
            start_index -= 1

        # Always keep at least one recent message.
        if not kept and self.conversation:
            kept = [self.conversation[-1]]
            start_index = len(self.conversation) - 1

        if kept:
            # Validate tool_call/tool_result pairs inside the kept suffix.
            start_index = self._repair_tool_pairs_in_suffix(start_index, available_tokens=available)
            kept = self.conversation[start_index:]

        if not kept and self.conversation:
            # Fallback to the latest safe boundary when strict budget trimming removes everything.
            fallback_start = len(self.conversation) - 1
            for idx in range(len(self.conversation) - 1, -1, -1):
                if self._is_safe_split_message(self.conversation[idx]):
                    fallback_start = idx
                    break
            fallback_start = self._repair_tool_pairs_in_suffix(fallback_start)
            kept = self.conversation[fallback_start:]

        trimmed = len(self.conversation) - len(kept)
        if trimmed > 0:
            console.print(f"  [#6E7681]⚠ Trimmed {trimmed} old messages to fit context window "
                          f"({context_window:,} tokens)[/#6E7681]")

        return [system_msg] + kept

    # ── Streaming response ─────────────────────

    def _stream_response(self, messages: list) -> LLMResponse:
        """Stream LLM response, rendering text incrementally via Rich Live panel.
        Supports Ctrl+C graceful interruption and reasoning content display."""
        response: Optional[LLMResponse] = None
        accumulated_text = ""
        accumulated_reasoning = ""
        live: Optional[Live] = None
        # Force unified markdown-capable rendering for all stream profiles,
        # including ultra, to avoid raw markdown tokens leaking to terminal.
        use_plain_stream = False
        plain_stream_started = False
        plain_md_pending = ""
        thinking_notice_shown = False
        reasoning_stream_buffer = ""
        last_reasoning_brief = ""
        thinking_status: Optional[Status] = None
        interrupted = False
        last_render_at = 0.0
        last_visible_chars = 0

        def _safe_markdown(text: str) -> str:
            """Best-effort sanitize incomplete markdown for live rendering."""
            if not text:
                return text
            # Close unclosed code fences
            fence_count = len(re.findall(r"(?m)^```", text))
            if fence_count % 2 == 1:
                text += "\n```"
            # Close unclosed inline markup (order matters: longest first)
            for marker in ("***", "**", "__"):
                if text.count(marker) % 2 == 1:
                    text += marker
            return text

        def _build_panel(render_markdown: bool = False):
            """Build the display area with thinking summary when available."""
            if accumulated_text:
                if accumulated_text.strip():
                    return Markdown(_safe_markdown(accumulated_text))
                return Text(accumulated_text)
            elif accumulated_reasoning:
                if self.reasoning_display == "off":
                    return Text("  ⏳ thinking…", style="#6E7681")
                reasoning_lines = accumulated_reasoning.strip().splitlines()
                if self.reasoning_display != "full":
                    return Text(
                        f"💭 thinking… ({len(reasoning_lines)} lines)",
                        style="#6E7681",
                    )
                if len(reasoning_lines) > 12:
                    shown = reasoning_lines[-10:]
                    content = f"💭 *thinking… ({len(reasoning_lines)} lines, showing last 10)*\n"
                    content += "\n".join(f"{l}" for l in shown)
                else:
                    content = "💭 *thinking…*\n"
                    content += "\n".join(reasoning_lines)
                return Text(content, style="#6E7681")
            else:
                return Text("  ⏳ thinking…", style="#6E7681")

        def _visible_chars() -> int:
            if accumulated_text:
                return len(accumulated_text)
            return len(accumulated_reasoning)

        def _is_priority_chunk(chunk: str) -> bool:
            if not chunk:
                return False
            # Prefer immediate flush on natural phrase boundaries.
            if any(mark in chunk for mark in ("\n", "。", "！", "？", "；", "：", ".", "!", "?", ";", ":")):
                return True
            return len(chunk) >= max(4, self._stream_profile_setting("min_chars"))

        def _ensure_live() -> None:
            nonlocal live
            if live is not None:
                return
            console.print()
            live = Live(console=console, refresh_per_second=8, auto_refresh=False)
            live.start()

        def _ensure_plain_stream() -> None:
            nonlocal plain_stream_started
            if plain_stream_started:
                return
            if not thinking_notice_shown:
                console.print()
            plain_stream_started = True

        def _sanitize_plain_chunk(chunk: str, *, final: bool = False) -> str:
            nonlocal plain_md_pending
            text = plain_md_pending + (chunk or "")
            plain_md_pending = ""

            if not final and text:
                trailing = ""
                while text and text[-1] in ("*", "_", "`") and len(trailing) < 2:
                    trailing = text[-1] + trailing
                    text = text[:-1]
                plain_md_pending = trailing

            if not text:
                return ""

            text = text.replace("```", "")
            text = text.replace("**", "")
            text = text.replace("__", "")
            text = text.replace("`", "")
            text = re.sub(r"(?m)^\\s{0,3}#{1,6}\\s+", "", text)
            text = re.sub(r"(?m)^\\s*>\\s?", "", text)
            return text

        def _write_plain_text(chunk: str) -> None:
            if not chunk:
                return
            _ensure_plain_stream()
            stream = getattr(console, "file", None)
            if stream is not None and hasattr(stream, "write"):
                stream.write(chunk)
                if hasattr(stream, "flush"):
                    stream.flush()
                return
            console.print(chunk, end="", markup=False, highlight=False, soft_wrap=True)

        def _stream_plain_text(chunk: str) -> None:
            if not chunk:
                return
            cleaned = _sanitize_plain_chunk(chunk)
            if cleaned:
                _write_plain_text(cleaned)

        def _compress_reasoning_line(line: str) -> str:
            compact = " ".join(line.strip().split())
            if not compact:
                return ""
            if len(compact) > 96:
                return compact[:93] + "..."
            return compact

        def _stop_thinking() -> None:
            nonlocal thinking_status
            if thinking_status is not None:
                thinking_status.stop()
                thinking_status = None

        def _stream_plain_reasoning(chunk: str) -> None:
            nonlocal reasoning_stream_buffer, thinking_notice_shown, last_reasoning_brief, thinking_status
            if self.reasoning_display == "off" or not chunk:
                return

            reasoning_stream_buffer += chunk
            while "\n" in reasoning_stream_buffer:
                line, reasoning_stream_buffer = reasoning_stream_buffer.split("\n", 1)
                brief = _compress_reasoning_line(line)
                if not brief:
                    continue
                if self.reasoning_display == "summary" and brief == last_reasoning_brief:
                    continue

                msg = line.strip() if self.reasoning_display == "full" else brief
                if not thinking_notice_shown:
                    thinking_status = Status(
                        f"  [#6E7681]💭 {msg}[/#6E7681]",
                        console=console, spinner="dots", spinner_style="#7FA6D9")
                    thinking_status.start()
                    thinking_notice_shown = True
                else:
                    thinking_status.update(f"  [#6E7681]💭 {msg}[/#6E7681]")
                last_reasoning_brief = brief

        def _flush_plain_reasoning_buffer() -> None:
            nonlocal reasoning_stream_buffer, thinking_notice_shown, last_reasoning_brief, thinking_status
            if self.reasoning_display == "off":
                reasoning_stream_buffer = ""
                return

            brief = _compress_reasoning_line(reasoning_stream_buffer)
            if not brief:
                reasoning_stream_buffer = ""
                return

            if self.reasoning_display == "summary" and brief == last_reasoning_brief:
                reasoning_stream_buffer = ""
                return

            msg = reasoning_stream_buffer.strip() if self.reasoning_display == "full" else brief
            if not thinking_notice_shown:
                thinking_status = Status(
                    f"  [#6E7681]💭 {msg}[/#6E7681]",
                    console=console, spinner="dots", spinner_style="#7FA6D9")
                thinking_status.start()
                thinking_notice_shown = True
            else:
                thinking_status.update(f"  [#6E7681]💭 {msg}[/#6E7681]")
            last_reasoning_brief = brief
            reasoning_stream_buffer = ""

        def _maybe_render(force: bool = False, final: bool = False, priority: bool = False) -> None:
            nonlocal last_render_at, last_visible_chars
            if live is None:
                return

            visible_chars = _visible_chars()
            if visible_chars < last_visible_chars:
                last_visible_chars = 0

            if not force:
                elapsed = time.monotonic() - last_render_at
                growth = visible_chars - last_visible_chars

                # Time-based fallback: always refresh after max_silent_ms
                max_silent = self._stream_profile_setting("max_silent_ms") / 1000.0
                silent_ready = elapsed >= max_silent and growth > 0

                priority_ready = (
                    priority
                    and growth >= self._stream_profile_setting("priority_chars")
                    and elapsed >= self._stream_profile_setting("priority_interval")
                )
                normal_ready = (
                    growth >= self._stream_profile_setting("min_chars")
                    or elapsed >= self._stream_profile_setting("interval")
                )
                if not silent_ready and not priority_ready and not normal_ready:
                    return

            live.update(_build_panel())
            if hasattr(live, "refresh"):
                live.refresh()
            last_render_at = time.monotonic()
            last_visible_chars = _visible_chars()

        try:
            for event_type, data in self.llm.chat_stream(messages, tools=self.tools.schemas):
                if event_type == "text":
                    accumulated_text += data
                    if use_plain_stream:
                        _stop_thinking()
                        _flush_plain_reasoning_buffer()
                        _stream_plain_text(data)
                    else:
                        _ensure_live()
                        _maybe_render(priority=_is_priority_chunk(data))
                elif event_type == "reasoning":
                    accumulated_reasoning += data
                    # Show thinking only before primary content appears
                    if not accumulated_text:
                        if use_plain_stream:
                            _stream_plain_reasoning(data)
                        else:
                            _ensure_live()
                            _maybe_render(priority=_is_priority_chunk(data))
                elif event_type == "done":
                    response = data
        except KeyboardInterrupt:
            interrupted = True
            _stop_thinking()
            if plain_stream_started:
                console.print()
            # Build a partial response from what we have so far
            content = accumulated_text if accumulated_text else "(interrupted)"
            reasoning = accumulated_reasoning if accumulated_reasoning else None
            if reasoning is not None and not reasoning:
                reasoning = ""
            response = LLMResponse(content=content, reasoning_content=reasoning)
            console.print("\n  [#E3B341]⚠ Stream interrupted by user[/#E3B341]")
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(f"Streaming error: {type(e).__name__}: {e}")
        finally:
            _stop_thinking()
            if live is not None:
                _maybe_render(force=True, final=True)
                live.stop()
            elif plain_stream_started:
                _flush_plain_reasoning_buffer()
                tail = _sanitize_plain_chunk("", final=True)
                if tail:
                    _write_plain_text(tail)
                console.print()

            # Show thinking summary after main content (if reasoning was used)
            if accumulated_reasoning and accumulated_text:
                reasoning_lines = accumulated_reasoning.strip().splitlines()
                if self.reasoning_display != "off" and len(reasoning_lines) > 3:
                    console.print()
                    console.print(f"  [#484F58]───[/#484F58] [#6E7681]💭 {len(reasoning_lines)} lines of reasoning[/#6E7681] [#484F58]───[/#484F58]")

        if response is None:
            raise ConnectionError("Stream ended without completion")

        return response

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
            for future, tool_id in list(future_map.items()):
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
                console.print("     [#30363D]·[/#30363D]")
            self._render_tool_call(tc.name, tc.arguments, index=i, total=total_calls)

            if not self.auto_confirm and ToolRegistry.needs_confirmation(tc.name):
                if not self._confirm(tc.name, tc.arguments):
                    self.conversation.append({"role": "tool", "tool_call_id": tc.id,
                                              "content": "⚠ User denied."})
                    console.print("  [#E3B341]↳ skipped[/#E3B341]")
                    continue

            if tc.id in parallel_results:
                result, elapsed = parallel_results[tc.id]
            else:
                with Status(f"  [#6E7681]  running…[/#6E7681]",
                            console=console, spinner="dots", spinner_style="#7FA6D9"):
                    result, elapsed = self._execute_single_tool_call(tc)
            self._render_result(tc.name, result, elapsed)

            # Handle image results specially for multimodal
            if tc.name == "read_image" and result.startswith("[IMAGE:"):
                self._handle_image_result(tc, result)
                continue

            if tc.name == "web_fetch":
                self._capture_web_fetch_evidence(result)
                stored_result = self._summarize_web_for_context(result)
                self.conversation.append({"role": "tool", "tool_call_id": tc.id, "content": stored_result})
                continue

            if tc.name == "web_search":
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
            console.print(f"\n  [#484F58]─ {total_calls} tools · {batch_elapsed:.1f}s ─[/#484F58]")

    def _summarize_web_for_context(self, result: str) -> str:
        """Store concise web content in context to reduce token pressure."""
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return self._truncate_tool_result(result)

        if self.web_display == "full":
            return self._truncate_tool_result(result)

        text = result.strip()
        if not text:
            return result

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        first = lines[0]
        start_index = 0
        if first.lower().startswith("url:"):
            header = first
            start_index = 1
        else:
            header = "URL: (not provided)"

        body = lines[start_index:]
        summary_lines: List[str] = []
        consumed = 0
        if self.web_display == "brief":
            max_lines = 1
            max_chars = min(600, max(200, self.web_context_chars // 5))
        else:
            max_lines = max(2, self.web_preview_lines + 2)
            max_chars = self.web_context_chars

        for line in body:
            if consumed >= max_chars:
                break
            remaining = max_chars - consumed
            clipped = line[:remaining]
            summary_lines.append(clipped)
            consumed += len(clipped)
            if len(summary_lines) >= max_lines:
                break

        summary_text = "\n".join(summary_lines)
        omitted_chars = max(0, len("\n".join(body)) - consumed)

        parts = [header]
        if summary_text:
            parts.extend(["", summary_text])
        if omitted_chars > 0:
            parts.append(f"\n... (context summary omitted {omitted_chars:,} chars)")
        return "\n".join(parts)

    def _format_web_result_preview(self, result: str) -> str:
        """Compress web tool output for terminal display."""
        if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
            return result

        if self.web_display == "full":
            return result

        text = result.strip()
        if not text:
            return result

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return result

        first = lines[0]
        if first.lower().startswith("url:"):
            url = first[4:].strip()
            body_lines = lines[1:]
        else:
            url = "(unknown)"
            body_lines = lines

        body_text = " ".join(body_lines).strip()

        if self.web_display == "brief":
            if not body_text:
                return f"web: {url}"
            snippet_limit = max(80, min(self.web_preview_chars, 180))
            snippet = body_text[:snippet_limit].strip()
            omitted_chars = max(0, len(body_text) - len(snippet))
            tail = f" ... (+{omitted_chars:,} chars)" if omitted_chars > 0 else ""
            return f"web: {url} | {snippet}{tail}"

        preview_lines: List[str] = []
        used_chars = 0
        for line in body_lines:
            if len(preview_lines) >= self.web_preview_lines:
                break
            if used_chars >= self.web_preview_chars:
                break
            remaining = self.web_preview_chars - used_chars
            clipped = line[:remaining].strip()
            if not clipped:
                continue
            preview_lines.append(clipped)
            used_chars += len(clipped)

        omitted_chars = max(0, len(body_text) - used_chars)
        preview = "\n     ".join(preview_lines) if preview_lines else "(no preview)"
        tail = (
            f"\n     ... ({omitted_chars:,} chars omitted)"
            if omitted_chars > 0
            else ""
        )
        return f"web: {url}\n     {preview}{tail}"

    def _confirm(self, tool_name: str, arguments: dict) -> bool:
        try:
            # Show diff preview for file editing operations
            if tool_name == "str_replace":
                self._show_edit_preview(tool_name, arguments)
            elif tool_name == "write_file":
                self._show_write_preview(arguments)
            elif tool_name == "bash":
                cmd = arguments.get("command", "")
                console.print(f"  [#6E7681]$[/#6E7681] {cmd}")

            ans = console.input(
                "  [#E3B341]?[/#E3B341] "
                "[bold #E6EDF3](y)[/bold #E6EDF3][#8B949E]es[/#8B949E] / "
                "[bold #E6EDF3](n)[/bold #E6EDF3][#8B949E]o[/#8B949E] / "
                "[bold #E6EDF3](a)[/bold #E6EDF3][#8B949E]lways[/#8B949E]: "
            ).strip().lower()
            if ans in ("a", "always"):
                self.auto_confirm = True
                return True
            return ans in ("y", "yes", "")
        except (KeyboardInterrupt, EOFError):
            return False

    def _build_diff_panel(self, diff: str) -> Panel:
        """Build a Rich Panel containing colored diff output."""
        diff_text = Text()
        lines = diff.splitlines()[:30]
        for i, line in enumerate(lines):
            if i > 0:
                diff_text.append("\n")
            if line.startswith('+') and not line.startswith('+++'):
                diff_text.append(line, style="#57DB9C")
            elif line.startswith('-') and not line.startswith('---'):
                diff_text.append(line, style="#F85149")
            elif line.startswith('@@'):
                diff_text.append(line, style="#58A6FF")
            else:
                diff_text.append(line, style="#6E7681")
        total = len(diff.splitlines())
        if total > 30:
            diff_text.append(f"\n… {total - 30} more lines", style="#6E7681")
        return Panel(diff_text, border_style="#30363D", padding=(0, 1), expand=False)

    def _show_edit_preview(self, tool_name: str, arguments: dict):
        """Show diff preview for str_replace."""
        path = arguments.get("path", "")
        old_str = arguments.get("old_str", "")
        new_str = arguments.get("new_str", "")

        can_apply, diff = self.tools.files.preview_str_replace(path, old_str, new_str)
        if can_apply and diff:
            console.print(self._build_diff_panel(diff))
        elif not can_apply:
            console.print(f"  [#E3B341]⚠ {diff}[/#E3B341]")

    def _show_write_preview(self, arguments: dict):
        """Show diff preview for write_file."""
        path = arguments.get("path", "")
        content = arguments.get("content", "")

        is_overwrite, diff = self.tools.files.preview_write_file(path, content)
        if is_overwrite and diff:
            console.print(self._build_diff_panel(diff))
        else:
            console.print(f"  [#6E7681]{diff}[/#6E7681]")

    def _handle_image_result(self, tc, result: str):
        """Handle image tool result for multimodal LLM."""
        path = tc.arguments.get("path", "")
        try:
            img_data = self.tools.files.read_image(path)
            # Create multimodal tool result
            content = [
                {"type": "text", "text": f"Image loaded: {path} ({img_data['size']} bytes)"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img_data['media_type']};base64,{img_data['data']}"
                    }
                }
            ]
            self.conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": content
            })
        except Exception as e:
            self.conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": f"Error loading image: {e}"
            })

    # ── Rendering ──────────────────────────────

    def _render_error(self, message: str):
        panel = Panel(
            f"[#F85149]{message}[/#F85149]",
            title="[bold #F85149]Error[/bold #F85149]",
            title_align="left",
            border_style="#F85149",
            padding=(0, 2),
        )
        console.print()
        console.print(panel)

    def _render_tool_call(self, name, args, index=None, total=None):
        icons = {
            "read_file": "▸", "create_file": "◆", "write_file": "◆",
            "str_replace": "✎", "delete_file": "✕", "list_directory": "≡",
            "search_files": "⊙", "bash": "$", "web_fetch": "◎",
            "read_image": "▣",
        }
        icon = icons.get(name, "·")

        match name:
            case "bash":
                detail = args.get("command", "")
            case "read_file":
                detail = args.get("path", "")
                if "start_line" in args:
                    detail += f" L{args.get('start_line','')}-{args.get('end_line','∞')}"
            case "create_file" | "write_file":
                n = args.get("content", "").count("\n") + 1
                detail = f"{args.get('path','')} ({n} lines)"
            case "str_replace":
                detail = args.get("path", "")
            case "list_directory":
                detail = args.get("path", ".")
            case "search_files":
                detail = f"/{args.get('pattern', '')}/ in {args.get('path', '.')}"
            case "web_fetch":
                detail = args.get("url", "")
            case _:
                detail = ""

        progress = ""
        if total and total > 1:
            progress = f"[#6E7681]{index}/{total}[/#6E7681] "

        console.print(f"\n  {progress}[#7FA6D9]{icon}[/#7FA6D9] [bold #E6EDF3]{name}[/bold #E6EDF3] [#6E7681]{detail}[/#6E7681]")

    def _render_result(self, name, result, elapsed: float = 0):
        if (
            name == "web_fetch"
            and self.web_display != "full"
            and not result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out"))
        ):
            result = self._format_web_result_preview(result)

        lines = result.splitlines()
        time_str = f" [#484F58]({elapsed:.1f}s)[/#484F58]" if elapsed >= 0.1 else ""

        # Detect success vs error
        is_error = result.startswith(("⚠", "⛔", "⏱", "Error:", "Blocked:", "Timed out"))
        is_success = any(result.startswith(w) for w in
                         ("Created", "Edited", "Overwrote", "Deleted", "✓", "Found"))

        if is_error:
            preview = result if len(lines) <= 5 else "\n".join(lines[:5]) + f"\n     ... ({len(lines)-5} more)"
            console.print(f"     [#F85149]{preview}[/#F85149]{time_str}")
        elif is_success:
            first_line = result.splitlines()[0]
            if first_line.startswith("✓ "):
                first_line = first_line[2:]
            elif first_line.startswith("✓"):
                first_line = first_line[1:].lstrip()
            console.print(f"     [#57DB9C]✓ {first_line}[/#57DB9C]{time_str}")
        else:
            if len(lines) > 20:
                preview = "\n".join(lines[:15]) + f"\n     ... ({len(lines)-15} more lines)"
            else:
                preview = result
            for line in preview.splitlines()[:20]:
                console.print(f"     [#6E7681]{line}[/#6E7681]")
            if time_str:
                console.print(f"     {time_str}")

    def _render_write_diff(self, tool_name: str, arguments: dict):
        """Always show compact diff for write operations, regardless of auto_confirm."""
        if tool_name == "str_replace":
            old_str = arguments.get("old_str", "")
            new_str = arguments.get("new_str", "")
            console.print("     [#30363D]┌─[/#30363D]")
            for line in old_str.splitlines()[:3]:
                console.print(f"     [#30363D]│[/#30363D] [#F85149]- {line[:100]}[/#F85149]")
            for line in new_str.splitlines()[:3]:
                console.print(f"     [#30363D]│[/#30363D] [#57DB9C]+ {line[:100]}[/#57DB9C]")
            old_lines = old_str.count('\n') + 1
            new_lines = new_str.count('\n') + 1
            if old_lines > 3 or new_lines > 3:
                console.print(f"     [#30363D]│[/#30363D] [#6E7681]({old_lines} lines → {new_lines} lines)[/#6E7681]")
            console.print("     [#30363D]└─[/#30363D]")
        elif tool_name in ("write_file", "create_file"):
            content = arguments.get("content", "")
            line_count = content.count('\n') + 1
            console.print(f"     [#6E7681]({line_count} lines written)[/#6E7681]")

    def _inject_error_hint(self, tool_name: str, arguments: dict, result: str) -> str:
        """Append recovery hints to failed tool results."""
        if not result.startswith(("Error:", "⚠")):
            return result

        if tool_name == "str_replace" and "not found" in result.lower():
            path = arguments.get("path", "")
            return (result + "\n\nHINT: The exact search string was not found in the file. "
                    f"Use read_file on '{path}' to see the current content, "
                    "then retry str_replace with the exact text from the file.")

        if tool_name == "bash":
            return (result + "\n\nHINT: The command failed. Review the error output above, "
                    "check for typos or missing dependencies, and adjust the command.")

        if tool_name == "create_file" and "exists" in result.lower():
            return (result + "\n\nHINT: File already exists. Use str_replace for targeted edits "
                    "or write_file to overwrite the entire file.")

        return result

    def _try_parse_plan(self, content: str) -> Optional[Plan]:
        """Try to parse a structured plan from LLM response."""
        title_match = re.search(r'##\s*Plan:\s*(.+)', content)
        if not title_match:
            return None

        title = title_match.group(1).strip()
        step_pattern = re.compile(
            r'(\d+)\.\s*\[(\w+)\]\s*`([^`]+)`\s*[—\-]\s*(.+)'
        )
        steps = []
        for m in step_pattern.finditer(content):
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

        return compacted_count

    def reset(self):
        self.conversation.clear()
        self.total_tokens = 0
        self._turn_web_used = False
        self._turn_web_sources.clear()
