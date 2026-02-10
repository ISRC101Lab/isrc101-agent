"""
Configuration — centralized model registry with project-level config.

Loading priority:
  1. Project dir .agent.conf.yml
  2. Git root .agent.conf.yml
  3. Global ~/.isrc101-agent/config.yml

API keys: always merged from AGENT_HOME/.agent.conf.yml (single source of truth).
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List

import yaml
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".isrc101-agent"
CONFIG_FILE = CONFIG_DIR / "config.yml"
HISTORY_FILE = CONFIG_DIR / "history.txt"

# Agent install directory — single source of truth for API keys
AGENT_HOME = Path(__file__).resolve().parent.parent
AGENT_HOME_CONFIG = AGENT_HOME / ".agent.conf.yml"

DEFAULT_ENABLED_SKILLS = [
    "git-workflow",
    "code-review",
    "smart-refactor",
    "python-bugfix",
]

REASONING_DISPLAY_MODES = {"off", "summary", "full"}
WEB_DISPLAY_MODES = {"brief", "summary", "full"}
ANSWER_STYLE_MODES = {"concise", "balanced", "detailed"}
STREAM_PROFILES = {"stable", "smooth", "ultra"}
GROUNDED_WEB_MODES = {"off", "strict"}
GROUNDED_CITATION_MODES = {"sources_only", "inline"}
DEFAULT_GROUNDED_OFFICIAL_DOMAINS = [
    "docs.nvidia.com",
    "developer.nvidia.com",
]


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
    chat_mode: str = "agent"
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
    skills_dir: str = "skills"
    enabled_skills: List[str] = field(default_factory=lambda: list(DEFAULT_ENABLED_SKILLS))
    web_enabled: bool = False  # /web toggle
    tavily_api_key: Optional[str] = None  # optional: TAVILY_API_KEY env var
    reasoning_display: str = "summary"
    web_display: str = "brief"
    answer_style: str = "concise"
    stream_profile: str = "ultra"
    grounded_web_mode: str = "strict"
    grounded_retry: int = 1
    grounded_visible_citations: str = "sources_only"
    grounded_context_chars: int = 8000
    grounded_search_max_seconds: int = 180
    grounded_search_max_rounds: int = 8
    grounded_search_per_round: int = 3
    grounded_official_domains: List[str] = field(
        default_factory=lambda: list(DEFAULT_GROUNDED_OFFICIAL_DOMAINS)
    )
    grounded_fallback_to_open_web: bool = True
    grounded_partial_on_timeout: bool = True
    web_preview_lines: int = 2
    web_preview_chars: int = 220
    web_context_chars: int = 4000
    tool_parallelism: int = 4
    project_root: Optional[str] = None
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

        config._merge_api_keys_from_home()
        config._apply_env()
        config.project_root = str(project_path)
        return config

    @classmethod
    def get_default_presets(cls) -> Dict[str, ModelPreset]:
        return {
            "local": ModelPreset(
                name="local", provider="local", model="openai/model",
                api_base="http://localhost:8080/v1", api_key="not-needed",
                description="Local model (vLLM / llama.cpp on :8080)",
                max_tokens=4096, context_window=32000,
            ),
            "deepseek-chat": ModelPreset(
                name="deepseek-chat", provider="deepseek",
                model="deepseek/deepseek-chat",
                api_key_env="DEEPSEEK_API_KEY",
                description="DeepSeek V3.2 (non-thinking)",
                max_tokens=4096,
            ),
            "deepseek-reasoner": ModelPreset(
                name="deepseek-reasoner", provider="deepseek",
                model="deepseek/deepseek-reasoner",
                api_key_env="DEEPSEEK_API_KEY",
                description="DeepSeek V3.2 (thinking)",
                max_tokens=4096,
            ),
            "qwen3-vl-235b": ModelPreset(
                name="qwen3-vl-235b", provider="openai",
                model="openai/Qwen3-VL-235B-A22B-Instruct",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 235B Instruct (BLSC)",
                max_tokens=4096,
            ),
            "qwen3-vl-235b-think": ModelPreset(
                name="qwen3-vl-235b-think", provider="openai",
                model="openai/Qwen3-VL-235B-A22B-Thinking",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 235B Thinking (BLSC)",
                max_tokens=4096,
            ),
            "qwen3-vl-30b": ModelPreset(
                name="qwen3-vl-30b", provider="openai",
                model="openai/Qwen3-VL-30B-A3B-Instruct",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 30B Instruct (BLSC)",
                max_tokens=4096,
            ),
            "qwen3-vl-30b-think": ModelPreset(
                name="qwen3-vl-30b-think", provider="openai",
                model="openai/Qwen3-VL-30B-A3B-Thinking",
                api_base="https://llmapi.blsc.cn/v1/",
                api_key_env="BLSC_API_KEY",
                description="Qwen3-VL 30B Thinking (BLSC)",
                max_tokens=4096,
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
        self.chat_mode = self._normalize_chat_mode(data.get("chat-mode", "agent"))
        self.auto_commit = data.get("auto-commit", True)
        self.commit_prefix = data.get("commit-prefix", "isrc101: ")
        self.command_timeout = data.get("command-timeout", 30)
        self.verbose = data.get("verbose", False)
        self.web_enabled = data.get("web-enabled", False)
        self.reasoning_display = self._normalize_reasoning_display(
            data.get("reasoning-display", "summary")
        )
        self.web_display = self._normalize_web_display(
            data.get("web-display", "brief")
        )
        self.answer_style = self._normalize_answer_style(
            data.get("answer-style", "concise")
        )
        self.stream_profile = self._normalize_stream_profile(
            data.get("stream-profile", "ultra")
        )
        self.grounded_web_mode = self._normalize_grounded_web_mode(
            data.get("grounded-web-mode", "strict")
        )
        self.grounded_retry = self._coerce_positive_int(
            data.get("grounded-retry", 1), default=1, min_value=0, max_value=3
        )
        self.grounded_visible_citations = self._normalize_grounded_citations(
            data.get("grounded-visible-citations", "sources_only")
        )
        self.grounded_context_chars = self._coerce_positive_int(
            data.get("grounded-context-chars", 8000), default=8000, min_value=800, max_value=40000
        )
        self.grounded_search_max_seconds = self._coerce_positive_int(
            data.get("grounded-search-max-seconds", 180), default=180, min_value=20, max_value=1200
        )
        self.grounded_search_max_rounds = self._coerce_positive_int(
            data.get("grounded-search-max-rounds", 8), default=8, min_value=1, max_value=30
        )
        self.grounded_search_per_round = self._coerce_positive_int(
            data.get("grounded-search-per-round", 3), default=3, min_value=1, max_value=8
        )
        self.grounded_official_domains = self._normalize_domain_list(
            data.get("grounded-official-domains", DEFAULT_GROUNDED_OFFICIAL_DOMAINS)
        )
        self.grounded_fallback_to_open_web = self._coerce_bool(
            data.get("grounded-fallback-to-open-web", True), default=True
        )
        self.grounded_partial_on_timeout = self._coerce_bool(
            data.get("grounded-partial-on-timeout", True), default=True
        )
        self.web_preview_lines = self._coerce_positive_int(
            data.get("web-preview-lines", 2), default=2, min_value=1, max_value=12
        )
        self.web_preview_chars = self._coerce_positive_int(
            data.get("web-preview-chars", 220), default=220, min_value=80, max_value=4000
        )
        self.web_context_chars = self._coerce_positive_int(
            data.get("web-context-chars", 4000), default=4000, min_value=500, max_value=20000
        )
        self.tool_parallelism = self._coerce_positive_int(
            data.get("tool-parallelism", 4), default=4, min_value=1, max_value=12
        )
        self.skills_dir = data.get("skills-dir", "skills")
        if "enabled-skills" in data:
            raw_enabled = data.get("enabled-skills", [])
            if isinstance(raw_enabled, list):
                self.enabled_skills = [str(item) for item in raw_enabled if str(item).strip()]
            else:
                self.enabled_skills = []
        else:
            self.enabled_skills = list(DEFAULT_ENABLED_SKILLS)
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

    def _merge_api_keys_from_home(self):
        """Fill missing api_key from AGENT_HOME_CONFIG (single source of truth)."""
        if not AGENT_HOME_CONFIG.exists():
            return
        try:
            with open(AGENT_HOME_CONFIG) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return
        home_models = data.get("models", {})
        for name, preset in self.models.items():
            if preset.api_key:
                continue
            home_m = home_models.get(name)
            if home_m and home_m.get("api-key"):
                preset.api_key = home_m["api-key"]

    def _apply_env(self):
        env_map = {
            "AGENT_MODEL": ("active_model", str),
            "AGENT_AUTO_CONFIRM": ("auto_confirm", lambda v: v.lower() in ("true", "1")),
            "AGENT_VERBOSE": ("verbose", lambda v: v.lower() in ("true", "1")),
            "AGENT_TOOL_PARALLELISM": (
                "tool_parallelism",
                lambda v: self._coerce_positive_int(v, default=self.tool_parallelism, min_value=1, max_value=12),
            ),
        }
        for env_var, (attr, conv) in env_map.items():
            val = os.environ.get(env_var)
            if val:
                try:
                    setattr(self, attr, conv(val))
                except (ValueError, TypeError):
                    pass
        # Tavily API key (optional, for web search upgrade)
        if not self.tavily_api_key:
            self.tavily_api_key = os.environ.get("TAVILY_API_KEY")

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
            "web-enabled": self.web_enabled,
            "reasoning-display": self.reasoning_display,
            "web-display": self.web_display,
            "answer-style": self.answer_style,
            "stream-profile": self.stream_profile,
            "grounded-web-mode": self.grounded_web_mode,
            "grounded-retry": self.grounded_retry,
            "grounded-visible-citations": self.grounded_visible_citations,
            "grounded-context-chars": self.grounded_context_chars,
            "grounded-search-max-seconds": self.grounded_search_max_seconds,
            "grounded-search-max-rounds": self.grounded_search_max_rounds,
            "grounded-search-per-round": self.grounded_search_per_round,
            "grounded-official-domains": self.grounded_official_domains,
            "grounded-fallback-to-open-web": self.grounded_fallback_to_open_web,
            "grounded-partial-on-timeout": self.grounded_partial_on_timeout,
            "web-preview-lines": self.web_preview_lines,
            "web-preview-chars": self.web_preview_chars,
            "web-context-chars": self.web_context_chars,
            "tool-parallelism": self.tool_parallelism,
            "skills-dir": self.skills_dir,
            "enabled-skills": self.enabled_skills,
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
            "Skills": ", ".join(self.enabled_skills) if self.enabled_skills else "(none)",
            "Web": "ON" if self.web_enabled else "OFF",
            "Thinking display": self.reasoning_display,
            "Web display": self.web_display,
            "Answer style": self.answer_style,
            "Stream profile": self.stream_profile,
            "Grounded web": self.grounded_web_mode,
            "Grounded retry": self.grounded_retry,
            "Grounded citations": self.grounded_visible_citations,
            "Grounded context chars": self.grounded_context_chars,
            "Grounded search seconds": self.grounded_search_max_seconds,
            "Grounded search rounds": self.grounded_search_max_rounds,
            "Grounded per round": self.grounded_search_per_round,
            "Grounded domains": ", ".join(self.grounded_official_domains),
            "Grounded fallback": "ON" if self.grounded_fallback_to_open_web else "OFF",
            "Grounded partial": "ON" if self.grounded_partial_on_timeout else "OFF",
            "Tool parallelism": self.tool_parallelism,
            "Project": self.project_root,
            "Config": self._config_source or "(defaults)",
        }

    @staticmethod
    def _normalize_reasoning_display(value) -> str:
        mode = str(value or "summary").strip().lower()
        if mode not in REASONING_DISPLAY_MODES:
            return "summary"
        return mode

    @staticmethod
    def _normalize_web_display(value) -> str:
        mode = str(value or "brief").strip().lower()
        if mode not in WEB_DISPLAY_MODES:
            return "brief"
        return mode

    @staticmethod
    def _normalize_answer_style(value) -> str:
        style = str(value or "concise").strip().lower()
        if style not in ANSWER_STYLE_MODES:
            return "concise"
        return style

    @staticmethod
    def _normalize_stream_profile(value) -> str:
        profile = str(value or "ultra").strip().lower()
        if profile not in STREAM_PROFILES:
            return "ultra"
        return profile

    @staticmethod
    def _normalize_chat_mode(value) -> str:
        mode = str(value or "agent").strip().lower()
        if mode in ("code", "architect"):
            return "agent"
        if mode not in ("agent", "ask"):
            return "agent"
        return mode

    @staticmethod
    def _normalize_grounded_web_mode(value) -> str:
        mode = str(value or "strict").strip().lower()
        if mode in ("on", "true", "1"):
            mode = "strict"
        if mode not in GROUNDED_WEB_MODES:
            return "strict"
        return mode

    @staticmethod
    def _normalize_grounded_citations(value) -> str:
        mode = str(value or "sources_only").strip().lower()
        if mode not in GROUNDED_CITATION_MODES:
            return "sources_only"
        return mode

    @staticmethod
    def _normalize_domain_list(value) -> List[str]:
        if isinstance(value, str):
            raw_values = re.split(r"[\s,]+", value)
        elif isinstance(value, list):
            raw_values = [str(item) for item in value]
        else:
            raw_values = list(DEFAULT_GROUNDED_OFFICIAL_DOMAINS)

        cleaned: List[str] = []
        seen = set()
        for item in raw_values:
            host = str(item or "").strip().lower()
            host = host.removeprefix("http://").removeprefix("https://").split("/")[0]
            if not host or host in seen:
                continue
            seen.add(host)
            cleaned.append(host)

        if not cleaned:
            return list(DEFAULT_GROUNDED_OFFICIAL_DOMAINS)
        return cleaned

    @staticmethod
    def _coerce_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off"):
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    @staticmethod
    def _coerce_positive_int(value, default: int, min_value: int = 1, max_value: int = 100000) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        if parsed < min_value:
            return min_value
        if parsed > max_value:
            return max_value
        return parsed

    @staticmethod
    def _find_git_root(path: Path) -> Optional[Path]:
        current = path
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None
