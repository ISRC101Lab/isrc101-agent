"""Tests for SharedTokenBudget — especially unlimited mode."""

import threading

import pytest

from isrc101_agent.crew.context import SharedTokenBudget, CrewContext


class TestBudgetUnlimited:
    """Budget with max_tokens=0 or per_agent_limit=0 (unlimited mode)."""

    def test_unlimited_property_zero_max(self):
        b = SharedTokenBudget(max_tokens=0, per_agent_limit=100_000)
        assert b.unlimited is True

    def test_unlimited_property_zero_per_agent(self):
        b = SharedTokenBudget(max_tokens=200_000, per_agent_limit=0)
        assert b.unlimited is True

    def test_unlimited_property_both_zero(self):
        b = SharedTokenBudget(max_tokens=0, per_agent_limit=0)
        assert b.unlimited is True

    def test_not_unlimited(self):
        b = SharedTokenBudget(max_tokens=200_000, per_agent_limit=200_000)
        assert b.unlimited is False

    def test_never_exhausted_when_unlimited(self):
        b = SharedTokenBudget(max_tokens=0, per_agent_limit=0)
        b.consume(999_999_999, "agent-0")
        assert b.is_exhausted() is False
        assert b.is_agent_exhausted("agent-0") is False

    def test_remaining_large_when_unlimited(self):
        b = SharedTokenBudget(max_tokens=0, per_agent_limit=0)
        b.consume(100_000, "agent-0")
        assert b.remaining == 999_999_999


class TestBudgetEnforced:
    """Budget with positive limits."""

    def test_exhaustion(self):
        b = SharedTokenBudget(max_tokens=1000, per_agent_limit=1000)
        b.consume(1000, "agent-0")
        assert b.is_exhausted() is True

    def test_not_exhausted(self):
        b = SharedTokenBudget(max_tokens=1000, per_agent_limit=1000)
        b.consume(500, "agent-0")
        assert b.is_exhausted() is False

    def test_remaining(self):
        b = SharedTokenBudget(max_tokens=1000, per_agent_limit=1000)
        b.consume(300, "agent-0")
        assert b.remaining == 700

    def test_used(self):
        b = SharedTokenBudget(max_tokens=1000, per_agent_limit=1000)
        b.consume(300, "agent-0")
        b.consume(200, "agent-1")
        assert b.used == 500

    def test_agent_used(self):
        b = SharedTokenBudget(max_tokens=1000, per_agent_limit=1000)
        b.consume(300, "agent-0")
        b.consume(200, "agent-1")
        assert b.agent_used("agent-0") == 300
        assert b.agent_used("agent-1") == 200
        assert b.agent_used("agent-2") == 0

    def test_agent_exhausted(self):
        b = SharedTokenBudget(max_tokens=10_000, per_agent_limit=500)
        b.consume(500, "agent-0")
        assert b.is_agent_exhausted("agent-0") is True
        assert b.is_agent_exhausted("agent-1") is False

    def test_global_exhaustion_overrides_agent(self):
        b = SharedTokenBudget(max_tokens=500, per_agent_limit=1000)
        b.consume(500, "agent-0")
        # agent-0 is under per-agent limit but global is exhausted
        assert b.is_agent_exhausted("agent-0") is True


class TestBudgetRoleMultipliers:
    """Role-based budget multipliers."""

    def test_register_agent_with_multiplier(self):
        b = SharedTokenBudget(
            max_tokens=1_000_000,
            per_agent_limit=200_000,
            role_multipliers={"reviewer": 0.4, "coder": 1.0},
        )
        coder_limit = b.register_agent("coder-0", "coder")
        reviewer_limit = b.register_agent("reviewer-0", "reviewer")
        assert coder_limit == 200_000
        assert reviewer_limit == 80_000

    def test_register_agent_unlimited(self):
        b = SharedTokenBudget(max_tokens=0, per_agent_limit=0)
        limit = b.register_agent("agent-0", "coder")
        assert limit == 0

    def test_get_agent_limit(self):
        b = SharedTokenBudget(
            max_tokens=1_000_000,
            per_agent_limit=200_000,
            role_multipliers={"reviewer": 0.4},
        )
        b.register_agent("reviewer-0", "reviewer")
        assert b.get_agent_limit("reviewer-0") == 80_000
        # Unregistered agent gets default
        assert b.get_agent_limit("unknown") == 200_000


