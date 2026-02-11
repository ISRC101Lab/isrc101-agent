"""Web operations: Jina Reader (fetch) + Bing HTML search.

Jina Reader: prepend https://r.jina.ai/ to any URL → clean markdown, no API key.
Bing: free web search via plain HTTP GET, no extra libraries needed.
"""

import re
import time
from html import unescape as html_unescape
from typing import Optional, List
from urllib.parse import urlparse

_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# ── Query cleaning for better search results ──
# Chinese filler patterns (questions, modal particles, etc.)
_ZH_FILLER_RE = re.compile(
    r"(请问|请帮我|帮我|我想知道|我想了解|能不能|可以吗|是什么|有哪些|怎么样|"
    r"如何|怎么|什么是|告诉我|介绍一下|解释一下|说一下|讲一下|"
    r"吗|呢|吧|啊|哦|嘛|了|的|地|得|着|过)"
)
# English filler words
_EN_FILLER_WORDS = {
    "please", "help", "me", "i", "want", "to", "know", "about",
    "what", "is", "are", "how", "do", "does", "can", "you",
    "tell", "explain", "describe", "the", "a", "an",
}
_MULTI_SPACE_RE = re.compile(r"\s{2,}")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False



class WebOpsError(Exception):
    pass


def clean_search_query(query: str) -> str:
    """Clean up a natural-language query into concise search keywords.

    Strips Chinese filler particles, English stop words, and excess whitespace.
    Returns the original query if cleaning would reduce it to < 2 tokens.
    """
    cleaned = query.strip()
    if not cleaned:
        return query

    # Remove Chinese filler / modal particles
    cleaned = _ZH_FILLER_RE.sub(" ", cleaned)

    # Remove common English filler words (only whole words)
    words = cleaned.split()
    filtered = [w for w in words if w.lower() not in _EN_FILLER_WORDS]

    # Fall back to original if too aggressive
    if len(filtered) < 2:
        filtered = words

    cleaned = " ".join(filtered)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned if cleaned else query


