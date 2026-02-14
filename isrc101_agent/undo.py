"""Undo/Rollback mechanism for file operations."""

import json
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

# Store backups in project .isrc101-undo directory
UNDO_DIR_NAME = ".isrc101-undo"
MAX_UNDO_HISTORY = 50
_FLUSH_INTERVAL = 5  # flush to disk every N operations


@dataclass
class FileBackup:
    """Record of a file state before modification."""
    path: str  # Relative path
    content: Optional[str]  # None if file didn't exist
    timestamp: str
    operation: str  # 'str_replace', 'write_file', 'create_file', 'delete_file'
    tool_args: Dict  # Original tool arguments


class UndoManager:
    """Manages file backups and undo operations."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.undo_dir = self.project_root / UNDO_DIR_NAME
        self.history_file = self.undo_dir / "history.json"
        self._history: List[FileBackup] = []
        self._dirty = 0  # count of unsaved operations
        self._load_history()

    def _ensure_dir(self):
        """Ensure undo directory exists."""
        self.undo_dir.mkdir(parents=True, exist_ok=True)
        # Add to .gitignore if not present
        gitignore = self.project_root / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text()
            if UNDO_DIR_NAME not in content:
                with open(gitignore, "a") as f:
                    f.write(f"\n# isrc101-agent undo history\n{UNDO_DIR_NAME}/\n")

    def _load_history(self):
        """Load undo history from disk."""
        if not self.history_file.exists():
            self._history = []
            return

        try:
            data = json.loads(self.history_file.read_text())
            self._history = [
                FileBackup(**item) for item in data
            ]
        except (json.JSONDecodeError, TypeError):
            self._history = []

    def _save_history(self):
        """Save undo history to disk."""
        self._ensure_dir()
        # Trim old entries
        if len(self._history) > MAX_UNDO_HISTORY:
            self._history = self._history[-MAX_UNDO_HISTORY:]

        data = [asdict(b) for b in self._history]
        self.history_file.write_text(json.dumps(data, indent=2))
        self._dirty = 0

    def _maybe_flush(self):
        """Flush to disk if enough operations have accumulated."""
        if self._dirty >= _FLUSH_INTERVAL:
            self._save_history()

    def flush(self):
        """Explicitly flush pending history to disk."""
        if self._dirty > 0:
            self._save_history()

    def backup_file(self, path: str, operation: str, tool_args: Dict,
                    content: Optional[str] = ...) -> bool:
        """Backup a file before modification.

        Args:
            path: Relative file path within project.
            operation: Operation name (str_replace, write_file, etc.).
            tool_args: Original tool arguments for the operation.
            content: Pre-read file content. Pass explicitly to avoid
                     re-reading the file. Use ``None`` to indicate the
                     file does not exist yet. Omit (sentinel ``...``)
                     to let the manager read it from disk.
        """
        if content is ...:
            # Caller did not supply content — read from disk
            fp = self.project_root / path
            content = None
            if fp.exists() and fp.is_file():
                try:
                    content = fp.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    return False

        backup = FileBackup(
            path=path,
            content=content,
            timestamp=datetime.now().isoformat(),
            operation=operation,
            tool_args=tool_args,
        )
        self._history.append(backup)
        self._dirty += 1
        self._maybe_flush()
        return True

    def undo_last(self) -> Optional[str]:
        """Undo the last file operation. Returns status message."""
        if not self._history:
            return None

        # Flush any pending saves first so on-disk state is consistent
        self.flush()

        backup = self._history.pop()
        fp = self.project_root / backup.path

        try:
            if backup.content is None:
                # File didn't exist before - delete it
                if fp.exists():
                    fp.unlink()
                    result = f"Deleted {backup.path} (was created by {backup.operation})"
                else:
                    result = f"File {backup.path} already doesn't exist"
            else:
                # Restore previous content
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(backup.content, encoding="utf-8")
                result = f"Restored {backup.path} (undid {backup.operation})"

            self._save_history()
            return result
        except Exception as e:
            # Put backup back on failure
            self._history.append(backup)
            return f"Undo failed: {e}"

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get recent undo history."""
        recent = self._history[-limit:] if self._history else []
        return [
            {
                "path": b.path,
                "operation": b.operation,
                "timestamp": b.timestamp[:19],  # Trim microseconds
            }
            for b in reversed(recent)
        ]

    def clear_history(self):
        """Clear all undo history."""
        self._history = []
        if self.undo_dir.exists():
            shutil.rmtree(self.undo_dir)

    @property
    def can_undo(self) -> bool:
        """Check if there's anything to undo."""
        return len(self._history) > 0

    @property
    def undo_count(self) -> int:
        """Number of operations that can be undone."""
        return len(self._history)
