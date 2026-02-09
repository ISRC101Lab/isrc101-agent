"""File operations: read, create, write, edit, delete, list, search."""

import base64
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict

from ..diff_utils import generate_unified_diff, preview_str_replace, count_changes
from ..undo import UndoManager


class FileOperationError(Exception):
    pass


class FileOps:
    SKIP_DIRS = {
        ".git", ".svn", ".hg", ".venv", "venv", "env",
        "node_modules", "__pycache__", ".mypy_cache",
        ".pytest_cache", ".tox", "dist", "build",
        ".egg-info", ".next", ".nuxt", ".cache",
        "target", "out", "bin", "obj", ".cargo",
    }

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.undo = UndoManager(project_root)

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.project_root / p
        p = p.resolve()
        try:
            p.relative_to(self.project_root)
        except ValueError:
            raise FileOperationError(
                f"Access denied: '{path}' is outside project root ({self.project_root})"
            )
        return p

    def read_file(self, path: str, start_line: Optional[int] = None,
                  end_line: Optional[int] = None) -> str:
        fp = self._resolve(path)
        if not fp.exists():
            raise FileOperationError(f"File not found: {path}")
        if not fp.is_file():
            raise FileOperationError(f"Not a file: {path}")
        try:
            content = fp.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = fp.read_text(encoding="latin-1")
            except Exception:
                raise FileOperationError(f"Cannot read binary file: {path}")

        lines = content.splitlines()
        total = len(lines)
        if start_line is not None or end_line is not None:
            s = max((start_line or 1) - 1, 0)
            e = min(end_line or total, total)
            display = lines[s:e]
            offset = s
        else:
            display = lines
            offset = 0

        numbered = [f"{offset + i + 1:4d} | {l}" for i, l in enumerate(display)]
        rel = fp.relative_to(self.project_root)
        return f"-- {rel} ({total} lines) --\n" + "\n".join(numbered)

    def create_file(self, path: str, content: str) -> str:
        fp = self._resolve(path)
        if fp.exists():
            raise FileOperationError(f"File exists: {path}. Use str_replace or write_file.")
        # Backup before creation (content=None means file didn't exist)
        self.undo.backup_file(path, "create_file", {"path": path})
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"Created {path} ({len(content.splitlines())} lines)"

    def write_file(self, path: str, content: str) -> str:
        fp = self._resolve(path)
        existed = fp.exists()
        # Backup before write
        self.undo.backup_file(path, "write_file", {"path": path})
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        verb = "Overwrote" if existed else "Created"
        return f"{verb} {path} ({len(content.splitlines())} lines)"

    def str_replace(self, path: str, old_str: str, new_str: str) -> str:
        fp = self._resolve(path)
        if not fp.exists():
            raise FileOperationError(f"File not found: {path}")
        content = fp.read_text(encoding="utf-8")
        count = content.count(old_str)
        if count == 0:
            lines = content.splitlines()
            preview = "\n".join(f"  {i+1:4d} | {l}" for i, l in enumerate(lines[:30]))
            raise FileOperationError(
                f"String not found in {path}.\nFirst {min(30, len(lines))} lines:\n{preview}"
            )
        if count > 1:
            raise FileOperationError(
                f"String appears {count}x in {path}. Add context to make unique."
            )
        # Backup before edit
        self.undo.backup_file(path, "str_replace", {"path": path})
        new_content = content.replace(old_str, new_str, 1)
        fp.write_text(new_content, encoding="utf-8")
        return f"Edited {path}"

    def preview_str_replace(self, path: str, old_str: str, new_str: str) -> Tuple[bool, str]:
        """Preview str_replace without applying. Returns (can_apply, diff_or_error)."""
        fp = self._resolve(path)
        if not fp.exists():
            return False, f"File not found: {path}"

        content = fp.read_text(encoding="utf-8")
        count = content.count(old_str)

        if count == 0:
            return False, f"String not found in {path}"
        if count > 1:
            return False, f"String appears {count}x in {path}. Add context to make unique."

        rel_path = str(fp.relative_to(self.project_root))
        diff = preview_str_replace(content, old_str, new_str, rel_path)
        return True, diff

    def preview_write_file(self, path: str, content: str) -> Tuple[bool, str]:
        """Preview write_file without applying. Returns (is_overwrite, diff_or_summary)."""
        fp = self._resolve(path)
        rel_path = str(fp.relative_to(self.project_root)) if fp.exists() else path

        if not fp.exists():
            lines = len(content.splitlines())
            return False, f"New file: {rel_path} ({lines} lines)"

        old_content = fp.read_text(encoding="utf-8")
        diff = generate_unified_diff(old_content, content, rel_path)
        added, removed, _ = count_changes(old_content, content)
        return True, diff

    def delete_file(self, path: str) -> str:
        fp = self._resolve(path)
        if not fp.exists():
            raise FileOperationError(f"Not found: {path}")
        if fp.is_dir():
            raise FileOperationError(f"Is a directory: {path}")
        # Backup before delete
        self.undo.backup_file(path, "delete_file", {"path": path})
        fp.unlink()
        return f"Deleted {path}"

    def list_directory(self, path: str = ".", max_depth: int = 3) -> str:
        fp = self._resolve(path)
        if not fp.exists():
            raise FileOperationError(f"Not found: {path}")
        if not fp.is_dir():
            raise FileOperationError(f"Not a directory: {path}")

        total_files = total_dirs = 0
        for root, dirs, files in os.walk(fp):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS and not d.startswith(".")]
            total_dirs += len(dirs)
            total_files += len(files)

        lines = []
        try:
            rel = fp.relative_to(self.project_root)
        except ValueError:
            rel = fp
        lines.append(f"{rel or '.'}/ ({total_files} files, {total_dirs} dirs)")

        effective_depth = max_depth
        if total_files > 200 and max_depth > 2:
            effective_depth = 2
        elif total_files > 500 and max_depth > 1:
            effective_depth = 1

        self._tree(fp, lines, "", 0, effective_depth)

        if path == "." or fp == self.project_root:
            summary = self._project_summary(fp)
            if summary:
                lines.append(f"\nProject: {summary}")
        return "\n".join(lines)

    def _tree(self, d: Path, lines: list, prefix: str, depth: int, max_depth: int):
        if depth >= max_depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        entries = [e for e in entries if not e.name.startswith(".") and e.name not in self.SKIP_DIRS]
        for i, entry in enumerate(entries):
            last = i == len(entries) - 1
            conn = "└── " if last else "├── "
            ext_pre = "    " if last else "│   "
            if entry.is_dir():
                try:
                    children = sum(1 for _ in entry.iterdir()
                                   if not _.name.startswith(".") and _.name not in self.SKIP_DIRS)
                except PermissionError:
                    children = "?"
                lines.append(f"{prefix}{conn}{entry.name}/ ({children})")
                self._tree(entry, lines, prefix + ext_pre, depth + 1, max_depth)
            else:
                sz = self._fmtsize(entry.stat().st_size)
                lines.append(f"{prefix}{conn}{entry.name} ({sz})")

    def _project_summary(self, root: Path) -> str:
        markers = {
            "package.json": "Node.js", "tsconfig.json": "TypeScript",
            "pyproject.toml": "Python", "setup.py": "Python",
            "Cargo.toml": "Rust", "go.mod": "Go", "pom.xml": "Java/Maven",
            "Makefile": "C/C++ (Make)", "CMakeLists.txt": "C/C++ (CMake)",
            "Dockerfile": "Docker",
        }
        found = []
        for marker, lang in markers.items():
            if (root / marker).exists() and lang not in found:
                found.append(lang)
        return ", ".join(found) if found else ""

    @staticmethod
    def _fmtsize(n: int) -> str:
        for u in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
            n /= 1024
        return f"{n:.1f}TB"

    def search_files(self, pattern: str, path: str = ".", include: Optional[str] = None) -> str:
        fp = self._resolve(path)

        # Try ripgrep first (much faster), fallback to grep
        if self._has_ripgrep():
            return self._search_with_rg(pattern, fp, include)
        return self._search_with_grep(pattern, fp, include)

    def _has_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        try:
            subprocess.run(["rg", "--version"], capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _search_with_rg(self, pattern: str, fp: Path, include: Optional[str]) -> str:
        """Search using ripgrep (faster)."""
        cmd = ["rg", "-n", "-H", "--color=never", "--no-heading"]

        # File type filter
        if include:
            cmd.extend(["-g", include])

        # Skip directories
        for d in self.SKIP_DIRS:
            cmd.extend(["-g", f"!{d}/"])

        cmd.extend([pattern, str(fp)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                    cwd=str(self.project_root))
        except subprocess.TimeoutExpired:
            return "Search timed out."

        if result.returncode == 1:
            return f"No matches for: {pattern}"
        if result.returncode != 0:
            return f"Search error: {result.stderr.strip()}"

        return self._format_search_output(result.stdout)

    def _search_with_grep(self, pattern: str, fp: Path, include: Optional[str]) -> str:
        """Search using grep (fallback)."""
        cmd = ["grep", "-rnH", "--color=never", "-I"]

        if include:
            cmd.extend(["--include", include])

        for d in self.SKIP_DIRS:
            cmd.extend(["--exclude-dir", d])

        cmd.extend([pattern, str(fp)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                                    cwd=str(self.project_root))
        except subprocess.TimeoutExpired:
            return "Search timed out."

        if result.returncode == 1:
            return f"No matches for: {pattern}"
        if result.returncode != 0:
            return f"Search error: {result.stderr.strip()}"

        return self._format_search_output(result.stdout)

    def _format_search_output(self, stdout: str) -> str:
        """Format search output with truncation."""
        output = stdout.replace(str(self.project_root) + "/", "")
        raw_lines = output.strip().splitlines()
        if not raw_lines:
            return "Found 0 match(es):"

        lines = raw_lines

        output = "\n".join(lines)
        if len(lines) > 80:
            output = "\n".join(lines[:80]) + f"\n... ({len(lines) - 80} more)"
        return f"Found {len(lines)} match(es):\n{output}"

    # ── Image support ──────────────────────────────
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB

    def read_image(self, path: str) -> Dict:
        """Read image file and return base64 encoded data for LLM."""
        fp = self._resolve(path)
        if not fp.exists():
            raise FileOperationError(f"Image not found: {path}")

        ext = fp.suffix.lower()
        if ext not in self.IMAGE_EXTENSIONS:
            raise FileOperationError(
                f"Unsupported image format: {ext}. "
                f"Supported: {', '.join(self.IMAGE_EXTENSIONS)}"
            )

        size = fp.stat().st_size
        if size > self.MAX_IMAGE_SIZE:
            raise FileOperationError(
                f"Image too large: {size / 1024 / 1024:.1f}MB "
                f"(max {self.MAX_IMAGE_SIZE / 1024 / 1024:.0f}MB)"
            )

        # Read and encode
        data = fp.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")

        # Determine media type
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        media_type = media_types.get(ext, "image/png")

        return {
            "type": "image",
            "path": path,
            "media_type": media_type,
            "data": b64,
            "size": size,
        }
