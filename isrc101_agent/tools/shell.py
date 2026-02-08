"""Shell command execution with safety guards."""
import subprocess, os
from pathlib import Path

class ShellExecutor:
    def __init__(self, project_root: str, blocked_commands: list = None, timeout: int = 30):
        self.project_root = Path(project_root).resolve()
        self.timeout = timeout
        self.blocked = blocked_commands or []

    def execute(self, command: str) -> str:
        cmd_lower = command.lower().strip()
        for blocked in self.blocked:
            if blocked.lower() in cmd_lower:
                return f"Blocked: matches '{blocked}'"
        try:
            result = subprocess.run(
                ["bash", "-c", command], capture_output=True, text=True,
                timeout=self.timeout, cwd=str(self.project_root),
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
