"""Session persistence: save and load conversation history."""

import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.tree import Tree

from .config import CONFIG_DIR
from .theme import SUCCESS, INFO, DIM, WARN

SESSIONS_DIR = CONFIG_DIR / "sessions"
EXPORTS_DIR = CONFIG_DIR / "exports"


def _ensure_sessions_dir():
    """Ensure sessions directory exists."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_exports_dir():
    """Ensure exports directory exists."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_session(
    conversation: List[Dict[str, Any]],
    name: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> str:
    """Save conversation to a session file.

    Args:
        conversation: List of conversation messages
        name: Optional session name (auto-generated if not provided)
        metadata: Optional metadata (mode, model, tags, etc.)

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

    # Ensure metadata dict and initialize tags if not present
    if metadata is None:
        metadata = {}
    if "tags" not in metadata:
        metadata["tags"] = []

    data = {
        "name": name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": metadata,
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


def add_session_tag(session_name: str, tag: str) -> bool:
    """Add a tag to a session.

    Args:
        session_name: Session name or filename
        tag: Tag to add

    Returns:
        True if successful, False otherwise
    """
    session_data = load_session(session_name)
    if not session_data:
        return False

    metadata = session_data.get("metadata", {})
    tags = metadata.get("tags", [])

    # Add tag if not already present
    tag = tag.strip().lower()
    if tag and tag not in tags:
        tags.append(tag)
        metadata["tags"] = tags
        session_data["metadata"] = metadata

        # Save back
        filepath = SESSIONS_DIR / session_name
        if not filepath.exists():
            filepath = SESSIONS_DIR / f"{session_name}.json"

        if filepath.exists():
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
            return True

    return False


def get_session_tags(session_name: str) -> List[str]:
    """Get tags for a session.

    Returns:
        List of tags or empty list
    """
    session_data = load_session(session_name)
    if not session_data:
        return []

    return session_data.get("metadata", {}).get("tags", [])


def render_session_timeline(conversation: List[Dict[str, Any]], console: Console):
    """Render a visual timeline of the conversation.

    Args:
        conversation: List of conversation messages
        console: Rich Console for rendering
    """
    tree = Tree(f"[bold {INFO}]Session Timeline[/bold {INFO}]")

    for i, msg in enumerate(conversation):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # Create node based on role
        if role == "user":
            # User message
            preview = content[:60] + "..." if len(content) > 60 else content
            node = tree.add(f"[bold]User:[/bold] {preview}")

        elif role == "assistant":
            # Assistant message - check for tool calls
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                node = tree.add(f"[{SUCCESS}]Assistant (with {len(tool_calls)} tool calls)[/{SUCCESS}]")
                # Add tool calls as children
                for tc in tool_calls[:3]:  # Show first 3
                    tool_name = tc.get("function", {}).get("name", "unknown")
                    node.add(f"[{DIM}]→ Tool: {tool_name}[/{DIM}]")
                if len(tool_calls) > 3:
                    node.add(f"[{DIM}]→ ... and {len(tool_calls) - 3} more[/{DIM}]")
            else:
                # Regular assistant message
                preview = content[:60] + "..." if len(content) > 60 else content
                node = tree.add(f"[{SUCCESS}]Assistant:[/{SUCCESS}] {preview}")

        elif role == "tool":
            # Tool result
            tool_call_id = msg.get("tool_call_id", "")
            result_preview = str(content)[:40] + "..." if len(str(content)) > 40 else str(content)
            tree.add(f"[{DIM}]Tool result: {result_preview}[/{DIM}]")

        elif role == "system":
            tree.add(f"[{WARN}]System: {content[:60]}...[/{WARN}]")

    console.print()
    console.print(tree)


def export_session_markdown(
    session_name: str,
    output_path: Optional[str] = None
) -> Optional[str]:
    """Export a session to Markdown format.

    Args:
        session_name: Session name or filename
        output_path: Optional output path (default: exports/<session>.md)

    Returns:
        Output filepath if successful, None otherwise
    """
    _ensure_exports_dir()

    session_data = load_session(session_name)
    if not session_data:
        return None

    # Determine output path
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = str(EXPORTS_DIR / f"session-{timestamp}.md")

    conversation = session_data.get("conversation", [])
    metadata = session_data.get("metadata", {})
    created_at = session_data.get("created_at", "unknown")
    tags = metadata.get("tags", [])

    # Build Markdown content
    lines = []
    lines.append(f"# Session Export: {session_data.get('name', 'Unnamed')}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- **Created**: {created_at}")
    lines.append(f"- **Messages**: {len(conversation)}")
    if tags:
        lines.append(f"- **Tags**: {', '.join(tags)}")
    lines.append(f"- **Model**: {metadata.get('model', 'unknown')}")
    lines.append(f"- **Mode**: {metadata.get('mode', 'unknown')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Conversation")
    lines.append("")

    # Format conversation
    for i, msg in enumerate(conversation, 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "user":
            lines.append(f"### Message {i}: User")
            lines.append("")
            lines.append(content)
            lines.append("")

        elif role == "assistant":
            lines.append(f"### Message {i}: Assistant")
            lines.append("")

            # Check for tool calls
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                lines.append("**Tool Calls:**")
                lines.append("")
                for tc in tool_calls:
                    tool_name = tc.get("function", {}).get("name", "unknown")
                    tool_args = tc.get("function", {}).get("arguments", "{}")
                    lines.append(f"- `{tool_name}`: {tool_args[:100]}...")
                lines.append("")

            if content:
                lines.append(content)
                lines.append("")

        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            lines.append(f"**Tool Result** (ID: `{tool_call_id}`)")
            lines.append("")
            lines.append("```")
            # Truncate very long results
            result_str = str(content)
            if len(result_str) > 1000:
                lines.append(result_str[:1000] + "\n... (truncated)")
            else:
                lines.append(result_str)
            lines.append("```")
            lines.append("")

        elif role == "system":
            lines.append(f"**System**: {content}")
            lines.append("")

    # Write to file
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return output_path
    except IOError:
        return None


def search_sessions(keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search sessions by keyword in conversation content.

    Args:
        keyword: Search keyword
        limit: Maximum results to return

    Returns:
        List of matching session summaries with context
    """
    _ensure_sessions_dir()

    keyword_lower = keyword.lower()
    results = []

    for filepath in sorted(SESSIONS_DIR.glob("*.json"),
                           key=lambda p: p.stat().st_mtime,
                           reverse=True):
        if len(results) >= limit:
            break

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            conversation = data.get("conversation", [])
            matches = []

            # Search in conversation
            for i, msg in enumerate(conversation):
                content = str(msg.get("content", ""))
                if keyword_lower in content.lower():
                    # Extract context (50 chars before and after)
                    idx = content.lower().find(keyword_lower)
                    start = max(0, idx - 50)
                    end = min(len(content), idx + len(keyword) + 50)
                    context = content[start:end]
                    if start > 0:
                        context = "..." + context
                    if end < len(content):
                        context = context + "..."
                    matches.append({
                        "message_index": i,
                        "role": msg.get("role", "unknown"),
                        "context": context
                    })

            if matches:
                results.append({
                    "filename": filepath.name,
                    "name": data.get("name", filepath.stem),
                    "created_at": data.get("created_at", "unknown"),
                    "matches": len(matches),
                    "first_match": matches[0]
                })

        except (json.JSONDecodeError, IOError):
            continue

    return results


def list_sessions_enhanced(limit: int = 10) -> List[Dict[str, Any]]:
    """List recent sessions with enhanced information (tags, tokens, etc.).

    Returns:
        List of session summaries with metadata
    """
    _ensure_sessions_dir()

    sessions = []
    for filepath in sorted(SESSIONS_DIR.glob("*.json"),
                           key=lambda p: p.stat().st_mtime,
                           reverse=True)[:limit]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            metadata = data.get("metadata", {})
            conversation = data.get("conversation", [])

            # Calculate approximate tokens (rough estimate)
            total_chars = sum(len(str(msg.get("content", ""))) for msg in conversation)
            approx_tokens = total_chars // 4

            sessions.append({
                "filename": filepath.name,
                "name": data.get("name", filepath.stem),
                "created_at": data.get("created_at", "unknown"),
                "messages": len(conversation),
                "tags": metadata.get("tags", []),
                "model": metadata.get("model", "unknown"),
                "mode": metadata.get("mode", "unknown"),
                "approx_tokens": approx_tokens,
            })
        except (json.JSONDecodeError, IOError):
            continue

    return sessions
