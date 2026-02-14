"""Role definitions and agent factory for crew members."""

import uuid
from dataclasses import dataclass, field
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..agent import Agent
    from ..config import Config
    from .context import SharedTokenBudget


@dataclass
class RoleSpec:
    """Specification for a crew role — drives agent construction."""

    name: str
    description: str
    system_prompt_extra: str
    mode: str = "agent"  # "agent" | "ask"
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None
    model_override: Optional[str] = None
    temperature_override: Optional[float] = None
    auto_confirm: bool = True


DEFAULT_ROLES = {
    "coder": RoleSpec(
        name="coder",
        description="Write and modify code",
        system_prompt_extra=(
            "You are a coding specialist in a multi-agent crew.\n"
            "Write clean, well-tested code. Always verify changes by reading files after editing.\n"
            "Focus only on the task assigned to you."
        ),
        mode="agent",
        blocked_tools=["web_search", "web_fetch"],
    ),
    "reviewer": RoleSpec(
        name="reviewer",
        description="Code review for correctness, security, and style",
        system_prompt_extra=(
            "You are a code reviewer in a multi-agent crew.\n"
            "Check for correctness, security vulnerabilities, and style issues.\n"
            "Do not modify files — only report findings."
        ),
        mode="ask",
        allowed_tools=["read_file", "list_directory", "search_files", "find_files", "find_symbol"],
    ),
    "researcher": RoleSpec(
        name="researcher",
        description="Technical research and information gathering",
        system_prompt_extra=(
            "You are a research specialist in a multi-agent crew.\n"
            "Find authoritative information to support the team's task.\n"
            "Cite sources when possible."
        ),
        mode="ask",
    ),
    "tester": RoleSpec(
        name="tester",
        description="Write and run tests",
        system_prompt_extra=(
            "You are a testing specialist in a multi-agent crew.\n"
            "Write tests and verify code correctness.\n"
            "Run tests with bash and report results."
        ),
        mode="agent",
    ),
}


def load_roles_from_config(config: "Config") -> dict[str, RoleSpec]:
    """Load role definitions from config, falling back to defaults."""
    crew_cfg = getattr(config, "crew_config", None) or {}
    roles_cfg = crew_cfg.get("roles", {})

    roles = dict(DEFAULT_ROLES)

    for name, spec in roles_cfg.items():
        roles[name] = RoleSpec(
            name=name,
            description=spec.get("description", name),
            system_prompt_extra=spec.get("instructions", ""),
            mode=spec.get("mode", "agent"),
            allowed_tools=spec.get("allowed-tools"),
            blocked_tools=spec.get("blocked-tools"),
            model_override=spec.get("model-override"),
            temperature_override=spec.get("temperature-override"),
            auto_confirm=spec.get("auto-confirm", True),
        )

    return roles


def create_agent_for_role(
    role: RoleSpec,
    config: "Config",
    project_root: str,
    shared_budget: "SharedTokenBudget",
) -> "Agent":
    """Create an independent Agent instance configured for a specific role.

    Each agent gets its own LLMAdapter and ToolRegistry so they can
    operate concurrently without sharing mutable state.
    """
    from ..agent import Agent
    from ..llm import LLMAdapter
    from ..tools import ToolRegistry

    # Validate config attributes
    if not hasattr(config, 'blocked_commands'):
        config.blocked_commands = []
    if not hasattr(config, 'command_timeout'):
        config.command_timeout = 120
    if not hasattr(config, 'commit_prefix'):
        config.commit_prefix = "isrc101"
    if not hasattr(config, 'web_enabled'):
        config.web_enabled = False
    if not hasattr(config, 'web_display'):
        config.web_display = "summary"

    # Resolve model — role override or active preset
    if role.model_override and role.model_override in config.models:
        preset = config.models[role.model_override]
    else:
        preset = config.get_active_preset()

    llm_kwargs = preset.get_llm_kwargs()
    if role.temperature_override is not None:
        llm_kwargs["temperature"] = role.temperature_override

    llm = LLMAdapter(**llm_kwargs)

    # Independent tool registry
    tools = ToolRegistry(
        project_root=project_root,
        blocked_commands=config.blocked_commands,
        command_timeout=config.command_timeout,
        commit_prefix=config.commit_prefix,
    )
    tools.web_enabled = config.web_enabled

    # Apply tool restrictions
    if role.allowed_tools is not None:
        tools.restrict_to(set(role.allowed_tools))
    if role.blocked_tools is not None:
        tools.block_tools(set(role.blocked_tools))

    # Build role-specific instructions
    crew_header = (
        f"## Crew Role: {role.name}\n"
        f"Description: {role.description}\n\n"
    )
    skill_instructions = crew_header + role.system_prompt_extra

    agent = Agent(
        llm=llm,
        tools=tools,
        auto_confirm=role.auto_confirm,
        chat_mode=role.mode,
        auto_commit=False,  # Coordinator handles commits
        skill_instructions=skill_instructions,
        reasoning_display="off",
        web_display=config.web_display,
        answer_style="concise",
        quiet=True,  # Suppress console output in crew mode
        config=config,
        auto_compact_threshold=85,  # Auto-compact at 85% context usage
    )

    # Attach budget reference for token tracking
    agent._crew_budget = shared_budget

    # Unique agent ID for per-agent budget tracking
    agent_id = f"{role.name}-{uuid.uuid4().hex[:8]}"
    agent._crew_agent_id = agent_id

    # Budget enforcement callback — soft stop on per-agent or global exhaustion.
    # Instead of raising immediately, set a flag so the agent can
    # finish its current iteration gracefully before stopping.
    def _budget_callback(tokens: int):
        shared_budget.consume(tokens, agent_id=agent_id)
        if shared_budget.is_agent_exhausted(agent_id):
            agent._budget_exhausted = True

    agent.token_callback = _budget_callback

    return agent
