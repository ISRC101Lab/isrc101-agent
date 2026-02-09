"""Web operations: fetch URLs with smart content extraction."""

import re
from urllib.parse import urlparse

# Optional dependencies — graceful degradation
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import html2text as _h2t
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False


class WebOpsError(Exception):
    pass


def _make_html2text():
    """Configure html2text for clean markdown output."""
    h = _h2t.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0          # no line wrapping
    h.skip_internal_links = True
    h.inline_links = True
    h.protect_links = True
    h.unicode_snob = True
    return h


class WebOps:
    """Web fetch with trafilatura → html2text → regex fallback chain."""

    TIMEOUT = 15
    MAX_CONTENT_LENGTH = 100000  # 100KB text limit

    def __init__(self):
        self._session = None
        self._h2t = _make_html2text() if HAS_HTML2TEXT else None

    @property
    def available(self) -> bool:
        return HAS_REQUESTS

    def _get_session(self):
        if self._session is None and HAS_REQUESTS:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (compatible; isrc101-agent/1.0; "
                    "+https://github.com/ISRC101Lab/isrc101-agent)"
                ),
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            })
        return self._session

    def fetch(self, url: str) -> str:
        """Fetch URL and return clean markdown content."""
        if not HAS_REQUESTS:
            raise WebOpsError("requests not installed. Run: pip install requests")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise WebOpsError(f"Invalid URL scheme: {parsed.scheme}")

        try:
            resp = self._get_session().get(url, timeout=self.TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise WebOpsError(f"Fetch failed: {e}")

        content_type = resp.headers.get("content-type", "")

        if "text/html" in content_type:
            return self._extract_html(resp.text, url)

        if "text/plain" in content_type or "application/json" in content_type:
            return self._truncate(resp.text, url)

        raise WebOpsError(f"Unsupported content type: {content_type}")

    def _extract_html(self, html: str, url: str) -> str:
        """Extract clean text from HTML using best available method."""
        text = None

        # 1) trafilatura — best for article/doc pages
        if HAS_TRAFILATURA and text is None:
            text = trafilatura.extract(
                html,
                include_links=True,
                include_formatting=True,
                include_tables=True,
                output_format="markdown",
                favor_precision=False,
                favor_recall=True,
            )

        # 2) html2text — good general HTML→Markdown
        if HAS_HTML2TEXT and not text:
            text = self._h2t.handle(html).strip()

        # 3) regex fallback
        if not text:
            text = self._regex_extract(html)

        # Clean up excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return self._truncate(text, url)

    @staticmethod
    def _regex_extract(html: str) -> str:
        """Last-resort regex HTML stripping."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n", "\n\n", text)
        return text.strip()

    def _truncate(self, text: str, url: str) -> str:
        """Add URL header and truncate if needed."""
        if len(text) > self.MAX_CONTENT_LENGTH:
            text = text[:self.MAX_CONTENT_LENGTH] + "\n\n... (truncated)"
        return f"URL: {url}\n\n{text}"
