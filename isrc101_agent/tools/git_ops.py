"""Git integration: auto-commit, status, log."""
import fnmatch
import subprocess
from pathlib import Path
from typing import Optional

from ..logger import get_logger

_log = get_logger(__name__)

class GitOps:
    SENSITIVE_PATTERNS = [
        ".env*",
        "*.key",
        "*.pem",
        "*.p12",
        "*.pfx",
        "*credentials*",
        "*secret*",
        "id_rsa*",
        "id_dsa*",
        "id_ecdsa*",
        "id_ed25519*",
    ]

    def __init__(self, project_root: str, commit_prefix: str = "isrc101: "):
        self.root = Path(project_root).resolve()
        self.prefix = commit_prefix
        self._has_git = (self.root / ".git").exists()

    @property
    def available(self) -> bool:
        return self._has_git

    def _run(self, *args, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + list(args), capture_output=True, text=True,
            cwd=str(self.root), timeout=15, **kwargs,
        )

    def status_short(self) -> str:
        if not self.available: return "(not a git repo)"
        return self._run("status", "--short").stdout.strip() or "(clean)"

    def has_changes(self) -> bool:
        if not self.available: return False
        return bool(self._run("status", "--porcelain").stdout.strip())

    def _is_sensitive_path(self, path: str) -> bool:
        """Return True when a path looks like it may contain secrets."""
        normalized = path.lower()
        filename = Path(path).name.lower()
        for pattern in self.SENSITIVE_PATTERNS:
            lowered_pattern = pattern.lower()
            if (
                fnmatch.fnmatch(normalized, lowered_pattern)
                or fnmatch.fnmatch(filename, lowered_pattern)
            ):
                return True
        return False

    def stage_changed_files(self) -> list[str]:
        """Stage non-sensitive modified and untracked files."""
        if not self.available:
            return []

        modified = self._run("diff", "--name-only").stdout.splitlines()
        untracked = self._run("ls-files", "--others", "--exclude-standard").stdout.splitlines()

        # Keep file order stable while removing duplicates.
        candidates = list(dict.fromkeys([*modified, *untracked]))
        stageable = [path for path in candidates if path and not self._is_sensitive_path(path)]

        if stageable:
            add_result = self._run("add", "--", *stageable)
            if add_result.returncode != 0:
                return []

        return stageable

    def auto_commit(self, message: Optional[str] = None) -> Optional[str]:
        if not self.available or not self.has_changes():
            return None

        staged_files = self.stage_changed_files()
        if not staged_files:
            return None

        if not message:
            diff_stat = self._run("diff", "--cached", "--stat").stdout.strip()
            message = f"automated changes\n\n{diff_stat}"
        r = self._run("commit", "-m", f"{self.prefix}{message}", "--", *staged_files)
        if r.returncode != 0:
            return None
        return self._run("rev-parse", "--short", "HEAD").stdout.strip()

    def get_log(self, n: int = 10) -> str:
        if not self.available: return "(not a git repo)"
        return self._run("log", "--oneline", f"-{n}", "--no-decorate").stdout.strip() or "(no commits)"

    def get_current_branch(self) -> str:
        if not self.available: return "(no git)"
        return self._run("branch", "--show-current").stdout.strip() or "(detached HEAD)"
