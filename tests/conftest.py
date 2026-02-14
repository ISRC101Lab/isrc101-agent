"""Shared fixtures for isrc101-agent tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory and cd into it."""
    orig = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(orig)


@pytest.fixture
def sample_config_data():
    """Minimal .agent.conf.yml data dict."""
    return {
        "active-model": "local",
        "auto-confirm": False,
        "chat-mode": "agent",
        "auto-commit": True,
        "commit-prefix": "test: ",
        "theme": "github_dark",
        "command-timeout": 30,
        "verbose": False,
        "web-enabled": False,
        "reasoning-display": "summary",
        "web-display": "brief",
        "answer-style": "concise",
        "grounded-web-mode": "strict",
        "grounded-retry": 1,
        "grounded-visible-citations": "sources_only",
        "grounded-context-chars": 8000,
        "grounded-search-max-seconds": 180,
        "grounded-search-max-rounds": 8,
        "grounded-search-per-round": 3,
        "grounded-official-domains": ["docs.nvidia.com"],
        "grounded-fallback-to-open-web": True,
        "grounded-partial-on-timeout": True,
        "tool-parallelism": 4,
        "result-truncation-mode": "auto",
        "display-file-tree": "auto",
        "use-unicode": True,
        "models": {
            "local": {
                "provider": "local",
                "model": "openai/model",
                "description": "Local test model",
                "temperature": 0.0,
                "max-tokens": 8192,
                "context-window": 128000,
                "api-base": "http://localhost:8080/v1",
                "api-key": "not-needed",
            }
        },
    }


@pytest.fixture
def config_yaml_file(tmp_dir, sample_config_data):
    """Write a config YAML to tmp_dir and return its Path."""
    path = tmp_dir / ".agent.conf.yml"
    with open(path, "w") as f:
        yaml.dump(sample_config_data, f, default_flow_style=False)
    return path


@pytest.fixture
def mock_console():
    """A mock Rich Console that silently accepts all print calls."""
    c = MagicMock()
    c.print = MagicMock()
    c.input = MagicMock(return_value="n")
    return c
