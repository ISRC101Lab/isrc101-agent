"""Web result formatting and summary logic."""

from typing import List

__all__ = ["summarize_web_for_context", "format_web_result_preview"]


def summarize_web_for_context(
    result: str, web_display: str,
    web_context_chars: int, web_preview_lines: int,
    truncate_fn=None,
) -> str:
    """Store concise web content in context to reduce token pressure."""
    if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
        return truncate_fn(result) if truncate_fn else result

    if web_display == "full":
        return truncate_fn(result) if truncate_fn else result

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
    if web_display == "brief":
        max_lines = 1
        max_chars = min(600, max(200, web_context_chars // 5))
    else:
        # Let the char budget be the primary constraint, not line count.
        # Previous limit of ~5 lines wasted most of the 4000-char budget,
        # causing the LLM to re-fetch the same URL for more content.
        max_lines = max(40, web_context_chars // 80)
        max_chars = web_context_chars

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


def format_web_result_preview(
    result: str, web_display: str,
    web_preview_lines: int, web_preview_chars: int,
) -> str:
    """Compress web tool output for terminal display."""
    if result.startswith(("Web error:", "Error:", "⚠", "Blocked:", "Timed out")):
        return result

    if web_display == "full":
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

    if web_display == "brief":
        if not body_text:
            return f"web: {url}"
        snippet_limit = max(80, min(web_preview_chars, 180))
        snippet = body_text[:snippet_limit].strip()
        omitted_chars = max(0, len(body_text) - len(snippet))
        tail = f" ... (+{omitted_chars:,} chars)" if omitted_chars > 0 else ""
        return f"web: {url} | {snippet}{tail}"

    preview_lines: List[str] = []
    used_chars = 0
    for line in body_lines:
        if len(preview_lines) >= web_preview_lines:
            break
        if used_chars >= web_preview_chars:
            break
        remaining = web_preview_chars - used_chars
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
