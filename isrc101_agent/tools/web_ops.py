"""Web operations: fetch URLs and search."""

import re
from typing import Optional
from urllib.parse import urlparse

# Optional dependencies
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


class WebOpsError(Exception):
    pass


class WebOps:
    """Web fetch and search operations."""

    TIMEOUT = 15
    MAX_CONTENT_LENGTH = 100000  # 100KB text limit

    def __init__(self):
        self._session = None

    @property
    def available(self) -> bool:
        return HAS_REQUESTS

    def _get_session(self):
        if self._session is None and HAS_REQUESTS:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "isrc101-agent/1.0 (AI coding assistant)"
            })
        return self._session

    def fetch(self, url: str) -> str:
        """Fetch URL and return text content."""
        if not HAS_REQUESTS:
            raise WebOpsError("requests not installed. Run: pip install requests")

        # Validate URL
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise WebOpsError(f"Invalid URL scheme: {parsed.scheme}")

        try:
            resp = self._get_session().get(url, timeout=self.TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise WebOpsError(f"Fetch failed: {e}")

        content_type = resp.headers.get("content-type", "")

        # Handle HTML
        if "text/html" in content_type:
            return self._extract_text_from_html(resp.text, url)

        # Handle plain text
        if "text/plain" in content_type or "application/json" in content_type:
            text = resp.text[:self.MAX_CONTENT_LENGTH]
            if len(resp.text) > self.MAX_CONTENT_LENGTH:
                text += f"\n... (truncated, {len(resp.text)} total chars)"
            return text

        raise WebOpsError(f"Unsupported content type: {content_type}")

    def _extract_text_from_html(self, html: str, url: str) -> str:
        """Extract readable text from HTML."""
        if HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            # Remove script and style
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        else:
            # Fallback: simple regex
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        # Truncate
        if len(text) > self.MAX_CONTENT_LENGTH:
            text = text[:self.MAX_CONTENT_LENGTH] + "\n... (truncated)"

        return f"URL: {url}\n\n{text}"
