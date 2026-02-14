"""Tests for CrewConfig parsing and validation."""

import pytest

from isrc101_agent.crew.crew import CrewConfig


class TestCrewConfigDefaults:
    """Default CrewConfig values."""

    def test_defaults(self):
        cfg = CrewConfig()
        assert cfg.max_parallel == 2
        assert cfg.per_agent_budget == 1_000_000
        assert cfg.token_budget == 0
        assert cfg.auto_review is True
        assert cfg.max_rework == 2
        assert cfg.message_timeout == 60.0
        assert cfg.task_timeout == 300.0
        assert cfg.budget_warning_thresholds == [50, 75, 90]
        assert cfg.role_budget_multipliers["coder"] == 1.0
        assert cfg.role_budget_multipliers["reviewer"] == 0.4
        assert cfg.display_mode == "compact"
        assert cfg.display_max_events == 4
        assert cfg.display_refresh_rate == 2


class TestCrewConfigFromDict:
    """CrewConfig.from_dict() parsing."""

    def test_from_empty_dict(self):
        cfg = CrewConfig.from_dict({})
        assert cfg.max_parallel == 2
        assert cfg.per_agent_budget == 1_000_000

    def test_from_none(self):
        cfg = CrewConfig.from_dict(None)
        assert cfg.max_parallel == 2

    def test_custom_values(self):
        data = {
            "max-parallel": 4,
            "per-agent-budget": 0,
            "token-budget": 0,
            "auto-review": False,
            "max-rework": 3,
            "task-timeout": 600,
        }
        cfg = CrewConfig.from_dict(data)
        assert cfg.max_parallel == 4
        assert cfg.per_agent_budget == 0
        assert cfg.token_budget == 0
        assert cfg.auto_review is False
        assert cfg.max_rework == 3
        assert cfg.task_timeout == 600

    def test_role_budget_multipliers(self):
        data = {
            "role-budget-multipliers": {
                "coder": 1.0,
                "reviewer": 1.0,
                "researcher": 1.0,
                "tester": 1.0,
            }
        }
        cfg = CrewConfig.from_dict(data)
        assert cfg.role_budget_multipliers["coder"] == 1.0
        assert cfg.role_budget_multipliers["reviewer"] == 1.0
        assert cfg.role_budget_multipliers["researcher"] == 1.0
        assert cfg.role_budget_multipliers["tester"] == 1.0

    def test_custom_role_multipliers(self):
        data = {
            "role-budget-multipliers": {
                "coder": 2.0,
                "custom_role": 0.8,
            }
        }
        cfg = CrewConfig.from_dict(data)
        assert cfg.role_budget_multipliers["coder"] == 2.0
        assert cfg.role_budget_multipliers["custom_role"] == 0.8
        # Defaults for unspecified roles
        assert cfg.role_budget_multipliers["reviewer"] == 0.4

    def test_empty_warning_thresholds(self):
        data = {"budget-warning-thresholds": []}
        cfg = CrewConfig.from_dict(data)
        assert cfg.budget_warning_thresholds == []

    def test_display_section(self):
        data = {
            "display": {
                "mode": "full",
                "max-events": 8,
                "refresh-rate": 4,
            }
        }
        cfg = CrewConfig.from_dict(data)
        assert cfg.display_mode == "full"
        assert cfg.display_max_events == 8
        assert cfg.display_refresh_rate == 4
