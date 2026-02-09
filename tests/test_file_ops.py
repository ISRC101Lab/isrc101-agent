import pytest

from isrc101_agent.tools.file_ops import FileOperationError, FileOps


def test_read_file(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("first\nsecond\nthird\n", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    result = ops.read_file("notes.txt")

    assert "-- notes.txt (3 lines) --" in result
    assert "   1 | first" in result
    assert "   2 | second" in result
    assert "   3 | third" in result


def test_read_file_not_found(tmp_path):
    ops = FileOps(str(tmp_path))

    with pytest.raises(FileOperationError, match="File not found: missing.txt"):
        ops.read_file("missing.txt")


def test_create_file(tmp_path):
    ops = FileOps(str(tmp_path))

    message = ops.create_file("new.txt", "hello\nworld")

    assert message == "Created new.txt (2 lines)"
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello\nworld"


def test_create_file_already_exists(tmp_path):
    (tmp_path / "exists.txt").write_text("data", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    with pytest.raises(FileOperationError, match="File exists: exists.txt"):
        ops.create_file("exists.txt", "new")


def test_write_file_overwrite(tmp_path):
    target = tmp_path / "write.txt"
    target.write_text("old", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    message = ops.write_file("write.txt", "new content")

    assert message == "Overwrote write.txt (1 lines)"
    assert target.read_text(encoding="utf-8") == "new content"


def test_str_replace(tmp_path):
    target = tmp_path / "replace.txt"
    target.write_text("before old_value after", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    message = ops.str_replace("replace.txt", "old_value", "new_value")

    assert message == "Edited replace.txt"
    assert target.read_text(encoding="utf-8") == "before new_value after"


def test_str_replace_not_unique(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("dupe\ndupe\n", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    with pytest.raises(FileOperationError, match="String appears 2x"):
        ops.str_replace("duplicate.txt", "dupe", "unique")


def test_delete_file(tmp_path):
    target = tmp_path / "delete_me.txt"
    target.write_text("remove", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    message = ops.delete_file("delete_me.txt")

    assert message == "Deleted delete_me.txt"
    assert not target.exists()


def test_path_traversal_blocked(tmp_path):
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    with pytest.raises(FileOperationError, match="Access denied"):
        ops.read_file("../outside.txt")


def test_list_directory(tmp_path):
    project_dir = tmp_path / "project"
    sub_dir = project_dir / "sub"
    sub_dir.mkdir(parents=True)
    (project_dir / "a.txt").write_text("a", encoding="utf-8")
    (sub_dir / "b.txt").write_text("b", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    output = ops.list_directory("project", max_depth=3)

    assert "project/ (2 files, 1 dirs)" in output
    assert "a.txt" in output
    assert "sub/" in output
    assert "b.txt" in output


def test_search_files(tmp_path):
    (tmp_path / "app.py").write_text("def fn():\n    return \"needle\"\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("needle in docs\n", encoding="utf-8")
    ops = FileOps(str(tmp_path))

    output = ops.search_files("needle")

    assert output.startswith("Found 2 match(es):")
    assert "app.py" in output
    assert "README.md" in output
