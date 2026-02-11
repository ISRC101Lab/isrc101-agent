from pathlib import Path

from isrc101_agent.tools.file_ops import FileOps


def test_list_directory_large_tree_omits_child_counts(monkeypatch, tmp_path: Path):
    root = tmp_path
    for index in range(6):
        sub = root / f"d{index}"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "f.txt").write_text("hello\n", encoding="utf-8")

    file_ops = FileOps(str(root))

    # Wrap _tree to inflate the count on the first top-level call,
    # triggering the retry path with include_child_counts=False.
    original_tree = FileOps._tree
    calls = [0]

    def _inflated_tree(self, d, lines, prefix, depth, max_depth, include_child_counts=True):
        f, dd = original_tree(self, d, lines, prefix, depth, max_depth, include_child_counts=include_child_counts)
        if depth == 0:
            calls[0] += 1
            if calls[0] == 1:
                return 6000, 20
        return f, dd

    monkeypatch.setattr(FileOps, "_tree", _inflated_tree)

    output = file_ops.list_directory(".", max_depth=3)

    assert "d0/" in output
    assert "d0/ (" not in output


def test_list_directory_small_tree_keeps_child_counts(tmp_path: Path):
    root = tmp_path
    sub = root / "docs"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "guide.md").write_text("x\n", encoding="utf-8")

    file_ops = FileOps(str(root))
    output = file_ops.list_directory(".", max_depth=3)

    assert "docs/ (1)" in output
