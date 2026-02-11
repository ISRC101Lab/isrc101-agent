"""CSV/Table formatter for tool results."""

import csv
import io
from typing import Optional, List
from rich.console import RenderableType
from rich.table import Table

from .base import Formatter
from ..theme import TEXT, ACCENT, BORDER, DIM


class TableFormatter(Formatter):
    """Format CSV/TSV and tabular data as Rich tables."""

    @property
    def priority(self) -> int:
        return 5  # Medium priority

    def can_format(self, content: str, context: dict) -> bool:
        """Detect CSV/TSV content."""
        stripped = content.strip()
        if not stripped:
            return False

        lines = stripped.splitlines()

        # Need at least 2 lines (header + data)
        if len(lines) < 2:
            return False

        # Check if it looks like tabular data
        # Look for consistent delimiter usage
        first_line = lines[0]

        # Check for common delimiters
        delimiters = [',', '\t', '|']
        for delim in delimiters:
            if delim in first_line:
                # Count delimiter occurrences in first few lines
                counts = [line.count(delim) for line in lines[:min(5, len(lines))]]

                # If delimiter count is consistent and > 0, likely a table
                if len(set(counts)) == 1 and counts[0] > 0:
                    return True

        return False

    def _detect_delimiter(self, content: str) -> str:
        """Detect the delimiter used in the content."""
        # Try common delimiters
        sample = content[:1000]  # Use first 1000 chars as sample

        for delim in ['\t', ',', '|', ';']:
            if delim in sample:
                lines = sample.splitlines()[:3]
                counts = [line.count(delim) for line in lines if line.strip()]
                if len(set(counts)) == 1 and counts[0] > 0:
                    return delim

        return ','  # Default to comma

    def _parse_table(self, content: str, delimiter: str) -> Optional[List[List[str]]]:
        """Parse content as CSV/TSV."""
        try:
            reader = csv.reader(io.StringIO(content), delimiter=delimiter)
            rows = list(reader)
            return rows if rows else None
        except Exception:
            return None

    def _looks_like_header(self, row: List[str]) -> bool:
        """Check if a row looks like a header row."""
        if not row:
            return False

        # Header rows typically have:
        # - No empty cells (or fewer)
        # - Shorter text
        # - No numeric-only cells
        # - Different patterns than data rows

        empty_count = sum(1 for cell in row if not cell.strip())
        if empty_count > len(row) / 2:
            return False

        # Check if any cell is purely numeric (headers usually aren't)
        numeric_count = 0
        for cell in row:
            cell = cell.strip()
            if cell and cell.replace('.', '').replace('-', '').isdigit():
                numeric_count += 1

        # If more than half are numeric, probably not a header
        if numeric_count > len(row) / 2:
            return False

        return True

    def format(self, content: str, context: dict) -> Optional[RenderableType]:
        """Format as a Rich table."""
        try:
            delimiter = self._detect_delimiter(content)
            rows = self._parse_table(content.strip(), delimiter)

            if not rows or len(rows) < 2:
                return None

            # Determine if first row is header
            has_header = self._looks_like_header(rows[0])

            # Create Rich table
            table = Table(
                show_header=has_header,
                header_style=f"bold {ACCENT}",
                border_style=BORDER,
                padding=(0, 1),
                show_lines=False,
            )

            # Add columns
            if has_header:
                headers = rows[0]
                data_rows = rows[1:]
            else:
                # Generate column names
                headers = [f"Col{i+1}" for i in range(len(rows[0]))]
                data_rows = rows
                table.show_header = True  # Show generated headers

            # Add columns to table
            for header in headers:
                table.add_column(header.strip(), style=TEXT, overflow="fold")

            # Add data rows (limit to prevent huge tables)
            max_rows = 100
            displayed_rows = data_rows[:max_rows]

            for row in displayed_rows:
                # Ensure row has same number of columns as headers
                padded_row = row + [''] * (len(headers) - len(row))
                padded_row = padded_row[:len(headers)]
                table.add_row(*[str(cell).strip() for cell in padded_row])

            # Add footer if truncated
            if len(data_rows) > max_rows:
                truncated_count = len(data_rows) - max_rows
                table.caption = f"[{DIM}]... ({truncated_count} more rows)[/{DIM}]"

            return table

        except Exception:
            # Fall back to default rendering
            return None
