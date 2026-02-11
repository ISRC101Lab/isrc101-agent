"""URL/domain utility functions and reference rendering helpers."""

import re
from typing import List
from urllib.parse import urlparse

__all__ = [
    "SEARCH_URL_RE",
    "url_host",
    "matches_official_domains",
    "extract_search_links",
    "normalize_text_for_match",
    "render_sources_footer",
    "render_grounding_refusal",
    "render_grounding_partial",
]

SEARCH_URL_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
_WHITESPACE_RE = re.compile(r"\s+")


def url_host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def matches_official_domains(url: str, domains: List[str]) -> bool:
    if not domains:
        return False
    host = url_host(url)
    if not host:
        return False
    for domain in domains:
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def extract_search_links(result: str) -> List[str]:
    links = SEARCH_URL_RE.findall(result or "")
    if not links:
        return []
    dedup: List[str] = []
    seen = set()
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        dedup.append(link)
    return dedup


def normalize_text_for_match(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", (text or "")).strip().lower()


def render_sources_footer(sources: List[str]) -> str:
    if not sources:
        return ""
    lines = "\n".join(f"- {url}" for url in sources)
    return f"\n\nSources:\n{lines}"


def render_grounding_refusal(reason: str, source_urls: List[str]) -> str:
    msg = "I cannot verify a reliable answer from the fetched sources in this turn."
    detail = f"\n\nReason: {reason}" if reason else ""
    hint = "\n\nPlease provide a more specific official URL or ask me to fetch additional sources."
    footer = render_sources_footer(source_urls)
    return msg + detail + hint + footer


def render_grounding_partial(reason: str, source_urls: List[str]) -> str:
    msg = "I found partial evidence from fetched sources, but cannot fully verify every claim in this turn."
    detail = f"\n\nReason: {reason}" if reason else ""
    footer = render_sources_footer(source_urls)
    return msg + detail + footer
