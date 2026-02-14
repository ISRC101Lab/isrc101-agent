"""Tests for configuration loading, validation and serialization."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from isrc101_agent.config import (
    Config,
    ModelPreset,
    validate_config_value,
    CONFIG_FIELDS,
    _validate_bool,
    _validate_int_range,
    _validate_enum,
)


class TestConfigLoad:
    """Config.load() from YAML files."""

    def test_load_from_yaml(self, tmp_dir, sample_config_data):
        path = tmp_dir / ".agent.conf.yml"
        with open(path, "w") as f:
            yaml.dump(sample_config_data, f)

        config = Config.load(str(tmp_dir))
        assert config.active_model == "local"
        assert config.auto_confirm is False
        assert config.chat_mode == "agent"
        assert config.auto_commit is True
        assert config.commit_prefix == "test: "
        assert config.reasoning_display == "summary"

    def test_load_models(self, tmp_dir, sample_config_data):
        path = tmp_dir / ".agent.conf.yml"
        with open(path, "w") as f:
            yaml.dump(sample_config_data, f)

        config = Config.load(str(tmp_dir))
        assert "local" in config.models
        preset = config.models["local"]
        assert isinstance(preset, ModelPreset)
        assert preset.provider == "local"
        assert preset.model == "openai/model"
        assert preset.api_base == "http://localhost:8080/v1"
        assert preset.max_tokens == 8192

    def test_load_defaults_when_no_config(self, tmp_dir):
        config = Config.load(str(tmp_dir))
        assert config.active_model == "local"
        assert len(config.models) > 0
        assert "local" in config.models

    def test_load_crew_section(self, tmp_dir, sample_config_data):
        sample_config_data["crew"] = {
            "max-parallel": 4,
            "per-agent-budget": 0,
            "token-budget": 0,
        }
        path = tmp_dir / ".agent.conf.yml"
        with open(path, "w") as f:
            yaml.dump(sample_config_data, f)

        config = Config.load(str(tmp_dir))
        assert config.crew_config == {
            "max-parallel": 4,
            "per-agent-budget": 0,
            "token-budget": 0,
        }


class TestConfigNormalization:
    """Mode and value normalization methods."""

    def test_normalize_chat_mode_valid(self):
        assert Config._normalize_chat_mode("agent") == "agent"
        assert Config._normalize_chat_mode("ask") == "ask"

    def test_normalize_chat_mode_aliases(self):
        assert Config._normalize_chat_mode("code") == "agent"
        assert Config._normalize_chat_mode("architect") == "agent"

    def test_normalize_chat_mode_invalid(self):
        assert Config._normalize_chat_mode("invalid") == "agent"
        assert Config._normalize_chat_mode("") == "agent"
        assert Config._normalize_chat_mode(None) == "agent"

    def test_normalize_reasoning_display(self):
        assert Config._normalize_reasoning_display("off") == "off"
        assert Config._normalize_reasoning_display("summary") == "summary"
        assert Config._normalize_reasoning_display("full") == "full"
        assert Config._normalize_reasoning_display("invalid") == "summary"

    def test_normalize_web_display(self):
        assert Config._normalize_web_display("brief") == "brief"
        assert Config._normalize_web_display("summary") == "summary"
        assert Config._normalize_web_display("full") == "full"
        assert Config._normalize_web_display("invalid") == "brief"

    def test_normalize_answer_style(self):
        assert Config._normalize_answer_style("concise") == "concise"
        assert Config._normalize_answer_style("balanced") == "balanced"
        assert Config._normalize_answer_style("detailed") == "detailed"
        assert Config._normalize_answer_style("invalid") == "concise"

    def test_normalize_grounded_web_mode(self):
        assert Config._normalize_grounded_web_mode("strict") == "strict"
        assert Config._normalize_grounded_web_mode("off") == "off"
        assert Config._normalize_grounded_web_mode("on") == "strict"
        assert Config._normalize_grounded_web_mode("true") == "strict"

    def test_coerce_bool(self):
        assert Config._coerce_bool(True, False) is True
        assert Config._coerce_bool(False, True) is False
        assert Config._coerce_bool("true", False) is True
        assert Config._coerce_bool("false", True) is False
        assert Config._coerce_bool("yes", False) is True
        assert Config._coerce_bool("no", True) is False
        assert Config._coerce_bool("1", False) is True
        assert Config._coerce_bool("0", True) is False
        assert Config._coerce_bool("garbage", True) is True
        assert Config._coerce_bool(1, False) is True
        assert Config._coerce_bool(0, True) is False

    def test_coerce_positive_int(self):
        assert Config._coerce_positive_int(5, 10, 1, 100) == 5
        assert Config._coerce_positive_int(-1, 10, 1, 100) == 1
        assert Config._coerce_positive_int(200, 10, 1, 100) == 100
        assert Config._coerce_positive_int("bad", 10, 1, 100) == 10

    def test_normalize_domain_list(self):
        result = Config._normalize_domain_list(["docs.nvidia.com", "developer.nvidia.com"])
        assert "docs.nvidia.com" in result
        assert "developer.nvidia.com" in result

    def test_normalize_domain_list_dedup(self):
        result = Config._normalize_domain_list(["foo.com", "foo.com", "bar.com"])
        assert result == ["foo.com", "bar.com"]

    def test_normalize_domain_list_strips_protocol(self):
        result = Config._normalize_domain_list(["https://foo.com/path", "http://bar.com"])
        assert result == ["foo.com", "bar.com"]


class TestModelPreset:
    """ModelPreset key resolution and kwarg generation."""

    def test_resolve_api_key_direct(self):
        preset = ModelPreset(name="t", provider="openai", model="test", api_key="sk-123")
        assert preset.resolve_api_key() == "sk-123"

    def test_resolve_api_key_env(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "sk-env-456")
        preset = ModelPreset(name="t", provider="openai", model="test", api_key_env="MY_KEY")
        assert preset.resolve_api_key() == "sk-env-456"

    def test_get_llm_kwargs(self):
        preset = ModelPreset(
            name="t", provider="openai", model="gpt-4",
            api_base="http://localhost:8080/v1", api_key="key123",
            temperature=0.5, max_tokens=4096, context_window=64000,
        )
        kwargs = preset.get_llm_kwargs()
        assert kwargs["model"] == "gpt-4"
        assert kwargs["api_base"] == "http://localhost:8080/v1"
        assert kwargs["api_key"] == "key123"
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 4096
        assert kwargs["context_window"] == 64000


class TestValidateConfigValue:
    """validate_config_value() for all field types."""

    def test_unknown_key(self):
        valid, val, err = validate_config_value("nonexistent-key", "whatever")
        assert not valid
        assert "Unknown" in err

    def test_bool_field(self):
        valid, val, err = validate_config_value("auto-confirm", "true")
        assert valid
        assert val is True

    def test_int_field(self):
        valid, val, err = validate_config_value("command-timeout", "60")
        assert valid
        assert val == 60

    def test_int_field_out_of_range(self):
        valid, val, err = validate_config_value("command-timeout", "999")
        assert not valid
        assert "between" in err.lower() or val != 999

    def test_enum_field(self):
        valid, val, err = validate_config_value("chat-mode", "ask")
        assert valid
        assert val == "ask"

    def test_enum_field_invalid(self):
        valid, val, err = validate_config_value("chat-mode", "invalid_mode")
        assert not valid

    def test_active_model_passthrough(self):
        valid, val, err = validate_config_value("active-model", "anything")
        assert valid
        assert val == "anything"


class TestConfigSave:
    """Config.save() round-trip."""

    def test_save_and_reload(self, tmp_dir, sample_config_data):
        path = tmp_dir / ".agent.conf.yml"
        with open(path, "w") as f:
            yaml.dump(sample_config_data, f)

        config = Config.load(str(tmp_dir))
        config.active_model = "local"
        config.web_enabled = True
        config.save(str(path))

        # Reload from YAML — web_enabled persists via YAML (not overridden by UIState)
        with open(path) as f:
            raw = yaml.safe_load(f)
        assert raw["web-enabled"] is True

    def test_set_config_value(self, tmp_dir, sample_config_data):
        path = tmp_dir / ".agent.conf.yml"
        with open(path, "w") as f:
            yaml.dump(sample_config_data, f)

        config = Config.load(str(tmp_dir))
        success, err = config.set_config_value("reasoning-display", "full")
        assert success
        assert config.reasoning_display == "full"

    def test_reset_config_value(self, tmp_dir, sample_config_data):
        path = tmp_dir / ".agent.conf.yml"
        with open(path, "w") as f:
            yaml.dump(sample_config_data, f)

        config = Config.load(str(tmp_dir))
        config.set_config_value("reasoning-display", "full")
        success, err = config.reset_config_value("reasoning-display")
        assert success
        assert config.reasoning_display == "summary"
