"""Git integration: auto-commit, status, log."""
import subprocess
from pathlib import Path
from typing import Optional

class GitOps:
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

    def auto_commit(self, message: Optional[str] = None) -> Optional[str]:
        if not self.available or not self.has_changes():
            return None
        self._run("add", "-A")
        if not message:
            diff_stat = self._run("diff", "--cached", "--stat").stdout.strip()
            message = f"automated changes\n\n{diff_stat}"
        r = self._run("commit", "-m", f"{self.prefix}{message}", "--no-verify")
        if r.returncode != 0:
            return None
        return self._run("rev-parse", "--short", "HEAD").stdout.strip()

    def get_log(self, n: int = 10) -> str:
        if not self.available: return "(not a git repo)"
        return self._run("log", "--oneline", f"-{n}", "--no-decorate").stdout.strip() or "(no commits)"

    def get_current_branch(self) -> str:
        if not self.available: return "(no git)"
        return self._run("branch", "--show-current").stdout.strip() or "(detached HEAD)"
