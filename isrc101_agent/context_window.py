"""Context window token budget and message trimming logic."""

import json
from typing import List, Dict, Any, Optional, Tuple

from .tokenizer import estimate_tokens, estimate_message_tokens

__all__ = ["ContextWindowManager"]

MAX_TOOL_RESULT_CHARS = 12000  # ~4000 tokens


class ContextWindowManager:
    def __init__(self, model: str, max_tokens: int, context_window: int = 128000):
        self.model = model
        self.max_tokens = max_tokens
        self.context_window = context_window
        # Cache keyed by id(msg) — safe because conversation dicts are never
        # mutated in-place and invalidate_token_cache() is called on compaction.
        self._token_cache: Dict[int, int] = {}
        # Scale tool result truncation with context window (12000 for 128K, min 4000)
        self.max_tool_result_chars = max(4000, int(12000 * (context_window / 128000)))

    def estimate_tokens(self, text: str) -> int:
        return estimate_tokens(text, self.model)

    def estimate_message_tokens(self, msg: dict) -> int:
        key = id(msg)
        cached = self._token_cache.get(key)
        if cached is not None:
            return cached
        result = estimate_message_tokens(msg, self.model)
        self._token_cache[key] = result
        return result

    def invalidate_token_cache(self):
        """Clear the token estimation cache (call after compaction)."""
        self._token_cache.clear()

    @staticmethod
    def assistant_tool_call_ids(msg: Dict[str, Any]) -> List[str]:
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

    def compute_token_prefix(self, conversation: list, end: int) -> List[int]:
        prefix = [0] * (max(0, end) + 1)
        running = 0
        for idx in range(end):
            running += self.estimate_message_tokens(conversation[idx])
            prefix[idx + 1] = running
        return prefix

    @staticmethod
    def range_sum(prefix: List[int], start: int, end: int) -> int:
        if start >= end:
            return 0
        return prefix[end] - prefix[start]

    @staticmethod
    def is_safe_split_message(msg: Dict[str, Any]) -> bool:
        role = msg.get("role")
        if role == "user":
            return True
        if role == "assistant" and not msg.get("tool_calls"):
            return True
        return False

    def build_suffix_indexes(
        self, conversation: list, start: int, total: int,
        assistant_call_cache: Dict[int, List[str]],
    ):
        assistant_by_call_id: Dict[str, int] = {}
        assistant_calls_by_index: Dict[int, List[str]] = {}
        call_id_to_result_indexes: Dict[str, List[int]] = {}
        orphan_tools: List[Tuple[int, Optional[str]]] = []

        for idx in range(start, total):
            msg = conversation[idx]
            role = msg.get("role")
            if role == "assistant":
                call_ids = assistant_call_cache.get(idx)
                if call_ids is None:
                    call_ids = self.assistant_tool_call_ids(msg)
                    assistant_call_cache[idx] = call_ids
                if not call_ids:
                    continue
                assistant_calls_by_index[idx] = call_ids
                for call_id in call_ids:
                    assistant_by_call_id[call_id] = idx
            elif role == "tool":
                call_id = msg.get("tool_call_id")
                if not call_id:
                    orphan_tools.append((idx, None))
                    continue
                call_id_to_result_indexes.setdefault(call_id, []).append(idx)

        return assistant_by_call_id, assistant_calls_by_index, call_id_to_result_indexes, orphan_tools

    def find_parent_assistant_index(
        self, conversation: list, tool_call_id: str, before_index: int,
        assistant_call_cache: Optional[Dict[int, List[str]]] = None,
    ) -> Optional[int]:
        if not tool_call_id:
            return None
        for idx in range(before_index, -1, -1):
            call_ids = None
            if assistant_call_cache is not None:
                call_ids = assistant_call_cache.get(idx)
            if call_ids is None:
                call_ids = self.assistant_tool_call_ids(conversation[idx])
                if assistant_call_cache is not None:
                    assistant_call_cache[idx] = call_ids
            if tool_call_id in call_ids:
                return idx
        return None

    def repair_tool_pairs_in_suffix(
        self, conversation: list, start: int,
        available_tokens: Optional[int] = None,
    ) -> int:
        total = len(conversation)
        start = max(0, min(start, total))

        token_prefix: Optional[List[int]] = None
        if available_tokens is not None:
            token_prefix = self.compute_token_prefix(conversation, total)
        assistant_call_cache: Dict[int, List[str]] = {}

        while start < total:
            (assistant_by_call_id, assistant_calls_by_index,
             call_id_to_result_indexes, orphan_tools) = self.build_suffix_indexes(
                conversation, start, total, assistant_call_cache)

            orphan_tool_index: Optional[int] = None
            orphan_parent_index: Optional[int] = None
            for idx, call_id in orphan_tools:
                orphan_tool_index = idx
                orphan_parent_index = None
                if call_id:
                    orphan_parent_index = self.find_parent_assistant_index(
                        conversation, call_id, idx - 1, assistant_call_cache)
                break

            if orphan_tool_index is None:
                for call_id, result_indexes in call_id_to_result_indexes.items():
                    if call_id in assistant_by_call_id:
                        continue
                    orphan_tool_index = result_indexes[0]
                    orphan_parent_index = self.find_parent_assistant_index(
                        conversation, call_id, orphan_tool_index - 1, assistant_call_cache)
                    break

            if orphan_tool_index is not None:
                if orphan_parent_index is not None and orphan_parent_index < start:
                    if available_tokens is None:
                        start = orphan_parent_index
                        continue
                    if token_prefix is None:
                        token_prefix = self.compute_token_prefix(conversation, total)
                    current_tokens = self.range_sum(token_prefix, start, total)
                    extra_tokens = self.range_sum(token_prefix, orphan_parent_index, start)
                    if current_tokens + extra_tokens <= available_tokens:
                        start = orphan_parent_index
                        continue
                start = orphan_tool_index + 1
                continue

            missing_drop_index: Optional[int] = None
            for assistant_index, call_ids in assistant_calls_by_index.items():
                missing = [cid for cid in call_ids if cid not in call_id_to_result_indexes]
                if not missing:
                    continue
                related_result_indexes = [
                    ri for cid in call_ids
                    for ri in call_id_to_result_indexes.get(cid, [])
                ]
                drop_until = max(related_result_indexes) + 1 if related_result_indexes else assistant_index + 1
                missing_drop_index = drop_until
                break

            if missing_drop_index is not None:
                start = missing_drop_index
                continue
            break

        return start

    def truncate_tool_result(self, result: str) -> str:
        limit = self.max_tool_result_chars
        if len(result) <= limit:
            return result
        half = limit // 2
        lines_total = result.count("\n") + 1
        return (result[:half]
                + f"\n\n... [truncated: {lines_total} lines, {len(result):,} chars"
                  f" → keeping first/last portions] ...\n\n"
                + result[-half:])

    def prepare_messages(self, conversation: list, system_prompt: str, console,
                         tool_schemas: Optional[list] = None,
                         on_trimmed=None) -> list:
        system_msg = {"role": "system", "content": system_prompt}

        # Tool schemas consume context window tokens
        tool_schema_tokens = 0
        if tool_schemas:
            try:
                tool_schema_tokens = self.estimate_tokens(json.dumps(tool_schemas))
            except Exception:
                tool_schema_tokens = len(tool_schemas) * 150  # conservative fallback

        safety_margin = 2000  # increased from 1000
        budget = self.context_window - self.max_tokens - safety_margin - tool_schema_tokens
        system_tokens = self.estimate_tokens(system_prompt) + 4
        available = budget - system_tokens

        kept: List[Dict[str, Any]] = []
        used = 0
        start_index = len(conversation)
        for msg in reversed(conversation):
            msg_tokens = self.estimate_message_tokens(msg)
            if used + msg_tokens > available:
                break
            kept.append(msg)
            used += msg_tokens
            start_index -= 1
        kept.reverse()

        if not kept and conversation:
            kept = [conversation[-1]]
            start_index = len(conversation) - 1

        if kept:
            start_index = self.repair_tool_pairs_in_suffix(
                conversation, start_index, available_tokens=available)
            kept = conversation[start_index:]

        if not kept and conversation:
            fallback_start = len(conversation) - 1
            for idx in range(len(conversation) - 1, -1, -1):
                if self.is_safe_split_message(conversation[idx]):
                    fallback_start = idx
                    break
            fallback_start = self.repair_tool_pairs_in_suffix(conversation, fallback_start)
            kept = conversation[fallback_start:]

        trimmed = len(conversation) - len(kept)
        if trimmed > 0:
            if on_trimmed:
                on_trimmed(trimmed, self.context_window)
            else:
                console.print(
                    f"  [#6E7681]⚠ Trimmed {trimmed} old messages to fit context window "
                    f"({self.context_window:,} tokens)[/#6E7681]")

        return [system_msg] + kept
