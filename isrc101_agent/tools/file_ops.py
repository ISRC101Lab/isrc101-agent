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
        self._rg_available: Optional[bool] = None

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

    def append_file(self, path: str, content: str) -> str:
        fp = self._resolve(path)
        if not fp.exists():
            raise FileOperationError(f"File not found: {path}. Use create_file first.")
        self.undo.backup_file(path, "append_file", {"path": path})
        existing = fp.read_text(encoding="utf-8")
        fp.write_text(existing + content, encoding="utf-8")
        total_lines = len((existing + content).splitlines())
        appended_lines = len(content.splitlines())
        return f"Appended {appended_lines} lines to {path} (now {total_lines} lines)"

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

        try:
            rel = fp.relative_to(self.project_root)
        except ValueError:
            rel = fp

        # Lightweight count first (os.walk only, no rendering)
        total_files, total_dirs = self._count_tree_items(fp)

        # Reduce depth for large projects to keep output manageable
        effective_depth = max_depth
        if total_files > 500 and max_depth > 1:
            effective_depth = 1
        elif total_files > 200 and max_depth > 2:
            effective_depth = 2

        # Single render pass at the chosen depth
        lines = []
        include_child_counts = total_files <= 5000
        self._tree(fp, lines, "", 0, effective_depth,
                   include_child_counts=include_child_counts)

        header = f"{rel or '.'}/ ({total_files} files, {total_dirs} dirs)"
        result = [header] + lines

        if path == "." or fp == self.project_root:
            summary = self._project_summary(fp)
            if summary:
                result.append(f"\nProject: {summary}")
        return "\n".join(result)

    def _tree(self, d: Path, lines: list, prefix: str, depth: int, max_depth: int, include_child_counts: bool = True):
        """Render tree lines, return (total_files, total_dirs) for the entire subtree."""
        if depth >= max_depth:
            # Count remaining items without rendering
            f_count = d_count = 0
            for _, dirs, files in os.walk(d):
                dirs[:] = [dd for dd in dirs if dd not in self.SKIP_DIRS and not dd.startswith(".")]
                d_count += len(dirs)
                f_count += len(files)
            return f_count, d_count
        try:
            entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return 0, 0
        entries = [e for e in entries if not e.name.startswith(".") and e.name not in self.SKIP_DIRS]
        total_files = 0
        total_dirs = 0
        for i, entry in enumerate(entries):
            last = i == len(entries) - 1
            conn = "└── " if last else "├── "
            ext_pre = "    " if last else "│   "
            if entry.is_dir():
                total_dirs += 1
                if include_child_counts:
                    children = self._count_children(entry)
                    lines.append(f"{prefix}{conn}{entry.name}/ ({children})")
                else:
                    lines.append(f"{prefix}{conn}{entry.name}/")
                sub_f, sub_d = self._tree(entry, lines, prefix + ext_pre, depth + 1, max_depth, include_child_counts=include_child_counts)
                total_files += sub_f
                total_dirs += sub_d
            else:
                total_files += 1
                sz = self._fmtsize(entry.stat().st_size)
                lines.append(f"{prefix}{conn}{entry.name} ({sz})")
        return total_files, total_dirs

    def _count_tree_items(self, root: Path) -> Tuple[int, int]:
        total_files = total_dirs = 0
        for _, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS and not d.startswith(".")]
            total_dirs += len(dirs)
            total_files += len(files)
        return total_files, total_dirs

    def _count_children(self, entry: Path):
        try:
            return sum(
                1
                for child in entry.iterdir()
                if not child.name.startswith(".") and child.name not in self.SKIP_DIRS
            )
        except PermissionError:
            return "?"

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

    def find_files(self, pattern: str, path: str = ".", max_results: int = 50,
                   progress_callback=None) -> str:
        """Find files by glob pattern, sorted by modification time (newest first).

        Args:
            pattern: Glob pattern (e.g., '*.py', 'test_*.js')
            path: Root directory to search
            max_results: Maximum number of results to return
            progress_callback: Optional callable(current, total) for progress updates
        """
        fp = self._resolve(path)
        if not fp.is_dir():
            raise FileOperationError(f"Not a directory: {path}")

        matches = []
        scanned = 0
        for p in fp.rglob(pattern):
            if any(skip in p.parts for skip in self.SKIP_DIRS):
                continue
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(self.project_root)
                mtime = p.stat().st_mtime
                matches.append((str(rel), mtime))
                scanned += 1
                if progress_callback and scanned % 10 == 0:
                    progress_callback(scanned, None)
            except (ValueError, OSError):
                continue

        matches.sort(key=lambda x: x[1], reverse=True)
        total = len(matches)
        shown = matches[:max_results]

        if not shown:
            return f"No files matching '{pattern}'"

        lines = [str(m[0]) for m in shown]
        result = f"Found {total} file(s)"
        if total > max_results:
            result += f" (showing {max_results})"
        result += f":\n" + "\n".join(lines)
        return result

    def find_symbol(self, name: str, kind: str = "any", path: str = ".") -> str:
        """Search for function/class/variable definitions by name."""
        fp = self._resolve(path)
        patterns = {
            "function": r"(def|function|func|fn|async\s+def|async\s+function)\s+" + name,
            "class": r"(class|struct|interface|enum)\s+" + name,
            "any": r"(def|function|func|fn|async\s+def|async\s+function|class|struct|interface|enum|const|let|var)\s+" + name,
        }
        pat = patterns.get(kind, patterns["any"])

        if self._has_ripgrep():
            cmd = ["rg", "-n", "-H", "--color=never", "--no-heading", "-e", pat]
            for d in self.SKIP_DIRS:
                cmd.extend(["-g", f"!{d}/"])
            cmd.append(str(fp))
        else:
            cmd = ["grep", "-rnHP", "--color=never", "-I", pat]
            for d in self.SKIP_DIRS:
                cmd.extend(["--exclude-dir", d])
            cmd.append(str(fp))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                    cwd=str(self.project_root))
        except subprocess.TimeoutExpired:
            return "Symbol search timed out."

        if result.returncode == 1:
            return f"No definitions found for: {name}"
        if result.returncode != 0:
            return f"Search error: {result.stderr.strip()}"

        return self._format_search_output(result.stdout)

    def search_files(self, pattern: str, path: str = ".", include: Optional[str] = None,
                     context_lines: int = 0, max_results: int = 80) -> str:
        fp = self._resolve(path)
        ctx = max(0, min(context_lines, 5))  # cap at 5

        # Try ripgrep first (much faster), fallback to grep
        if self._has_ripgrep():
            return self._search_with_rg(pattern, fp, include, ctx, max_results)
        return self._search_with_grep(pattern, fp, include, ctx, max_results)

    def _has_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        if self._rg_available is not None:
            return self._rg_available
        try:
            subprocess.run(["rg", "--version"], capture_output=True, timeout=2)
            self._rg_available = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._rg_available = False
        return self._rg_available

    def _search_with_rg(self, pattern: str, fp: Path, include: Optional[str],
                        context_lines: int = 0, max_results: int = 80) -> str:
        """Search using ripgrep (faster)."""
        cmd = ["rg", "-n", "-H", "--color=never", "--no-heading"]

        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])

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

    def _search_with_grep(self, pattern: str, fp: Path, include: Optional[str],
                          context_lines: int = 0, max_results: int = 80) -> str:
        """Search using grep (fallback)."""
        cmd = ["grep", "-rnH", "--color=never", "-I"]

        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])

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

    def _format_search_output(self, stdout: str, max_results: int = 80) -> str:
        """Format search output with round-robin distribution across files."""
        output = stdout.replace(str(self.project_root) + "/", "")
        raw_lines = output.strip().splitlines()
        if not raw_lines:
            return "Found 0 match(es):"

        # Group lines by file for cleaner output
        groups: dict = {}
        for line in raw_lines:
            # rg/grep format: file:line:content or file-line-content (context)
            sep_idx = line.find(":")
            if sep_idx > 0:
                fname = line[:sep_idx]
                groups.setdefault(fname, []).append(line)
            else:
                groups.setdefault("(other)", []).append(line)

        total_matches = len(raw_lines)

        # Round-robin: take 5 lines per file per round until max_results
        result_lines = []
        shown = 0
        per_round = 5
        file_names = list(groups.keys())
        file_offsets = {fname: 0 for fname in file_names}

        while shown < max_results and any(file_offsets[f] < len(groups[f]) for f in file_names):
            for fname in file_names:
                if shown >= max_results:
                    break
                offset = file_offsets[fname]
                file_lines = groups[fname]
                if offset >= len(file_lines):
                    continue

                # Add file header if this is the first batch from this file
                if offset == 0:
                    result_lines.append(f"\n── {fname} ({len(file_lines)} matches) ──")

                # Take up to per_round lines from this file
                batch_end = min(offset + per_round, len(file_lines), offset + (max_results - shown))
                for i in range(offset, batch_end):
                    result_lines.append(file_lines[i])
                    shown += 1
                    if shown >= max_results:
                        break

                file_offsets[fname] = batch_end

        header = f"Found {total_matches} match(es) in {len(groups)} file(s)"
        if total_matches > max_results:
            header += f" (showing {max_results})"
        return header + ":" + "\n".join(result_lines)

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
