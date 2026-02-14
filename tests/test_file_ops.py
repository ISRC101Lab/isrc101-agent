"""Tests for file operations performance optimizations."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from isrc101_agent.undo import UndoManager, MAX_UNDO_HISTORY, _FLUSH_INTERVAL
from isrc101_agent.tools.file_ops import FileOps, FileOperationError
from isrc101_agent.diff_utils import apply_unified_diff, DiffApplyError


# ── UndoManager tests ────────────────────────────────────────


class TestUndoBackupContentParam:
    """backup_file() accepts pre-read content to avoid redundant reads."""

    def test_content_passed_skips_disk_read(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("original", encoding="utf-8")

        # Pass content explicitly — should NOT read from disk
        with patch.object(Path, "read_text", wraps=target.read_text) as mock_read:
            undo.backup_file("test.txt", "str_replace", {}, content="original")
            # read_text should not be called by backup_file since we passed content
            mock_read.assert_not_called()

        assert undo._history[-1].content == "original"

    def test_content_none_for_new_file(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))
        undo.backup_file("new.txt", "create_file", {}, content=None)
        assert undo._history[-1].content is None

    def test_sentinel_fallback_reads_disk(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("disk content", encoding="utf-8")

        # Omit content param (uses ... sentinel) — should read from disk
        undo.backup_file("test.txt", "str_replace", {})
        assert undo._history[-1].content == "disk content"


class TestUndoDeferredFlush:
    """History saves are deferred until flush interval or explicit flush."""

    def test_single_op_no_disk_write(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("x", encoding="utf-8")

        undo.backup_file("test.txt", "edit", {}, content="x")
        # With _FLUSH_INTERVAL > 1, single op should not trigger disk write
        assert undo._dirty == 1
        # History file should not exist yet (no flush)
        assert not undo.history_file.exists()

    def test_flush_interval_triggers_save(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))

        for i in range(_FLUSH_INTERVAL):
            undo.backup_file(f"f{i}.txt", "edit", {}, content=f"v{i}")

        # After _FLUSH_INTERVAL operations, should have flushed
        assert undo._dirty == 0
        assert undo.history_file.exists()
        data = json.loads(undo.history_file.read_text())
        assert len(data) == _FLUSH_INTERVAL

    def test_explicit_flush(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))
        undo.backup_file("test.txt", "edit", {}, content="v1")
        assert undo._dirty == 1

        undo.flush()
        assert undo._dirty == 0
        assert undo.history_file.exists()

    def test_flush_noop_when_clean(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))
        undo.flush()  # No ops, should be a no-op
        assert not undo.history_file.exists()

    def test_undo_last_flushes_first(self, tmp_dir):
        undo = UndoManager(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("original", encoding="utf-8")

        undo.backup_file("test.txt", "edit", {}, content="original")
        target.write_text("modified", encoding="utf-8")

        # undo_last should flush before undoing
        result = undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "original"
        # After undo + save, dirty should be 0
        assert undo._dirty == 0


# ── FileOps content cache tests ──────────────────────────────


class TestFileOpsContentCache:
    """mtime-keyed content cache avoids redundant reads."""

    def test_read_cached_returns_content(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("hello", encoding="utf-8")
        fp = ops._resolve("test.txt")

        content = ops._read_cached(fp)
        assert content == "hello"

    def test_read_cached_uses_cache_on_same_mtime(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("hello", encoding="utf-8")
        fp = ops._resolve("test.txt")

        # First read — populates cache
        ops._read_cached(fp)
        # Second read — should use cache (no disk read)
        with patch.object(Path, "read_text") as mock_read:
            result = ops._read_cached(fp)
            mock_read.assert_not_called()
        assert result == "hello"

    def test_read_cached_invalidates_on_mtime_change(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("v1", encoding="utf-8")
        fp = ops._resolve("test.txt")

        ops._read_cached(fp)

        # Modify file (change mtime)
        time.sleep(0.01)
        target.write_text("v2", encoding="utf-8")

        result = ops._read_cached(fp)
        assert result == "v2"

    def test_invalidate_cache_removes_entry(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("hello", encoding="utf-8")
        fp = ops._resolve("test.txt")

        ops._read_cached(fp)
        assert str(fp) in ops._content_cache

        ops._invalidate_cache(fp)
        assert str(fp) not in ops._content_cache


class TestFileOpsNoRedundantReads:
    """File operations should not read the same file multiple times."""

    def test_str_replace_reads_once(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("old text here", encoding="utf-8")

        # Track actual disk reads via the real read_text
        original_read = Path.read_text
        read_count = [0]
        target_str = str(target)

        def counting_read(self, *args, **kwargs):
            if str(self) == target_str:
                read_count[0] += 1
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read):
            ops.str_replace("test.txt", "old text", "new text")

        # Should read exactly once (via _read_cached), not twice
        assert read_count[0] == 1
        assert target.read_text() == "new text here"

    def test_preview_then_apply_reads_once(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("old text here", encoding="utf-8")

        original_read = Path.read_text
        read_count = [0]
        target_str = str(target)

        def counting_read(self, *args, **kwargs):
            if str(self) == target_str:
                read_count[0] += 1
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read):
            # Preview reads it once
            ok, diff = ops.preview_str_replace("test.txt", "old text", "new text")
            assert ok
            # Apply should use cached content — no additional read
            ops.str_replace("test.txt", "old text", "new text")

        # preview reads once (populates cache), str_replace uses cache = 1 total
        assert read_count[0] == 1

    def test_write_file_passes_content_to_backup(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("original", encoding="utf-8")

        original_read = Path.read_text
        read_count = [0]
        target_str = str(target)

        def counting_read(self, *args, **kwargs):
            if str(self) == target_str:
                read_count[0] += 1
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read):
            ops.write_file("test.txt", "new content")

        # Should read exactly once (for backup content)
        assert read_count[0] == 1

    def test_append_file_reads_once(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line1\n", encoding="utf-8")

        original_read = Path.read_text
        read_count = [0]
        target_str = str(target)

        def counting_read(self, *args, **kwargs):
            if str(self) == target_str:
                read_count[0] += 1
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read):
            ops.append_file("test.txt", "line2\n")

        # Should read once (_read_cached), reuse for both backup and append
        assert read_count[0] == 1
        assert target.read_text() == "line1\nline2\n"

    def test_create_file_no_reads(self, tmp_dir):
        ops = FileOps(str(tmp_dir))

        original_read = Path.read_text
        read_count = [0]

        def counting_read(self, *args, **kwargs):
            read_count[0] += 1
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read):
            ops.create_file("new.txt", "content")

        # create_file passes content=None, no reads needed
        assert read_count[0] == 0

    def test_delete_file_reads_once(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("to delete", encoding="utf-8")

        original_read = Path.read_text
        read_count = [0]
        target_str = str(target)

        def counting_read(self, *args, **kwargs):
            if str(self) == target_str:
                read_count[0] += 1
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read):
            ops.delete_file("test.txt")

        # Should read once for backup
        assert read_count[0] == 1
        assert not target.exists()


class TestUndoRoundTrip:
    """Undo still works correctly after optimizations."""

    def test_undo_str_replace(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("hello world", encoding="utf-8")

        ops.str_replace("test.txt", "hello", "goodbye")
        assert target.read_text() == "goodbye world"

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "hello world"

    def test_undo_create_file(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        ops.create_file("new.txt", "content")
        assert (tmp_dir / "new.txt").exists()

        result = ops.undo.undo_last()
        assert "Deleted" in result
        assert not (tmp_dir / "new.txt").exists()

    def test_undo_write_file(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("original", encoding="utf-8")

        ops.write_file("test.txt", "overwritten")
        assert target.read_text() == "overwritten"

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "original"

    def test_undo_append_file(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line1\n", encoding="utf-8")

        ops.append_file("test.txt", "line2\n")
        assert target.read_text() == "line1\nline2\n"

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "line1\n"

    def test_undo_delete_file(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("precious", encoding="utf-8")

        ops.delete_file("test.txt")
        assert not target.exists()

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "precious"


# ── multi_edit tests ──────────────────────────────────────────


class TestMultiEdit:
    def test_basic_multiple_edits(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.py"
        target.write_text("import os\nprint('hello')\nprint('world')\n")

        result = ops.multi_edit("test.py", [
            {"old_str": "import os", "new_str": "import sys"},
            {"old_str": "print('hello')", "new_str": "print('hi')"},
        ])

        assert "2 replacements" in result
        content = target.read_text()
        assert "import sys" in content
        assert "print('hi')" in content
        assert "print('world')" in content

    def test_atomic_failure_no_partial_apply(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line one\nline two\n")

        with pytest.raises(FileOperationError, match="validation failed"):
            ops.multi_edit("test.txt", [
                {"old_str": "line one", "new_str": "LINE ONE"},
                {"old_str": "NONEXISTENT", "new_str": "whatever"},
            ])

        # File should be unchanged
        assert target.read_text() == "line one\nline two\n"

    def test_duplicate_old_str_fails(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("aaa\naaa\n")

        with pytest.raises(FileOperationError, match="appears 2x"):
            ops.multi_edit("test.txt", [
                {"old_str": "aaa", "new_str": "bbb"},
            ])

    def test_empty_edits_fails(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("content")

        with pytest.raises(FileOperationError, match="No edits"):
            ops.multi_edit("test.txt", [])

    def test_missing_field_fails(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("content")

        with pytest.raises(FileOperationError, match="missing 'new_str'"):
            ops.multi_edit("test.txt", [{"old_str": "content"}])

    def test_undo_multi_edit(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("alpha beta gamma")

        ops.multi_edit("test.txt", [
            {"old_str": "alpha", "new_str": "ALPHA"},
            {"old_str": "gamma", "new_str": "GAMMA"},
        ])
        assert target.read_text() == "ALPHA beta GAMMA"

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "alpha beta gamma"

    def test_file_not_found(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        with pytest.raises(FileOperationError, match="File not found"):
            ops.multi_edit("nope.txt", [{"old_str": "a", "new_str": "b"}])


# ── edit_file_lines tests ────────────────────────────────────


class TestEditFileLines:
    def test_insert_line(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line1\nline2\nline3\n")

        result = ops.edit_file_lines("test.txt", [
            {"type": "insert", "line": 2, "content": "inserted\n"},
        ])

        assert "+1/-0" in result
        content = target.read_text()
        lines = content.splitlines()
        assert lines == ["line1", "inserted", "line2", "line3"]

    def test_replace_lines(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line1\nline2\nline3\nline4\n")

        result = ops.edit_file_lines("test.txt", [
            {"type": "replace", "line": 2, "end_line": 3, "content": "replaced\n"},
        ])

        content = target.read_text()
        lines = content.splitlines()
        assert lines == ["line1", "replaced", "line4"]

    def test_delete_lines(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line1\nline2\nline3\n")

        result = ops.edit_file_lines("test.txt", [
            {"type": "delete", "line": 2, "end_line": 2},
        ])

        content = target.read_text()
        lines = content.splitlines()
        assert lines == ["line1", "line3"]

    def test_multiple_operations_bottom_to_top(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("a\nb\nc\nd\ne\n")

        # Delete line 4, insert before line 2 — should work without shift issues
        result = ops.edit_file_lines("test.txt", [
            {"type": "insert", "line": 2, "content": "X\n"},
            {"type": "delete", "line": 4, "end_line": 4},
        ])

        content = target.read_text()
        lines = content.splitlines()
        assert lines == ["a", "X", "b", "c", "e"]

    def test_invalid_line_number(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("one\ntwo\n")

        with pytest.raises(FileOperationError, match="out of range"):
            ops.edit_file_lines("test.txt", [
                {"type": "delete", "line": 5, "end_line": 5},
            ])

    def test_invalid_type(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("content\n")

        with pytest.raises(FileOperationError, match="invalid type"):
            ops.edit_file_lines("test.txt", [
                {"type": "foo", "line": 1},
            ])

    def test_undo_edit_file_lines(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("a\nb\nc\n")

        ops.edit_file_lines("test.txt", [
            {"type": "delete", "line": 2, "end_line": 2},
        ])
        assert target.read_text().splitlines() == ["a", "c"]

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "a\nb\nc\n"

    def test_empty_operations(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("content\n")

        with pytest.raises(FileOperationError, match="No operations"):
            ops.edit_file_lines("test.txt", [])


# ── regex_replace tests ──────────────────────────────────────


class TestRegexReplace:
    def test_basic_regex(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("foo123 bar456 baz789\n")

        result = ops.regex_replace("test.txt", r"\d+", "NUM")
        assert "3 replacement(s)" in result
        assert target.read_text() == "fooNUM barNUM bazNUM\n"

    def test_count_limit(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("aaa bbb aaa bbb aaa\n")

        result = ops.regex_replace("test.txt", "aaa", "XXX", count=2)
        assert "2 replacement(s)" in result
        assert target.read_text() == "XXX bbb XXX bbb aaa\n"

    def test_group_replacement(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("def foo(x):\ndef bar(y):\n")

        result = ops.regex_replace("test.txt", r"def (\w+)\(", r"def renamed_\1(")
        assert "2 replacement(s)" in result
        content = target.read_text()
        assert "def renamed_foo(x):" in content
        assert "def renamed_bar(y):" in content

    def test_case_insensitive_flag(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("Hello HELLO hello\n")

        result = ops.regex_replace("test.txt", "hello", "hi", flags="i")
        assert "3 replacement(s)" in result
        assert target.read_text() == "hi hi hi\n"

    def test_multiline_flag(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("start line1\nstart line2\nother line3\n")

        result = ops.regex_replace("test.txt", r"^start", "BEGIN", flags="m")
        assert "2 replacement(s)" in result
        content = target.read_text()
        assert content == "BEGIN line1\nBEGIN line2\nother line3\n"

    def test_no_match_raises(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("nothing here\n")

        with pytest.raises(FileOperationError, match="not found"):
            ops.regex_replace("test.txt", r"xyz\d+", "replacement")

    def test_invalid_pattern_raises(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("content\n")

        with pytest.raises(FileOperationError, match="Invalid regex"):
            ops.regex_replace("test.txt", r"[invalid", "replacement")

    def test_invalid_flag_raises(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("content\n")

        with pytest.raises(FileOperationError, match="Unknown regex flag"):
            ops.regex_replace("test.txt", "x", "y", flags="z")

    def test_undo_regex_replace(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("old_name = 1\nold_name = 2\n")

        ops.regex_replace("test.txt", "old_name", "new_name")
        assert "new_name = 1" in target.read_text()

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == "old_name = 1\nold_name = 2\n"


# ── apply_diff tests ─────────────────────────────────────────


class TestApplyDiff:
    def test_single_hunk(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line1\nline2\nline3\nline4\n")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,4 +1,4 @@\n"
            " line1\n"
            "-line2\n"
            "+LINE_TWO\n"
            " line3\n"
            " line4\n"
        )

        result = ops.apply_diff("test.txt", diff)
        assert "diff applied" in result
        content = target.read_text()
        assert content == "line1\nLINE_TWO\nline3\nline4\n"

    def test_multi_hunk(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("a\nb\nc\nd\ne\nf\ng\nh\n")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " a\n"
            "-b\n"
            "+B\n"
            " c\n"
            "@@ -6,3 +6,3 @@\n"
            " f\n"
            "-g\n"
            "+G\n"
            " h\n"
        )

        result = ops.apply_diff("test.txt", diff)
        content = target.read_text()
        assert "B" in content
        assert "G" in content
        assert content == "a\nB\nc\nd\ne\nf\nG\nh\n"

    def test_context_mismatch_error(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("line1\nline2\nline3\n")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-WRONG_LINE\n"
            "+replacement\n"
            " line3\n"
        )

        with pytest.raises(FileOperationError, match="context mismatch"):
            ops.apply_diff("test.txt", diff)

    def test_add_lines(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("before\nafter\n")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,2 +1,4 @@\n"
            " before\n"
            "+added1\n"
            "+added2\n"
            " after\n"
        )

        ops.apply_diff("test.txt", diff)
        content = target.read_text()
        assert content == "before\nadded1\nadded2\nafter\n"

    def test_remove_lines(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("keep\nremove1\nremove2\nalso_keep\n")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,4 +1,2 @@\n"
            " keep\n"
            "-remove1\n"
            "-remove2\n"
            " also_keep\n"
        )

        ops.apply_diff("test.txt", diff)
        content = target.read_text()
        assert content == "keep\nalso_keep\n"

    def test_undo_apply_diff(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        original = "a\nb\nc\n"
        target.write_text(original)

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " a\n"
            "-b\n"
            "+B\n"
            " c\n"
        )

        ops.apply_diff("test.txt", diff)
        assert target.read_text() == "a\nB\nc\n"

        result = ops.undo.undo_last()
        assert "Restored" in result
        assert target.read_text() == original

    def test_empty_diff_raises(self, tmp_dir):
        ops = FileOps(str(tmp_dir))
        target = tmp_dir / "test.txt"
        target.write_text("content\n")

        with pytest.raises(FileOperationError, match="No hunks found"):
            ops.apply_diff("test.txt", "not a valid diff")


# ── apply_unified_diff unit tests ────────────────────────────


class TestApplyUnifiedDiff:
    def test_simple_replacement(self):
        content = "line1\nline2\nline3\n"
        diff = (
            "--- a/f\n+++ b/f\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+LINE2\n"
            " line3\n"
        )
        result = apply_unified_diff(content, diff)
        assert result == "line1\nLINE2\nline3\n"

    def test_no_hunks_raises(self):
        with pytest.raises(DiffApplyError, match="No hunks"):
            apply_unified_diff("content\n", "garbage text")

    def test_mismatch_raises(self):
        content = "a\nb\n"
        diff = (
            "--- a/f\n+++ b/f\n"
            "@@ -1,2 +1,2 @@\n"
            " a\n"
            "-WRONG\n"
            "+c\n"
        )
        with pytest.raises(DiffApplyError, match="context mismatch"):
            apply_unified_diff(content, diff)

    def test_file_without_trailing_newline(self):
        content = "line1\nline2"  # no trailing newline
        diff = (
            "--- a/f\n+++ b/f\n"
            "@@ -1,2 +1,2 @@\n"
            " line1\n"
            "-line2\n"
            "+LINE2\n"
        )
        result = apply_unified_diff(content, diff)
        assert result == "line1\nLINE2"
