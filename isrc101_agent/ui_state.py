"""UI state persistence — remember user preferences and usage patterns."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from .config import CONFIG_DIR

UI_STATE_FILE = CONFIG_DIR / "ui_state.json"


class UIStateManager:
    """Manage UI state and command usage statistics."""

    def __init__(self, project_root: Optional[str] = None):
        """Initialize UI state manager.

        Args:
            project_root: Current project directory (for per-project settings)
        """
        self.project_root = str(Path(project_root).resolve()) if project_root else None
        self.state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load UI state from disk."""
        if not UI_STATE_FILE.exists():
            return self._default_state()

        try:
            with open(UI_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure all required sections exist
                for key in ["version", "global", "projects", "command_stats", "preferences"]:
                    if key not in data:
                        data[key] = self._default_state()[key]
                return data
        except (json.JSONDecodeError, IOError):
            return self._default_state()

    def _default_state(self) -> Dict[str, Any]:
        """Return default UI state structure."""
        return {
            "version": "1.0",
            "global": {
                "theme": "github_dark",
                "use_unicode": True,
                "reasoning_display": "summary",
                "web_display": "brief",
            },
            "projects": {},
            "command_stats": {},
            "preferences": {
                "truncation_mode": "auto",
                "display_file_tree": "auto",
            },
        }

    def save(self):
        """Save UI state to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        try:
            with open(UI_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except IOError:
            pass  # Silently fail on save errors

    def get_global_setting(self, key: str, default: Any = None) -> Any:
        """Get a global setting."""
        return self.state.get("global", {}).get(key, default)

    def set_global_setting(self, key: str, value: Any):
        """Set a global setting and save."""
        if "global" not in self.state:
            self.state["global"] = {}
        self.state["global"][key] = value
        self.save()

    def get_project_setting(self, key: str, default: Any = None) -> Any:
        """Get a project-specific setting (falls back to global)."""
        if not self.project_root:
            return self.get_global_setting(key, default)

        project_settings = self.state.get("projects", {}).get(self.project_root, {})
        if key in project_settings:
            return project_settings[key]

        return self.get_global_setting(key, default)

    def set_project_setting(self, key: str, value: Any):
        """Set a project-specific setting and save."""
        if not self.project_root:
            self.set_global_setting(key, value)
            return

        if "projects" not in self.state:
            self.state["projects"] = {}

        if self.project_root not in self.state["projects"]:
            self.state["projects"][self.project_root] = {}

        self.state["projects"][self.project_root][key] = value
        self.save()

    def record_command_usage(self, command: str):
        """Record that a command was used (for statistics and autocomplete ordering).

        Args:
            command: The command that was used (e.g., "/model", "/theme")
        """
        if "command_stats" not in self.state:
            self.state["command_stats"] = {}

        stats = self.state["command_stats"]

        if command not in stats:
            stats[command] = {
                "count": 0,
                "last_used": None,
            }

        stats[command]["count"] += 1
        stats[command]["last_used"] = datetime.now().isoformat()

        self.save()

    def get_command_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get all command usage statistics."""
        return self.state.get("command_stats", {})

    def get_top_commands(self, limit: int = 10) -> List[tuple[str, int]]:
        """Get most frequently used commands.

        Args:
            limit: Maximum number of commands to return

        Returns:
            List of (command, count) tuples sorted by usage count
        """
        stats = self.get_command_stats()

        sorted_commands = sorted(
            stats.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )

        return [(cmd, data["count"]) for cmd, data in sorted_commands[:limit]]

    def get_recent_commands(self, limit: int = 10) -> List[str]:
        """Get most recently used commands.

        Args:
            limit: Maximum number of commands to return

        Returns:
            List of command names sorted by last used time
        """
        stats = self.get_command_stats()

        # Filter out commands without last_used timestamp
        with_timestamps = [
            (cmd, data["last_used"])
            for cmd, data in stats.items()
            if data.get("last_used")
        ]

        sorted_commands = sorted(
            with_timestamps,
            key=lambda x: x[1],
            reverse=True
        )

        return [cmd for cmd, _ in sorted_commands[:limit]]

    def get_command_priority_score(self, command: str) -> float:
        """Calculate priority score for command autocomplete ordering.

        Commands with higher scores should appear first in autocomplete.
        Score is based on:
        - Usage frequency (count)
        - Recency (last_used)

        Args:
            command: Command name

        Returns:
            Priority score (higher = more priority)
        """
        stats = self.get_command_stats()

        if command not in stats:
            return 0.0

        data = stats[command]
        count = data.get("count", 0)
        last_used = data.get("last_used")

        # Base score from usage count
        score = float(count) * 10.0

        # Recency bonus (commands used in last 24 hours get a boost)
        if last_used:
            try:
                last_time = datetime.fromisoformat(last_used)
                now = datetime.now()
                hours_ago = (now - last_time).total_seconds() / 3600

                # Recency bonus: 100 points if used in last hour, decaying over 24 hours
                if hours_ago < 24:
                    recency_bonus = max(0, 100 * (1 - hours_ago / 24))
                    score += recency_bonus
            except (ValueError, TypeError):
                pass

        return score

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        return self.state.get("preferences", {}).get(key, default)

    def set_preference(self, key: str, value: Any):
        """Set a user preference and save."""
        if "preferences" not in self.state:
            self.state["preferences"] = {}
        self.state["preferences"][key] = value
        self.save()

    def get_stats_summary(self) -> Dict[str, Any]:
        """Get summary of UI state statistics for display.

        Returns:
            Dict with various statistics
        """
        stats = self.get_command_stats()
        total_commands = sum(data["count"] for data in stats.values())
        unique_commands = len(stats)

        top_commands = self.get_top_commands(10)
        recent_commands = self.get_recent_commands(5)

        return {
            "total_commands_executed": total_commands,
            "unique_commands_used": unique_commands,
            "top_commands": top_commands,
            "recent_commands": recent_commands,
            "projects_tracked": len(self.state.get("projects", {})),
        }
