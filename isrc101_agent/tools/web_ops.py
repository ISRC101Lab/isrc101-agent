"""Web operations: Jina Reader (fetch) + DuckDuckGo/Tavily (search).

Jina Reader: prepend https://r.jina.ai/ to any URL → clean markdown, no API key.
DuckDuckGo: free web search, no API key (default).
Tavily: AI-optimized search, optional upgrade when API key is set.
"""

import re
import time
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

try:
    from ddgs import DDGS
    HAS_DDG = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDG = True
    except ImportError:
        HAS_DDG = False

try:
    from tavily import TavilyClient
    HAS_TAVILY = True
except ImportError:
    HAS_TAVILY = False


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
    """Web fetch via Jina Reader, search via DuckDuckGo (free) or Tavily (optional)."""

    JINA_PREFIX = "https://r.jina.ai/"
    TIMEOUT = 30
    MAX_CONTENT_LENGTH = 40000

    def __init__(self, tavily_api_key: Optional[str] = None):
        self._session = None
        self._tavily = None
        if tavily_api_key and HAS_TAVILY:
            self._tavily = TavilyClient(api_key=tavily_api_key)

    @property
    def available(self) -> bool:
        return HAS_REQUESTS

    @property
    def search_available(self) -> bool:
        return HAS_DDG or self._tavily is not None

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

    def _request_with_retry(self, url: str, *, max_retries: int = 2) -> "requests.Response":
        """GET with exponential backoff on transient errors."""
        session = self._get_session()
        last_exc: Optional[Exception] = None
        for attempt in range(1 + max_retries):
            try:
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
            time.sleep(delay)
        raise last_exc  # unreachable, but satisfies type checker

    # ── URL Fetch (Jina Reader) ──

    def fetch(self, url: str) -> str:
        """Fetch URL via Jina Reader → clean markdown."""
        if not HAS_REQUESTS:
            raise WebOpsError("requests not installed")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise WebOpsError(f"Invalid URL scheme: {parsed.scheme}")

        jina_url = self.JINA_PREFIX + url
        try:
            resp = self._request_with_retry(jina_url)
        except requests.RequestException as e:
            raise WebOpsError(f"Jina fetch failed: {e}")

        text = resp.text.strip()
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return self._truncate(text, url)

    # ── Web Search ──

    def search(self, query: str, max_results: int = 5, domains: Optional[List[str]] = None) -> str:
        """Search web: Tavily (if key set) → DuckDuckGo (free default)."""
        query = clean_search_query(query)
        # Normalize domains once at entry point
        normalized_domains = [str(d).strip().lower() for d in (domains or []) if str(d).strip()]
        if self._tavily:
            return self._search_tavily(query, max_results, domains=normalized_domains)
        if HAS_DDG:
            return self._search_ddg(query, max_results, domains=normalized_domains)
        raise WebOpsError("No search backend. Install: pip install ddgs")

    def _search_ddg(self, query: str, max_results: int, domains: Optional[List[str]] = None) -> str:
        """DuckDuckGo search — free, no API key, with retry."""
        effective_query = query
        if domains:
            domain_filter = " OR ".join(f"site:{d}" for d in domains)
            effective_query = f"({query}) ({domain_filter})"

        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                ddgs = DDGS()
                results = list(ddgs.text(effective_query, max_results=max_results))
                break
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    time.sleep(2 ** attempt)
        else:
            raise WebOpsError(f"DuckDuckGo search failed: {last_exc}")

        if domains:
            results = self._filter_results_by_domains(results, domains)

        return self._format_ddg_results(query, results)

    def _search_tavily(self, query: str, max_results: int, domains: Optional[List[str]] = None) -> str:
        """Tavily search — AI-optimized, needs API key."""
        try:
            kwargs = {
                "query": query,
                "max_results": max_results,
                "include_answer": True,
            }
            normalized_domains = [d.strip() for d in (domains or []) if str(d).strip()]
            if normalized_domains:
                kwargs["include_domains"] = normalized_domains
            result = self._tavily.search(**kwargs)
        except Exception as e:
            raise WebOpsError(f"Tavily search failed: {e}")

        if domains and isinstance(result, dict):
            result["results"] = self._filter_results_by_domains(result.get("results", []), domains, tavily=True)

        return self._format_tavily_results(query, result)

    @staticmethod
    def _filter_results_by_domains(results, domains: List[str], tavily: bool = False):
        if not domains:
            return results

        filtered = []
        for item in results:
            url = ""
            if tavily and isinstance(item, dict):
                url = str(item.get("url", ""))
            elif isinstance(item, dict):
                url = str(item.get("href", ""))
            if not url:
                continue

            host = urlparse(url).netloc.lower()
            host = host[4:] if host.startswith("www.") else host
            if any(host == domain or host.endswith(f".{domain}") for domain in domains):
                filtered.append(item)
        return filtered

    # ── Formatters ──

    @staticmethod
    def _format_ddg_results(query: str, results: list) -> str:
        lines = [f"Search: {query}\n"]
        if not results:
            lines.append("No results found.")
            return "\n".join(lines)
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("href", "")
            body = r.get("body", "")
            if len(body) > 500:
                body = body[:500] + "..."
            lines.append(f"{i}. [{title}]({url})")
            if body:
                lines.append(f"   {body}\n")
        return "\n".join(lines)

    @staticmethod
    def _format_tavily_results(query: str, result: dict) -> str:
        lines = [f"Search: {query}\n"]
        answer = result.get("answer")
        if answer:
            lines.append(f"**Summary:** {answer}\n")
        for i, r in enumerate(result.get("results", []), 1):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("content", "")
            if len(snippet) > 500:
                snippet = snippet[:500] + "..."
            lines.append(f"{i}. [{title}]({url})")
            if snippet:
                lines.append(f"   {snippet}\n")
        if not result.get("results") and not answer:
            lines.append("No results found.")
        return "\n".join(lines)

    # ── Helpers ──

    def _truncate(self, text: str, url: str) -> str:
        if len(text) > self.MAX_CONTENT_LENGTH:
            text = text[:self.MAX_CONTENT_LENGTH] + "\n\n... (truncated)"
        return f"URL: {url}\n\n{text}"
