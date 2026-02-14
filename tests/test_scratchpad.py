"""Tests for SharedScratchpad inter-agent knowledge store."""

import time
import threading

import pytest

from isrc101_agent.crew.scratchpad import SharedScratchpad, ScratchEntry
from isrc101_agent.crew.tasks import CrewTask


class TestScratchpadBasics:
    """Write, read, overwrite."""

    def test_write_and_read(self):
        sp = SharedScratchpad()
        sp.write("api_schema", "REST endpoints: /users, /items", "researcher", "t1")
        entry = sp.read("api_schema")
        assert entry is not None
        assert entry.value == "REST endpoints: /users, /items"
        assert entry.author == "researcher"
        assert entry.task_id == "t1"

    def test_read_missing(self):
        sp = SharedScratchpad()
        assert sp.read("nonexistent") is None

    def test_overwrite(self):
        sp = SharedScratchpad()
        sp.write("key", "v1", "a1")
        sp.write("key", "v2", "a2")
        entry = sp.read("key")
        assert entry.value == "v2"
        assert entry.author == "a2"

    def test_write_with_tags(self):
        sp = SharedScratchpad()
        sp.write("findings", "bug found", "researcher", tags=["coder", "tester"])
        entry = sp.read("findings")
        assert set(entry.tags) == {"coder", "tester"}


class TestScratchpadQueryByTags:
    """query_by_tags()."""

    def test_query_matching_tags(self):
        sp = SharedScratchpad()
        sp.write("k1", "v1", "a1", tags=["coder"])
        sp.write("k2", "v2", "a2", tags=["reviewer"])
        sp.write("k3", "v3", "a3", tags=["coder", "tester"])

        results = sp.query_by_tags({"coder"})
        assert len(results) == 2
        keys = {e.key for e in results}
        assert keys == {"k1", "k3"}

    def test_query_no_matches(self):
        sp = SharedScratchpad()
        sp.write("k1", "v1", "a1", tags=["coder"])
        results = sp.query_by_tags({"reviewer"})
        assert len(results) == 0

    def test_query_limit(self):
        sp = SharedScratchpad()
        for i in range(10):
            sp.write(f"k{i}", f"v{i}", "a", tags=["test"])
        results = sp.query_by_tags({"test"}, limit=3)
        assert len(results) == 3

    def test_query_most_recent_first(self):
        sp = SharedScratchpad()
        sp.write("old", "v_old", "a", tags=["x"])
        time.sleep(0.01)
        sp.write("new", "v_new", "a", tags=["x"])
        results = sp.query_by_tags({"x"})
        assert results[0].key == "new"


class TestScratchpadRelevantForTask:
    """get_relevant_for_task()."""

    def test_relevant_from_deps(self):
        sp = SharedScratchpad()
        sp.write("schema", "user table", "researcher", task_id="t1")
        sp.write("other", "unrelated", "researcher", task_id="t99")

        task = CrewTask(
            id="t2", description="Implement", assigned_role="coder",
            depends_on=["t1"],
        )
        result = sp.get_relevant_for_task(task)
        assert "user table" in result
        assert "unrelated" not in result

    def test_relevant_from_role_tag(self):
        sp = SharedScratchpad()
        sp.write("style_guide", "use snake_case", "researcher", tags=["coder"])

        task = CrewTask(
            id="t2", description="Implement", assigned_role="coder",
            depends_on=[],
        )
        result = sp.get_relevant_for_task(task)
        assert "snake_case" in result

    def test_relevant_dedup(self):
        sp = SharedScratchpad()
        sp.write("shared", "data", "a", task_id="t1", tags=["coder"])

        task = CrewTask(
            id="t2", description="Implement", assigned_role="coder",
            depends_on=["t1"],
        )
        result = sp.get_relevant_for_task(task)
        # "shared" should appear only once even though it matches both dep and tag
        assert result.count("[shared]") == 1

    def test_relevant_max_chars(self):
        sp = SharedScratchpad()
        sp.write("big", "x" * 10000, "a", task_id="t1")
        sp.write("small", "y", "a", task_id="t1")

        task = CrewTask(
            id="t2", description="Implement", assigned_role="coder",
            depends_on=["t1"],
        )
        result = sp.get_relevant_for_task(task, max_chars=100)
        # Should be truncated — not both entries
        assert len(result) < 10100

    def test_relevant_empty(self):
        sp = SharedScratchpad()
        task = CrewTask(
            id="t2", description="Implement", assigned_role="coder",
            depends_on=["t1"],
        )
        result = sp.get_relevant_for_task(task)
        assert result == ""

    def test_uses_context_from_over_depends_on(self):
        sp = SharedScratchpad()
        sp.write("dep_data", "from dep", "a", task_id="t1")
        sp.write("ctx_data", "from ctx", "a", task_id="t3")

        task = CrewTask(
            id="t2", description="Implement", assigned_role="coder",
            depends_on=["t1"],
            context_from=["t3"],
        )
        result = sp.get_relevant_for_task(task)
        assert "from ctx" in result
        assert "from dep" not in result


class TestScratchpadThreadSafety:
    """Concurrent access."""

    def test_concurrent_writes(self):
        sp = SharedScratchpad()
        errors = []

        def writer(i):
            try:
                sp.write(f"key-{i}", f"value-{i}", f"agent-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        for i in range(20):
            assert sp.read(f"key-{i}") is not None
