"""Web operations: Jina Reader (fetch) + DuckDuckGo/Tavily (search).

Jina Reader: prepend https://r.jina.ai/ to any URL → clean markdown, no API key.
DuckDuckGo: free web search, no API key (default).
Tavily: AI-optimized search, optional upgrade when API key is set.
"""

import re
from typing import Optional
from urllib.parse import urlparse

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


class WebOps:
    """Web fetch via Jina Reader, search via DuckDuckGo (free) or Tavily (optional)."""

    JINA_PREFIX = "https://r.jina.ai/"
    TIMEOUT = 30
    MAX_CONTENT_LENGTH = 100000

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
            })
        return self._session

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
            resp = self._get_session().get(jina_url, timeout=self.TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise WebOpsError(f"Jina fetch failed: {e}")

        text = resp.text.strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return self._truncate(text, url)

    # ── Web Search ──

    def search(self, query: str, max_results: int = 5) -> str:
        """Search web: Tavily (if key set) → DuckDuckGo (free default)."""
        if self._tavily:
            return self._search_tavily(query, max_results)
        if HAS_DDG:
            return self._search_ddg(query, max_results)
        raise WebOpsError("No search backend. Install: pip install ddgs")

    def _search_ddg(self, query: str, max_results: int) -> str:
        """DuckDuckGo search — free, no API key."""
        try:
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            raise WebOpsError(f"DuckDuckGo search failed: {e}")
        return self._format_ddg_results(query, results)

    def _search_tavily(self, query: str, max_results: int) -> str:
        """Tavily search — AI-optimized, needs API key."""
        try:
            result = self._tavily.search(
                query=query, max_results=max_results, include_answer=True,
            )
        except Exception as e:
            raise WebOpsError(f"Tavily search failed: {e}")
        return self._format_tavily_results(query, result)

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
            if len(body) > 300:
                body = body[:300] + "..."
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
            if len(snippet) > 300:
                snippet = snippet[:300] + "..."
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
