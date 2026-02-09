"""Shell command execution with safety guards."""

import base64
import os
import re
import subprocess
from collections import deque
from pathlib import Path

from ..logger import get_logger

_log = get_logger(__name__)


class ShellExecutor:
    """Execute shell commands while blocking dangerous or obfuscated payloads."""

    # Regex signatures for high-risk commands and common exploit chains.
    DANGEROUS_PATTERNS = [
        r"\brm\b\s+-[^\s;|&]*r[^\s;|&]*f[^\s;|&]*\b",
        r"\b(?:mkfs(?:\.[a-z0-9_+\-]+)?|fdisk|parted|sfdisk|wipefs|format)\b",
        r"\bdd\b[^\n;|&]*\bif\s*=",
        r"\bchmod\b\s+(?:-[^\s]+\s+)?0?777\b",
        r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
        r"(?:>|>>)\s*/dev/sd[a-z]\d*",
        r"\b(?:of|if)\s*=\s*/dev/sd[a-z]\d*",
        r"\bcurl\b[^\n;|&]*\|\s*(?:sh|bash|zsh|ksh)\b",
        r"\bwget\b[^\n;|&]*\|\s*(?:sh|bash|zsh|ksh)\b",
        r"\bpython(?:\d+(?:\.\d+)?)?\b[^\n;|&]*-c\b[^\n;|&]*os\.system",
        r"\beval\b\s+",
        r"\bbase64\b[^\n;|&]*-(?:d|decode)\b[^\n;|&]*\|\s*(?:sh|bash|zsh|ksh)\b",
    ]

    _BASE64_DECODE_RE = re.compile(
        r"\bbase64\b[^\n;|&]*-(?:d|decode)\b", re.IGNORECASE
    )
    _BASE64_BLOB_RE = re.compile(
        r"(?<![A-Za-z0-9+/=])([A-Za-z0-9+/]{16,}={0,2})(?![A-Za-z0-9+/=])"
    )
    _VAR_ASSIGN_RE = re.compile(
        r"(?:^|[\s;|&()])([A-Za-z_][A-Za-z0-9_]*)"
        r"=("  # Value can be unquoted, single-quoted, or double-quoted.
        r"'[^']*'"
        r"|\"(?:[^\"\\]|\\.)*\""
        r"|[^\s;|&]+"
        r")"
    )
    _VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
    _MAX_ANALYSIS_DEPTH = 3

    def __init__(self, project_root: str, blocked_commands: list = None, timeout: int = 30):
        self.project_root = Path(project_root).resolve()
        self.timeout = timeout
        self.blocked = blocked_commands or []
        self._dangerous_regexes = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.DANGEROUS_PATTERNS
        ]
        self._blocked_rules = [
            self._build_block_rule(blocked) for blocked in self.blocked if blocked.strip()
        ]

    @staticmethod
    def _canonicalize_command(command: str) -> str:
        """Normalize shell syntax noise so obfuscated variants are easier to match."""
        normalized = command.lower().replace("\\\n", " ")
        normalized = re.sub(r"\$\{?\s*ifs\s*\}?", " ", normalized)
        normalized = re.sub(r"[\'\"`\\]", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @staticmethod
    def _build_flexible_regex(blocked: str) -> re.Pattern:
        """Build a regex that tolerates simple quote/escape based obfuscation."""
        text = blocked.strip()
        parts = []

        for char in text:
            if char.isspace():
                parts.append(r"(?:\s+|\$\{?ifs\}?)+")
                continue
            if char in "|&;<>":
                parts.append(r"\s*" + re.escape(char) + r"\s*")
                continue
            if char.isalnum():
                parts.append(re.escape(char) + r"(?:['\"`\\]*)")
            else:
                parts.append(re.escape(char))

        pattern = "".join(parts)
        if text and text[0].isalnum():
            pattern = r"\b" + pattern
        if text and text[-1].isalnum():
            pattern = pattern + r"\b"
        return re.compile(pattern, re.IGNORECASE)

    def _build_block_rule(self, blocked: str) -> dict:
        canonical = self._canonicalize_command(blocked)
        compact = re.sub(r"\s+", "", canonical)
        return {
            "raw": blocked,
            "raw_lower": blocked.lower().strip(),
            "canonical": canonical,
            "compact": compact,
            "regex": self._build_flexible_regex(blocked),
        }

    @staticmethod
    def _unquote_literal(value: str) -> str:
        """Return a best-effort literal representation for a shell variable value."""
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")

    @classmethod
    def _extract_variable_assignments(cls, command: str) -> dict:
        """Extract simple literal assignments (e.g. a='rm', b=-rf) for static expansion."""
        assignments = {}

        for match in cls._VAR_ASSIGN_RE.finditer(command):
            name = match.group(1)
            raw_value = match.group(2).strip()
            value = cls._unquote_literal(raw_value)

            # Keep only safe, literal-like values to avoid speculative expansion.
            if not value or len(value) > 256:
                continue
            if any(ch in value for ch in ("$", "`", "(", ")", ";", "|", "&")):
                continue

            assignments[name] = value

        return assignments

    @classmethod
    def _expand_simple_variables(cls, command: str, assignments: dict) -> str:
        """Resolve direct $var/${var} references from known literal assignments."""
        if not assignments:
            return command

        expanded = command
        for _ in range(3):
            changed = False

            def _replace(match: re.Match) -> str:
                nonlocal changed
                var_name = match.group(1) or match.group(2)
                if var_name in assignments:
                    changed = True
                    return assignments[var_name]
                return match.group(0)

            expanded = cls._VAR_REF_RE.sub(_replace, expanded)
            if not changed:
                break

        return expanded

    @staticmethod
    def _extract_backtick_subcommands(command: str) -> list:
        subcommands = []
        in_backticks = False
        escape = False
        current = []

        for char in command:
            if escape:
                if in_backticks:
                    current.append(char)
                escape = False
                continue

            if char == "\\":
                escape = True
                continue

            if char == "`":
                if in_backticks:
                    fragment = "".join(current).strip()
                    if fragment:
                        subcommands.append(fragment)
                    current = []
                    in_backticks = False
                else:
                    in_backticks = True
                    current = []
                continue

            if in_backticks:
                current.append(char)

        return subcommands

    @classmethod
    def _extract_dollar_subcommands(cls, command: str) -> list:
        """Extract nested command substitutions from $(...)."""
        subcommands = []
        i = 0
        length = len(command)

        while i < length - 1:
            if command[i] == "\\":
                i += 2
                continue

            if command[i] == "$" and command[i + 1] == "(":
                start = i + 2
                depth = 1
                i += 2

                while i < length:
                    char = command[i]
                    if char == "\\":
                        i += 2
                        continue
                    if char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                        if depth == 0:
                            fragment = command[start:i].strip()
                            if fragment:
                                subcommands.append(fragment)
                                subcommands.extend(cls._extract_dollar_subcommands(fragment))
                            break
                    i += 1
            else:
                i += 1

        return subcommands

    @staticmethod
    def _extract_eval_payloads(command: str) -> list:
        payloads = []
        for match in re.finditer(r"\beval\b\s+([^\n]+)", command, flags=re.IGNORECASE):
            fragment = match.group(1).strip()
            if fragment:
                payloads.append(fragment)
        return payloads

    @classmethod
    def _decode_base64_payloads(cls, command: str) -> list:
        """Best-effort decode for commands that include base64 -d/--decode pipelines."""
        if not cls._BASE64_DECODE_RE.search(command):
            return []

        decoded_payloads = []
        for match in cls._BASE64_BLOB_RE.finditer(command):
            token = match.group(1)
            if len(token) % 4 != 0:
                continue

            try:
                decoded_bytes = base64.b64decode(token, validate=True)
            except Exception:
                continue

            if not decoded_bytes:
                continue

            decoded_text = decoded_bytes[:4096].decode("utf-8", errors="ignore").strip()
            if not decoded_text:
                continue

            printable_chars = sum(
                char.isprintable() or char in "\n\r\t" for char in decoded_text
            )
            if printable_chars / len(decoded_text) < 0.75:
                continue

            decoded_payloads.append(decoded_text)

        return decoded_payloads

    def _collect_fragments(self, command: str) -> list:
        """Collect raw and derived command fragments so bypass tricks can be inspected."""
        queue = deque([("command", command, 0)])
        fragments = []
        seen = set()

        while queue:
            source, fragment, depth = queue.popleft()
            key = fragment.strip()
            if not key or key in seen:
                continue

            seen.add(key)
            fragments.append((source, fragment))

            if depth >= self._MAX_ANALYSIS_DEPTH:
                continue

            for subcommand in self._extract_backtick_subcommands(fragment):
                queue.append(("backtick substitution", subcommand, depth + 1))
            for subcommand in self._extract_dollar_subcommands(fragment):
                queue.append(("$() substitution", subcommand, depth + 1))
            for payload in self._extract_eval_payloads(fragment):
                queue.append(("eval payload", payload, depth + 1))
            for payload in self._decode_base64_payloads(fragment):
                queue.append(("base64-decoded payload", payload, depth + 1))

            assignments = self._extract_variable_assignments(fragment)
            if assignments:
                expanded = self._expand_simple_variables(fragment, assignments)
                if expanded != fragment:
                    queue.append(("variable expansion", expanded, depth + 1))

        return fragments

    def _match_blocked_rules(self, fragment: str):
        cmd_lower = fragment.lower().strip()
        canonical = self._canonicalize_command(fragment)
        compact = re.sub(r"\s+", "", canonical)

        for rule in self._blocked_rules:
            if rule["raw_lower"] and rule["raw_lower"] in cmd_lower:
                return f"matches blocked command '{rule['raw']}'"
            if rule["canonical"] and rule["canonical"] in canonical:
                return f"matches blocked command '{rule['raw']}'"
            if rule["compact"] and rule["compact"] in compact:
                return f"matches blocked command '{rule['raw']}'"
            if rule["regex"].search(fragment):
                return f"matches blocked command '{rule['raw']}'"

        for pattern in self._dangerous_regexes:
            if pattern.search(fragment):
                return f"matches dangerous pattern '{pattern.pattern}'"

        return None

    def _get_block_reason(self, command: str):
        for source, fragment in self._collect_fragments(command):
            reason = self._match_blocked_rules(fragment)
            if reason:
                return f"{reason} via {source}"
        return None

    def execute(self, command: str) -> str:
        block_reason = self._get_block_reason(command)
        if block_reason:
            _log.warning("Command blocked: %s", block_reason)
            return f"Blocked: {block_reason}"

        _log.debug("Executing command: %s", command[:100])

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.project_root),
                env={**os.environ, "TERM": "dumb"},
            )
        except subprocess.TimeoutExpired:
            return f"Timed out after {self.timeout}s"
        except Exception as e:
            return f"{type(e).__name__}: {e}"

        parts = []
        if result.stdout:
            out = result.stdout
            if len(out) > 8000:
                out = out[:4000] + "\n...(truncated)...\n" + out[-4000:]
            parts.append(out)

        if result.stderr:
            err = result.stderr
            if len(err) > 4000:
                err = err[:2000] + "\n...(truncated)...\n" + err[-2000:]
            parts.append(f"[stderr]\n{err}")

        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")

        output = "\n".join(parts).strip()
        return output if output else "(no output)"
