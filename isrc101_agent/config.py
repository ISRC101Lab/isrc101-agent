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
from typing import Optional, Dict, List, Callable, Any, TYPE_CHECKING

import yaml
from dotenv import load_dotenv

if TYPE_CHECKING:
    from .ui_state import UIStateManager

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
GROUNDED_WEB_MODES = {"off", "strict"}
GROUNDED_CITATION_MODES = {"sources_only", "inline"}
RESULT_TRUNCATION_MODES = {"auto", "fixed", "none"}
FILE_TREE_DISPLAY_MODES = {"off", "auto", "always"}
CHAT_MODES = {"agent", "ask"}
THEMES = {"github_dark", "github_light", "nord", "dracula", "monokai"}
DEFAULT_GROUNDED_OFFICIAL_DOMAINS = [
    "docs.nvidia.com",
    "developer.nvidia.com",
]


# ── Configuration metadata and validation ──


@dataclass
class ConfigFieldSpec:
    """Configuration field specification with validation rules."""
    key: str
    field_name: str
    description: str
    value_type: str  # "str", "int", "bool", "list"
    default: Any
    validator: Optional[Callable[[Any], tuple[bool, Any, str]]] = None  # (valid, coerced_value, error_msg)


def _validate_int_range(value: Any, min_val: int, max_val: int) -> tuple[bool, int, str]:
    """Validate integer within range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False, 0, f"Must be an integer"
    if parsed < min_val or parsed > max_val:
        return False, max(min_val, min(max_val, parsed)), f"Must be between {min_val} and {max_val}"
    return True, parsed, ""


def _validate_enum(value: Any, valid_values: set) -> tuple[bool, str, str]:
    """Validate value is in allowed set."""
    val_str = str(value).strip().lower()
    if val_str not in valid_values:
        return False, "", f"Must be one of: {', '.join(sorted(valid_values))}"
    return True, val_str, ""


def _validate_bool(value: Any) -> tuple[bool, bool, str]:
    """Validate boolean value."""
    if isinstance(value, bool):
        return True, value, ""
    if isinstance(value, str):
        val_lower = value.strip().lower()
        if val_lower in ("1", "true", "yes", "on"):
            return True, True, ""
        if val_lower in ("0", "false", "no", "off"):
            return True, False, ""
    return False, False, "Must be true/false, yes/no, on/off, or 1/0"


def _validate_domain_list(value: Any) -> tuple[bool, List[str], str]:
    """Validate domain list."""
    if isinstance(value, str):
        raw_values = re.split(r"[\s,]+", value)
    elif isinstance(value, list):
        raw_values = [str(item) for item in value]
    else:
        return False, [], "Must be a comma-separated list of domains"

    cleaned = []
    seen = set()
    for item in raw_values:
        host = str(item or "").strip().lower()
        host = host.removeprefix("http://").removeprefix("https://").split("/")[0]
        if not host or host in seen:
            continue
        seen.add(host)
        cleaned.append(host)

    if not cleaned:
        return False, [], "At least one valid domain required"
    return True, cleaned, ""


# Configuration field registry with validation
CONFIG_FIELDS: Dict[str, ConfigFieldSpec] = {
    "active-model": ConfigFieldSpec(
        key="active-model",
        field_name="active_model",
        description="Currently active model preset name",
        value_type="str",
        default="local",
        validator=None,  # Validated against available models separately
    ),
    "max-iterations": ConfigFieldSpec(
        key="max-iterations",
        field_name="max_iterations",
        description="Maximum agent iterations per turn",
        value_type="int",
        default=30,
        validator=lambda v: _validate_int_range(v, 1, 100),
    ),
    "auto-confirm": ConfigFieldSpec(
        key="auto-confirm",
        field_name="auto_confirm",
        description="Auto-confirm tool executions without prompting",
        value_type="bool",
        default=False,
        validator=_validate_bool,
    ),
    "chat-mode": ConfigFieldSpec(
        key="chat-mode",
        field_name="chat_mode",
        description="Chat mode: agent (full actions) or ask (read-only)",
        value_type="str",
        default="agent",
        validator=lambda v: _validate_enum(v, CHAT_MODES),
    ),
    "auto-commit": ConfigFieldSpec(
        key="auto-commit",
        field_name="auto_commit",
        description="Automatically commit changes after file modifications",
        value_type="bool",
        default=True,
        validator=_validate_bool,
    ),
    "commit-prefix": ConfigFieldSpec(
        key="commit-prefix",
        field_name="commit_prefix",
        description="Prefix for auto-generated commit messages",
        value_type="str",
        default="isrc101: ",
        validator=None,
    ),
    "theme": ConfigFieldSpec(
        key="theme",
        field_name="theme",
        description="UI color theme",
        value_type="str",
        default="github_dark",
        validator=lambda v: _validate_enum(v, THEMES),
    ),
    "command-timeout": ConfigFieldSpec(
        key="command-timeout",
        field_name="command_timeout",
        description="Command execution timeout in seconds",
        value_type="int",
        default=30,
        validator=lambda v: _validate_int_range(v, 5, 300),
    ),
    "verbose": ConfigFieldSpec(
        key="verbose",
        field_name="verbose",
        description="Enable verbose debug output",
        value_type="bool",
        default=False,
        validator=_validate_bool,
    ),
    "web-enabled": ConfigFieldSpec(
        key="web-enabled",
        field_name="web_enabled",
        description="Enable web search and URL fetching",
        value_type="bool",
        default=False,
        validator=_validate_bool,
    ),
    "reasoning-display": ConfigFieldSpec(
        key="reasoning-display",
        field_name="reasoning_display",
        description="How to display model thinking: off, summary, or full",
        value_type="str",
        default="summary",
        validator=lambda v: _validate_enum(v, REASONING_DISPLAY_MODES),
    ),
    "web-display": ConfigFieldSpec(
        key="web-display",
        field_name="web_display",
        description="Web content display mode: brief, summary, or full",
        value_type="str",
        default="brief",
        validator=lambda v: _validate_enum(v, WEB_DISPLAY_MODES),
    ),
    "answer-style": ConfigFieldSpec(
        key="answer-style",
        field_name="answer_style",
        description="Answer detail level: concise, balanced, or detailed",
        value_type="str",
        default="concise",
        validator=lambda v: _validate_enum(v, ANSWER_STYLE_MODES),
    ),
    "grounded-web-mode": ConfigFieldSpec(
        key="grounded-web-mode",
        field_name="grounded_web_mode",
        description="Grounded web answer validation: off or strict",
        value_type="str",
        default="strict",
        validator=lambda v: _validate_enum(v, GROUNDED_WEB_MODES),
    ),
    "grounded-retry": ConfigFieldSpec(
        key="grounded-retry",
        field_name="grounded_retry",
        description="Retry attempts for grounded web queries",
        value_type="int",
        default=1,
        validator=lambda v: _validate_int_range(v, 0, 3),
    ),
    "grounded-visible-citations": ConfigFieldSpec(
        key="grounded-visible-citations",
        field_name="grounded_visible_citations",
        description="Citation display mode: sources_only or inline",
        value_type="str",
        default="sources_only",
        validator=lambda v: _validate_enum(v, GROUNDED_CITATION_MODES),
    ),
    "grounded-context-chars": ConfigFieldSpec(
        key="grounded-context-chars",
        field_name="grounded_context_chars",
        description="Maximum context characters for grounded search",
        value_type="int",
        default=8000,
        validator=lambda v: _validate_int_range(v, 800, 40000),
    ),
    "grounded-search-max-seconds": ConfigFieldSpec(
        key="grounded-search-max-seconds",
        field_name="grounded_search_max_seconds",
        description="Maximum search time in seconds",
        value_type="int",
        default=180,
        validator=lambda v: _validate_int_range(v, 20, 1200),
    ),
    "grounded-search-max-rounds": ConfigFieldSpec(
        key="grounded-search-max-rounds",
        field_name="grounded_search_max_rounds",
        description="Maximum search rounds",
        value_type="int",
        default=8,
        validator=lambda v: _validate_int_range(v, 1, 30),
    ),
    "grounded-search-per-round": ConfigFieldSpec(
        key="grounded-search-per-round",
        field_name="grounded_search_per_round",
        description="Searches per round",
        value_type="int",
        default=3,
        validator=lambda v: _validate_int_range(v, 1, 8),
    ),
    "grounded-official-domains": ConfigFieldSpec(
        key="grounded-official-domains",
        field_name="grounded_official_domains",
        description="Trusted official documentation domains (comma-separated)",
        value_type="list",
        default=DEFAULT_GROUNDED_OFFICIAL_DOMAINS,
        validator=_validate_domain_list,
    ),
    "grounded-fallback-to-open-web": ConfigFieldSpec(
        key="grounded-fallback-to-open-web",
        field_name="grounded_fallback_to_open_web",
        description="Fallback to open web if official sources fail",
        value_type="bool",
        default=True,
        validator=_validate_bool,
    ),
    "grounded-partial-on-timeout": ConfigFieldSpec(
        key="grounded-partial-on-timeout",
        field_name="grounded_partial_on_timeout",
        description="Return partial results on timeout",
        value_type="bool",
        default=True,
        validator=_validate_bool,
    ),
    "tool-parallelism": ConfigFieldSpec(
        key="tool-parallelism",
        field_name="tool_parallelism",
        description="Maximum parallel tool executions",
        value_type="int",
        default=4,
        validator=lambda v: _validate_int_range(v, 1, 12),
    ),
    "result-truncation-mode": ConfigFieldSpec(
        key="result-truncation-mode",
        field_name="result_truncation_mode",
        description="Tool result truncation: auto, fixed, or none",
        value_type="str",
        default="auto",
        validator=lambda v: _validate_enum(v, RESULT_TRUNCATION_MODES),
    ),
    "display-file-tree": ConfigFieldSpec(
        key="display-file-tree",
        field_name="display_file_tree",
        description="File tree display: off, auto, or always",
        value_type="str",
        default="auto",
        validator=lambda v: _validate_enum(v, FILE_TREE_DISPLAY_MODES),
    ),
}


def validate_config_value(key: str, value: Any) -> tuple[bool, Any, str]:
    """
    Validate a configuration value.

    Returns:
        (is_valid, coerced_value, error_message)
    """
    if key not in CONFIG_FIELDS:
        return False, value, f"Unknown configuration key: {key}"

    spec = CONFIG_FIELDS[key]

    # Handle special case for active-model validation
    if key == "active-model":
        # Will be validated against available models when setting
        return True, str(value), ""

    # Run validator if present
    if spec.validator:
        return spec.validator(value)

    # No validator — just coerce type
    if spec.value_type == "str":
        return True, str(value), ""
    elif spec.value_type == "int":
        try:
            return True, int(value), ""
        except (TypeError, ValueError):
            return False, spec.default, "Must be an integer"
    elif spec.value_type == "bool":
        return _validate_bool(value)

    return True, value, ""


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
    theme: str = "github_dark"
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
    reasoning_display: str = "summary"
    web_display: str = "brief"
    answer_style: str = "concise"
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
    max_web_calls_per_turn: int = 12
    tool_parallelism: int = 4
    result_truncation_mode: str = "auto"
    display_file_tree: str = "auto"
    use_unicode: bool = True  # Accessibility: Unicode vs ASCII icons
    crew_config: Dict = field(default_factory=dict)  # crew: section from YAML
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

        # Initialize UI state manager for this project
        from .ui_state import UIStateManager
        config.ui_state = UIStateManager(project_root=str(project_path))

        # Apply UI state preferences to config (project settings take priority)
        if config.ui_state:
            # Restore theme from UI state if not explicitly loaded from config
            if not config_loaded:
                saved_theme = config.ui_state.get_project_setting("theme")
                if saved_theme:
                    config.theme = saved_theme

            # Restore other UI preferences
            saved_reasoning = config.ui_state.get_project_setting("reasoning_display")
            if saved_reasoning:
                config.reasoning_display = config._normalize_reasoning_display(saved_reasoning)

            saved_web_display = config.ui_state.get_project_setting("web_display")
            if saved_web_display:
                config.web_display = config._normalize_web_display(saved_web_display)

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
        self.theme = data.get("theme", "github_dark")
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
        self.result_truncation_mode = self._normalize_result_truncation_mode(
            data.get("result-truncation-mode", "auto")
        )
        self.display_file_tree = self._normalize_file_tree_display(
            data.get("display-file-tree", "auto")
        )
        self.use_unicode = self._coerce_bool(
            data.get("use-unicode", True), default=True
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

        # Crew multi-agent configuration
        self.crew_config = data.get("crew", {})

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
            "theme": self.theme,
            "command-timeout": self.command_timeout,
            "verbose": self.verbose,
            "web-enabled": self.web_enabled,
            "reasoning-display": self.reasoning_display,
            "web-display": self.web_display,
            "answer-style": self.answer_style,
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
            "result-truncation-mode": self.result_truncation_mode,
            "display-file-tree": self.display_file_tree,
            "use-unicode": self.use_unicode,
            "skills-dir": self.skills_dir,
            "enabled-skills": self.enabled_skills,
            "models": {},
        }
        for name, m in self.models.items():
            if m is None:
                continue
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
        from .rendering import get_icon
        return [
            {"name": n, "active": n == self.active_model, "provider": m.provider,
             "model": m.model, "api_base": m.api_base or "-",
             "key": get_icon("✓") if m.resolve_api_key() else get_icon("✗"), "desc": m.description}
            for n, m in self.models.items()
        ]

    def summary(self) -> dict:
        from .rendering import get_icon
        p = self.get_active_preset()
        check = get_icon("✓")
        cross = get_icon("✗")
        return {
            "Active model": f"{self.active_model} → {p.model}",
            "Provider": p.provider,
            "API base": p.api_base or "(provider default)",
            "API key": f"{check}" if p.resolve_api_key() else f"{cross} not set",
            "Chat mode": self.chat_mode,
            "Theme": self.theme,
            "Skills": ", ".join(self.enabled_skills) if self.enabled_skills else "(none)",
            "Web": "ON" if self.web_enabled else "OFF",
            "Thinking display": self.reasoning_display,
            "Web display": self.web_display,
            "Answer style": self.answer_style,
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
    def _normalize_result_truncation_mode(value) -> str:
        mode = str(value or "auto").strip().lower()
        if mode not in RESULT_TRUNCATION_MODES:
            return "auto"
        return mode

    @staticmethod
    def _normalize_file_tree_display(value) -> str:
        mode = str(value or "auto").strip().lower()
        if mode not in FILE_TREE_DISPLAY_MODES:
            return "auto"
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

    def get_config_value(self, key: str) -> Any:
        """Get configuration value by key."""
        if key not in CONFIG_FIELDS:
            return None
        spec = CONFIG_FIELDS[key]
        return getattr(self, spec.field_name, spec.default)

    def set_config_value(self, key: str, value: Any) -> tuple[bool, str]:
        """
        Set configuration value with validation.

        Returns:
            (success, error_message)
        """
        # Special handling for active-model
        if key == "active-model":
            if value not in self.models:
                return False, f"Model '{value}' not found. Use /model list to see available models."
            self.active_model = value
            self.save()
            return True, ""

        is_valid, coerced_value, error_msg = validate_config_value(key, value)
        if not is_valid:
            return False, error_msg

        if key not in CONFIG_FIELDS:
            return False, f"Unknown configuration key: {key}"

        spec = CONFIG_FIELDS[key]
        setattr(self, spec.field_name, coerced_value)
        self.save()
        return True, ""

    def reset_config_value(self, key: str) -> tuple[bool, str]:
        """
        Reset configuration value to default.

        Returns:
            (success, error_message)
        """
        if key not in CONFIG_FIELDS:
            return False, f"Unknown configuration key: {key}"

        spec = CONFIG_FIELDS[key]
        setattr(self, spec.field_name, spec.default)
        self.save()
        return True, ""

    def get_config_diff(self) -> Dict[str, Dict[str, Any]]:
        """
        Get configuration differences from defaults.

        Returns:
            Dict with keys: 'modified', 'default'
        """
        result = {"modified": {}, "default": {}}

        for key, spec in CONFIG_FIELDS.items():
            current_value = getattr(self, spec.field_name, spec.default)

            # Handle list comparison
            if isinstance(spec.default, list):
                is_default = current_value == spec.default
            else:
                is_default = current_value == spec.default

            if is_default:
                result["default"][key] = {
                    "current": current_value,
                    "default": spec.default,
                    "type": spec.value_type,
                    "description": spec.description,
                }
            else:
                result["modified"][key] = {
                    "current": current_value,
                    "default": spec.default,
                    "type": spec.value_type,
                    "description": spec.description,
                }

        return result
