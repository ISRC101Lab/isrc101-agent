"""Token estimation utilities with tiktoken support."""

import re
from typing import Optional

_tiktoken_available = False
_encoder_cache = {}

try:
    import tiktoken
    _tiktoken_available = True
except ImportError:
    pass


def _get_encoder(model: str):
    """Get tiktoken encoder for model, with caching."""
    if not _tiktoken_available:
        return None

    if model in _encoder_cache:
        return _encoder_cache[model]

    try:
        # Try model-specific encoding first
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        # Fallback to cl100k_base (GPT-4, Claude compatible)
        enc = tiktoken.get_encoding("cl100k_base")

    _encoder_cache[model] = enc
    return enc


def estimate_tokens(text: str, model: Optional[str] = None) -> int:
    """Estimate token count for text.

    Uses tiktoken for accurate counting when available,
    falls back to heuristic estimation otherwise.
    """
    if not text:
        return 0

    # Try tiktoken first
    if _tiktoken_available and model:
        enc = _get_encoder(model)
        if enc:
            try:
                return len(enc.encode(text))
            except Exception:
                pass

    # Fallback: heuristic estimation
    return _heuristic_estimate(text)


def _heuristic_estimate(text: str) -> int:
    """Heuristic token estimation for mixed CJK/English text."""
    if not text:
        return 0

    # Count CJK characters (Chinese, Japanese, Korean)
    cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]')
    cjk_chars = len(cjk_pattern.findall(text))

    # Remove CJK for English estimation
    non_cjk = cjk_pattern.sub(' ', text)

    # English: ~4 chars per token
    # CJK: ~1.5 chars per token (each CJK char is often 1-2 tokens)
    english_tokens = len(non_cjk) / 4
    cjk_tokens = cjk_chars / 1.5

    return max(1, int(english_tokens + cjk_tokens))


def estimate_message_tokens(msg: dict, model: Optional[str] = None) -> int:
    """Estimate tokens for a conversation message."""
    tokens = 4  # per-message overhead

    content = msg.get("content", "") or ""
    tokens += estimate_tokens(content, model)

    # Tool calls
    if "tool_calls" in msg:
        import json
        try:
            tokens += estimate_tokens(json.dumps(msg["tool_calls"]), model)
        except (TypeError, ValueError):
            tokens += 100  # fallback estimate

    # Reasoning content
    if "reasoning_content" in msg:
        rc = msg.get("reasoning_content", "") or ""
        tokens += estimate_tokens(rc, model)

    return tokens
