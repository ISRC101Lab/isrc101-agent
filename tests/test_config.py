from unittest.mock import patch

import isrc101_agent.config as config_module
from isrc101_agent.config import Config, ModelPreset


def test_default_presets_exist():
    presets = Config.get_default_presets()

    assert "local" in presets
    assert "deepseek-chat" in presets
    assert isinstance(presets["local"], ModelPreset)
    assert presets["local"].provider == "local"


def test_load_creates_defaults(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    config_dir = tmp_path / "global-config"
    config_file = config_dir / "config.yml"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_file)

    cfg = Config.load(project_dir=str(project_dir))

    assert config_file.exists()
    assert cfg.active_model == "local"
    assert "local" in cfg.models
    assert cfg._config_source == str(config_file)


def test_set_active_model():
    cfg = Config()
    cfg.models = Config.get_default_presets()

    with patch.object(cfg, "save") as save_mock:
        assert cfg.set_active_model("deepseek-chat") is True
        save_mock.assert_called_once()

    assert cfg.active_model == "deepseek-chat"
    assert cfg.set_active_model("does-not-exist") is False


def test_model_preset_resolve_api_key(monkeypatch):
    monkeypatch.setenv("CUSTOM_TEST_KEY", "from-env")
    env_preset = ModelPreset(
        name="custom",
        provider="openai",
        model="openai/test",
        api_key_env="CUSTOM_TEST_KEY",
    )
    assert env_preset.resolve_api_key() == "from-env"

    direct_preset = ModelPreset(
        name="direct",
        provider="openai",
        model="openai/test",
        api_key="direct-key",
        api_key_env="CUSTOM_TEST_KEY",
    )
    assert direct_preset.resolve_api_key() == "direct-key"

    monkeypatch.setenv("OPENAI_API_KEY", "provider-default")
    provider_preset = ModelPreset(
        name="provider",
        provider="openai",
        model="openai/test",
    )
    assert provider_preset.resolve_api_key() == "provider-default"


def test_display_settings_normalization_and_bounds(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    cfg_file = project_dir / ".agent.conf.yml"
    cfg_file.write_text(
        """
active-model: local
reasoning-display: invalid
web-display: also-invalid
answer-style: too-verbose
stream-profile: super-fast
web-preview-lines: -2
web-preview-chars: 40
web-context-chars: 999999
models:
  local:
    provider: local
    model: openai/model
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / "missing-global.yml")
    cfg = Config.load(project_dir=str(project_dir))

    assert cfg.reasoning_display == "summary"
    assert cfg.web_display == "brief"
    assert cfg.answer_style == "concise"
    assert cfg.stream_profile == "ultra"
    assert cfg.web_preview_lines == 1
    assert cfg.web_preview_chars == 80
    assert cfg.web_context_chars == 20000


def test_default_skills_include_concise_and_performance():
    cfg = Config()
    assert "openai-docs" in cfg.enabled_skills
    assert "gh-address-comments" in cfg.enabled_skills
    assert "gh-fix-ci" in cfg.enabled_skills
    assert "playwright" in cfg.enabled_skills
    assert "performance-tuning" in cfg.enabled_skills
