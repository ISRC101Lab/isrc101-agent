"""
Configuration — centralized model registry with project-level config.

Loading priority:
  1. Project dir .agent.conf.yml
  2. Git root .agent.conf.yml
  3. Global ~/.isrc101-agent/config.yml
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List

import yaml
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".isrc101-agent"
CONFIG_FILE = CONFIG_DIR / "config.yml"
HISTORY_FILE = CONFIG_DIR / "history.txt"
PROJECT_INSTRUCTION_NAME = "AGENT.md"


@dataclass
class ModelPreset:
    name: str
    provider: str
    model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4096
    context_window: int = 128000
    description: str = ""

    def resolve_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        env_map = {
            "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY", "gemini": "GEMINI_API_KEY",
        }
        env_var = env_map.get(self.provider)
        return os.environ.get(env_var) if env_var else None

    def apply_to_env(self):
        """Set env vars as fallback. Prefer get_llm_kwargs() for direct passing."""
        key = self.resolve_api_key()
        if key:
            provider_env = {
                "anthropic": "ANTHROPIC_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
                "gemini": "GEMINI_API_KEY",
            }
            os.environ[provider_env.get(self.provider, "OPENAI_API_KEY")] = key

    def get_llm_kwargs(self) -> dict:
        """Return kwargs dict for LLMAdapter constructor — direct, no env vars."""
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "context_window": self.context_window,
            "api_base": self.api_base,
            "api_key": self.resolve_api_key(),
        }


@dataclass
class Config:
    active_model: str = "local"
    models: Dict[str, ModelPreset] = field(default_factory=dict)
    max_iterations: int = 30
    auto_confirm: bool = False
    chat_mode: str = "code"
    auto_commit: bool = True
    commit_prefix: str = "isrc101: "
    blocked_commands: List[str] = field(
        default_factory=lambda: [
            "rm -rf /", "rm -rf /*", "mkfs", "dd if=", "> /dev/sda",
            "sudo ", "chmod 777", "curl|sh", "curl|bash", "wget|sh",
            ":(){:|:&};:",  # fork bomb
        ]
    )
    command_timeout: int = 30
    verbose: bool = False
    project_root: Optional[str] = None
    project_instructions: Optional[str] = None
    _config_source: str = ""

    @classmethod
    def load(cls, project_dir: str = ".") -> "Config":
        config = cls()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        project_path = Path(project_dir).resolve()

        for env_path in [CONFIG_DIR / ".env", project_path / ".env"]:
            if env_path.exists():
                load_dotenv(env_path, override=False)

        git_root = cls._find_git_root(project_path)
        config_loaded = False
        for candidate in [
            project_path / ".agent.conf.yml",
            (git_root / ".agent.conf.yml") if git_root and git_root != project_path else None,
            CONFIG_FILE,
        ]:
            if candidate and candidate.exists():
                config._load_yaml(candidate)
                config._config_source = str(candidate)
                config_loaded = True
                break

        if not config_loaded:
            config._add_default_presets()
            config._config_source = str(CONFIG_FILE)
            config.save()

        config._apply_env()
        config.project_root = str(project_path)

        for search_dir in [project_path, git_root]:
            if search_dir:
                md_file = search_dir / PROJECT_INSTRUCTION_NAME
                if md_file.exists():
                    config.project_instructions = md_file.read_text(encoding="utf-8")
                    break
        return config

    @classmethod
    def get_default_presets(cls) -> Dict[str, ModelPreset]:
        return {
            "local": ModelPreset(
                name="local", provider="local", model="openai/model",
                api_base="http://localhost:8080/v1", api_key="not-needed",
                description="Local model (vLLM / llama.cpp on :8080)",
                max_tokens=8192, context_window=32000,
            ),
            "deepseek-chat": ModelPreset(
                name="deepseek-chat", provider="deepseek",
                model="deepseek/deepseek-chat",
                api_key_env="DEEPSEEK_API_KEY",
                description="DeepSeek V3.2 (non-thinking)",
                max_tokens=8192,
            ),
            "deepseek-reasoner": ModelPreset(
                name="deepseek-reasoner", provider="deepseek",
                model="deepseek/deepseek-reasoner",
                api_key_env="DEEPSEEK_API_KEY",
                description="DeepSeek V3.2 (thinking)",
                max_tokens=8192,
            ),
            "qwen3-vl-235b": ModelPreset(
                name="qwen3-vl-235b", provider="openai",
                model="openai/Qwen3-VL-235B-A22B-Instruct",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 235B Instruct (BLSC)",
                max_tokens=8192,
            ),
            "qwen3-vl-235b-think": ModelPreset(
                name="qwen3-vl-235b-think", provider="openai",
                model="openai/Qwen3-VL-235B-A22B-Thinking",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 235B Thinking (BLSC)",
                max_tokens=8192,
            ),
            "qwen3-vl-30b": ModelPreset(
                name="qwen3-vl-30b", provider="openai",
                model="openai/Qwen3-VL-30B-A3B-Instruct",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 30B Instruct (BLSC)",
                max_tokens=8192,
            ),
            "qwen3-vl-30b-think": ModelPreset(
                name="qwen3-vl-30b-think", provider="openai",
                model="openai/Qwen3-VL-30B-A3B-Thinking",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 30B Thinking (BLSC)",
                max_tokens=8192,
            ),
        }

    def _add_default_presets(self):
        self.models = self.get_default_presets()
        self.active_model = "local"

    def _load_yaml(self, filepath: Path):
        try:
            with open(filepath) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            self._add_default_presets()
            return

        self.active_model = data.get("active-model", "local")
        self.max_iterations = data.get("max-iterations", 30)
        self.auto_confirm = data.get("auto-confirm", False)
        self.chat_mode = data.get("chat-mode", "code")
        self.auto_commit = data.get("auto-commit", True)
        self.commit_prefix = data.get("commit-prefix", "isrc101: ")
        self.command_timeout = data.get("command-timeout", 30)
        self.verbose = data.get("verbose", False)
        if "blocked-commands" in data:
            self.blocked_commands = data["blocked-commands"]

        self.models = {}
        for name, m in data.get("models", {}).items():
            self.models[name] = ModelPreset(
                name=name, provider=m.get("provider", "openai"),
                model=m.get("model", "openai/gpt-4o-mini"),
                api_base=m.get("api-base"), api_key=m.get("api-key"),
                api_key_env=m.get("api-key-env"),
                temperature=m.get("temperature", 0.0),
                max_tokens=m.get("max-tokens", 4096),
                context_window=m.get("context-window", 128000),
                description=m.get("description", ""),
            )
        if not self.models:
            self._add_default_presets()

    def _apply_env(self):
        env_map = {
            "AGENT_MODEL": ("active_model", str),
            "AGENT_AUTO_CONFIRM": ("auto_confirm", lambda v: v.lower() in ("true", "1")),
            "AGENT_VERBOSE": ("verbose", lambda v: v.lower() in ("true", "1")),
        }
        for env_var, (attr, conv) in env_map.items():
            val = os.environ.get(env_var)
            if val:
                try:
                    setattr(self, attr, conv(val))
                except (ValueError, TypeError):
                    pass

    def save(self, filepath: Optional[str] = None):
        target = Path(filepath) if filepath else (
            Path(self._config_source) if self._config_source else CONFIG_FILE
        )
        target.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "active-model": self.active_model,
            "max-iterations": self.max_iterations,
            "auto-confirm": self.auto_confirm,
            "chat-mode": self.chat_mode,
            "auto-commit": self.auto_commit,
            "commit-prefix": self.commit_prefix,
            "command-timeout": self.command_timeout,
            "verbose": self.verbose,
            "models": {},
        }
        for name, m in self.models.items():
            entry = {"provider": m.provider, "model": m.model,
                     "description": m.description, "temperature": m.temperature,
                     "max-tokens": m.max_tokens, "context-window": m.context_window}
            if m.api_base:
                entry["api-base"] = m.api_base
            if m.api_key:
                entry["api-key"] = m.api_key
            if m.api_key_env:
                entry["api-key-env"] = m.api_key_env
            data["models"][name] = entry

        with open(target, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        self._config_source = str(target)

    def get_active_preset(self) -> ModelPreset:
        if self.active_model in self.models:
            return self.models[self.active_model]
        if self.models:
            return next(iter(self.models.values()))
        return ModelPreset(name="default", provider="local", model="openai/model",
                           api_base="http://localhost:8080/v1", api_key="not-needed")

    def set_active_model(self, name: str) -> bool:
        if name in self.models:
            self.active_model = name
            self.save()
            return True
        return False

    def list_models(self) -> List[Dict]:
        return [
            {"name": n, "active": n == self.active_model, "provider": m.provider,
             "model": m.model, "api_base": m.api_base or "-",
             "key": "✓" if m.resolve_api_key() else "✗", "desc": m.description}
            for n, m in self.models.items()
        ]

    def summary(self) -> dict:
        p = self.get_active_preset()
        return {
            "Active model": f"{self.active_model} → {p.model}",
            "Provider": p.provider,
            "API base": p.api_base or "(provider default)",
            "API key": "✓" if p.resolve_api_key() else "✗ not set",
            "Chat mode": self.chat_mode,
            "Project": self.project_root,
            "AGENT.md": "✓" if self.project_instructions else "✗",
            "Config": self._config_source or "(defaults)",
        }

    @staticmethod
    def _find_git_root(path: Path) -> Optional[Path]:
        current = path
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None
