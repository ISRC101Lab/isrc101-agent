"""XML/HTML formatter for tool results."""

import re
from typing import Optional
from rich.console import RenderableType
from rich.syntax import Syntax

from .base import Formatter


class XMLFormatter(Formatter):
    """Format XML/HTML content with syntax highlighting."""

    @property
    def priority(self) -> int:
        return 8  # High priority, but lower than JSON

    def can_format(self, content: str, context: dict) -> bool:
        """Detect XML/HTML content."""
        stripped = content.strip()
        if not stripped:
            return False

        # Quick structural check
        if not stripped.startswith('<'):
            return False

        # More thorough XML/HTML validation
        # Check for balanced tags or valid XML/HTML structure
        if re.match(r'<\?xml\s', stripped, re.IGNORECASE):
            return True

        if re.match(r'<!DOCTYPE\s+html', stripped, re.IGNORECASE):
            return True

        # Check for common HTML tags
        html_tags = ['html', 'head', 'body', 'div', 'span', 'p', 'a', 'table', 'form']
        for tag in html_tags:
            if re.search(rf'<{tag}[\s>]', stripped, re.IGNORECASE):
                return True

        # Check for generic XML structure (opening and closing tags)
        # Look for at least one complete tag pair
        if re.search(r'<(\w+)[^>]*>.*?</\1>', stripped, re.DOTALL):
            return True

        # Self-closing tags
        if re.search(r'<\w+[^>]*/>', stripped):
            return True

        return False

    def _detect_language(self, content: str) -> str:
        """Detect if content is HTML or XML."""
        stripped = content.strip().lower()

        if '<!doctype html' in stripped or '<html' in stripped:
            return 'html'

        return 'xml'

    def _try_pretty_print(self, content: str, lang: str) -> str:
        """Attempt to pretty-print XML/HTML."""
        try:
            if lang == 'html':
                # Try to pretty-print HTML
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(content, 'html.parser')
                    return soup.prettify()
                except ImportError:
                    # BeautifulSoup not available, return as-is
                    pass
            elif lang == 'xml':
                # Try to pretty-print XML
                try:
                    import xml.dom.minidom
                    dom = xml.dom.minidom.parseString(content)
                    return dom.toprettyxml(indent="  ")
                except Exception:
                    # If parsing fails, return as-is
                    pass
        except Exception:
            pass

        return content

    def format(self, content: str, context: dict) -> Optional[RenderableType]:
        """Format XML/HTML with syntax highlighting."""
        try:
            lang = self._detect_language(content)

            # Try to pretty-print (optional, falls back to original if it fails)
            formatted_content = self._try_pretty_print(content.strip(), lang)

            # Use Rich Syntax for highlighting
            syntax = Syntax(
                formatted_content,
                lang,
                theme="monokai",
                line_numbers=True,
                word_wrap=False,
                background_color="default"
            )

            return syntax

        except Exception:
            # Fall back to default rendering
            return None
