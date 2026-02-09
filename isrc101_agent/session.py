"""Session persistence: save and load conversation history."""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from .config import CONFIG_DIR

SESSIONS_DIR = CONFIG_DIR / "sessions"


def _ensure_sessions_dir():
    """Ensure sessions directory exists."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_session(
    conversation: List[Dict[str, Any]],
    name: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> str:
    """Save conversation to a session file.

    Args:
        conversation: List of conversation messages
        name: Optional session name (auto-generated if not provided)
        metadata: Optional metadata (mode, model, etc.)

    Returns:
        Session filename
    """
    _ensure_sessions_dir()

    if not name:
        name = f"session_{int(time.time())}"

    # Sanitize filename
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filename = f"{safe_name}.json"
    filepath = SESSIONS_DIR / filename

    data = {
        "name": name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": metadata or {},
        "conversation": conversation,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filename


def load_session(name: str) -> Optional[Dict[str, Any]]:
    """Load a session by name or filename.

    Returns:
        Session data dict or None if not found
    """
    _ensure_sessions_dir()

    # Try exact filename first
    filepath = SESSIONS_DIR / name
    if not filepath.exists():
        filepath = SESSIONS_DIR / f"{name}.json"

    if not filepath.exists():
        # Search by name prefix
        for f in SESSIONS_DIR.glob("*.json"):
            if f.stem.startswith(name):
                filepath = f
                break

    if not filepath.exists():
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def list_sessions(limit: int = 10) -> List[Dict[str, Any]]:
    """List recent sessions.

    Returns:
        List of session summaries (name, created_at, message_count)
    """
    _ensure_sessions_dir()

    sessions = []
    for filepath in sorted(SESSIONS_DIR.glob("*.json"),
                           key=lambda p: p.stat().st_mtime,
                           reverse=True)[:limit]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                sessions.append({
                    "filename": filepath.name,
                    "name": data.get("name", filepath.stem),
                    "created_at": data.get("created_at", "unknown"),
                    "messages": len(data.get("conversation", [])),
                })
        except (json.JSONDecodeError, IOError):
            continue

    return sessions


def delete_session(name: str) -> bool:
    """Delete a session by name or filename."""
    _ensure_sessions_dir()

    filepath = SESSIONS_DIR / name
    if not filepath.exists():
        filepath = SESSIONS_DIR / f"{name}.json"

    if filepath.exists():
        filepath.unlink()
        return True
    return False