class TestBudgetWarnings:
    """Threshold-based warning notifications."""

    def test_check_warnings_crosses_threshold(self):
        b = SharedTokenBudget(max_tokens=1_000_000, per_agent_limit=1000)
        b.register_agent("a", "coder")
        b.consume(500, "a")
        result = b.check_warnings("a", [50, 75, 90])
        assert result == 50

    def test_check_warnings_not_crossed(self):
        b = SharedTokenBudget(max_tokens=1_000_000, per_agent_limit=1000)
        b.register_agent("a", "coder")
        b.consume(100, "a")
        result = b.check_warnings("a", [50, 75, 90])
        assert result is None

    def test_check_warnings_no_double_warn(self):
        b = SharedTokenBudget(max_tokens=1_000_000, per_agent_limit=1000)
        b.register_agent("a", "coder")
        b.consume(500, "a")
        b.check_warnings("a", [50, 75, 90])
        # Same threshold should not fire again
        b.consume(10, "a")
        result = b.check_warnings("a", [50, 75, 90])
        assert result is None

    def test_check_warnings_unlimited_returns_none(self):
        b = SharedTokenBudget(max_tokens=0, per_agent_limit=0)
        b.register_agent("a", "coder")
        b.consume(999_999, "a")
        result = b.check_warnings("a", [50, 75, 90])
        assert result is None

    def test_check_warnings_empty_thresholds(self):
        b = SharedTokenBudget(max_tokens=1_000_000, per_agent_limit=1000)
        b.register_agent("a", "coder")
        b.consume(900, "a")
        result = b.check_warnings("a", [])
        assert result is None


class TestBudgetReallocation:
    """Budget reallocation from finished agents."""

    def test_reallocate_from(self):
        b = SharedTokenBudget(max_tokens=1_000_000, per_agent_limit=200_000)
        b.register_agent("a", "coder")
        b.consume(50_000, "a")
        reclaimed = b.reallocate_from("a")
        assert reclaimed == 150_000
        # Global budget should be increased
        assert b.max_tokens == 1_150_000

    def test_reallocate_fully_used(self):
        b = SharedTokenBudget(max_tokens=1_000_000, per_agent_limit=200_000)
        b.register_agent("a", "coder")
        b.consume(200_000, "a")
        reclaimed = b.reallocate_from("a")
        assert reclaimed == 0


class TestBudgetThreadSafety:
    """Concurrent access to SharedTokenBudget."""

    def test_concurrent_consume(self):
        b = SharedTokenBudget(max_tokens=0, per_agent_limit=0)
        threads = []
        for i in range(10):
            t = threading.Thread(target=lambda: b.consume(100, f"agent-{i}"))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert b.used == 1000


class TestCrewContext:
    """CrewContext result accumulation."""

    def test_add_and_get_result(self):
        ctx = CrewContext()
        ctx.add_result("t1", "result 1")
        ctx.add_result("t2", "result 2")
        text = ctx.get_context_for(["t1"])
        assert "result 1" in text
        assert "result 2" not in text

    def test_get_context_multiple(self):
        ctx = CrewContext()
        ctx.add_result("t1", "r1")
        ctx.add_result("t2", "r2")
        text = ctx.get_context_for(["t1", "t2"])
        assert "r1" in text
        assert "r2" in text

    def test_get_context_missing(self):
        ctx = CrewContext()
        text = ctx.get_context_for(["nonexistent"])
        assert text == ""