class WebOps:
    """Web fetch via Jina Reader, search via Bing (plain HTTP)."""

    JINA_PREFIX = "https://r.jina.ai/"
    TIMEOUT = 30
    MAX_CONTENT_LENGTH = 40000

    def __init__(self):
        self._session = None

    @property
    def available(self) -> bool:
        return HAS_REQUESTS

    @property
    def search_available(self) -> bool:
        return HAS_REQUESTS

    def _get_session(self):
        if self._session is None and HAS_REQUESTS:
            self._session = requests.Session()
            self._session.headers.update({
                "Accept": "text/markdown, text/plain, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                "X-Return-Format": "markdown",
                "X-With-Links-Summary": "true",
            })
        return self._session

    _RETRYABLE_STATUS = {429, 500, 502, 503}

    def _request_with_retry(self, url: str, *, max_retries: int = 2,
                           progress_callback=None) -> "requests.Response":
        """GET with exponential backoff on transient errors.

        Args:
            url: URL to fetch
            max_retries: Maximum number of retry attempts
            progress_callback: Optional callable() for progress updates
        """
        session = self._get_session()
        last_exc: Optional[Exception] = None
        for attempt in range(1 + max_retries):
            try:
                if progress_callback:
                    progress_callback()
                resp = session.get(url, timeout=self.TIMEOUT)
                if resp.status_code not in self._RETRYABLE_STATUS or attempt == max_retries:
                    resp.raise_for_status()
                    return resp
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt == max_retries:
                    raise
            except requests.HTTPError as e:
                last_exc = e
                if attempt == max_retries:
                    raise
            delay = (2 ** attempt)  # 1s → 2s → 4s
            if progress_callback:
                progress_callback()
            time.sleep(delay)
        raise last_exc  # unreachable, but satisfies type checker

    # ── URL Fetch (Jina Reader) ──

    def fetch(self, url: str, progress_callback=None) -> str:
        """Fetch URL via Jina Reader → clean markdown.

        Args:
            url: URL to fetch
            progress_callback: Optional callable() for progress updates
        """
        if not HAS_REQUESTS:
            raise WebOpsError("requests not installed")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise WebOpsError(f"Invalid URL scheme: {parsed.scheme}")

        jina_url = self.JINA_PREFIX + url
        try:
            resp = self._request_with_retry(jina_url, progress_callback=progress_callback)
        except requests.RequestException as e:
            raise WebOpsError(f"Jina fetch failed: {e}")

        text = resp.text.strip()
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return self._truncate(text, url)

    # ── Web Search (Bing HTML) ──

    _BING_URL = "https://cn.bing.com/search"
    # Regex to extract result blocks from Bing HTML
    _BING_BLOCK_RE = re.compile(
        r'<li class="b_algo"[^>]*>(.*?)(?=<li class="b_algo"|</ol>|$)',
        re.DOTALL,
    )
    _BING_TITLE_URL_RE = re.compile(
        r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2>',
        re.DOTALL,
    )
    _BING_SNIPPET_RE = re.compile(
        r'<div class="b_caption"[^>]*><p[^>]*>(.*?)</p>',
        re.DOTALL,
    )

    def search(self, query: str, max_results: int = 5, domains: Optional[List[str]] = None,
              progress_callback=None) -> str:
        """Search web via Bing — plain HTTP, no extra libs.

        Args:
            query: Search query
            max_results: Maximum number of results to return
            domains: Optional list of domains to filter results
            progress_callback: Optional callable() for progress updates
        """
        if not HAS_REQUESTS:
            raise WebOpsError("requests not installed")

        query = clean_search_query(query)

        effective_query = query
        normalized_domains = [str(d).strip().lower() for d in (domains or []) if str(d).strip()]
        if normalized_domains:
            domain_filter = " OR ".join(f"site:{d}" for d in normalized_domains)
            effective_query = f"{query} ({domain_filter})"

        try:
            if progress_callback:
                progress_callback()
            resp = requests.get(
                self._BING_URL,
                params={"q": effective_query, "setlang": "en"},
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
                },
                timeout=self.TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise WebOpsError(f"Bing search failed: {e}")

        results = self._parse_bing_html(resp.text, max_results)

        if normalized_domains:
            results = [
                r for r in results
                if self._host_matches_domains(r["url"], normalized_domains)
            ]

        return self._format_search_results(query, results)

    def _parse_bing_html(self, html: str, max_results: int) -> List[dict]:
        """Extract title/url/snippet from Bing HTML response."""
        results = []
        blocks = self._BING_BLOCK_RE.findall(html)

        for block in blocks:
            if len(results) >= max_results:
                break

            # Extract title and URL
            title_match = self._BING_TITLE_URL_RE.search(block)
            if not title_match:
                continue

            url = html_unescape(title_match.group(1)).strip()
            title = re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
            title = html_unescape(title)

            # Extract snippet
            snippet = ""
            snippet_match = self._BING_SNIPPET_RE.search(block)
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
                snippet = html_unescape(snippet)

            if url and title:
                results.append({"title": title, "url": url, "snippet": snippet})

        return results

    @staticmethod
    def _host_matches_domains(url: str, domains: List[str]) -> bool:
        host = urlparse(url).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return any(host == d or host.endswith(f".{d}") for d in domains)

    @staticmethod
    def _format_search_results(query: str, results: List[dict]) -> str:
        lines = [f"Search: {query}\n"]
        if not results:
            lines.append("No results found.")
            return "\n".join(lines)
        for i, r in enumerate(results, 1):
            snippet = r["snippet"]
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."
            lines.append(f"{i}. [{r['title']}]({r['url']})")
            if snippet:
                lines.append(f"   {snippet}\n")
        return "\n".join(lines)

    # ── Helpers ──

    def _truncate(self, text: str, url: str) -> str:
        if len(text) > self.MAX_CONTENT_LENGTH:
            text = text[:self.MAX_CONTENT_LENGTH] + "\n\n... (truncated)"
        return f"URL: {url}\n\n{text}"
