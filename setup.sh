#!/usr/bin/env bash
# ══════════════════════════════════════════════════
#  isrc101-agent v1.0.0 — One-step setup
#  Run: bash setup.sh
# ══════════════════════════════════════════════════

set -Ee -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

on_setup_error() {
    local exit_code=$?
    local line_no="$1"
    local failed_cmd="${BASH_COMMAND:-unknown}"

    echo ""
    echo "  ❌ Setup failed (exit ${exit_code})"
    echo "     Line: ${line_no}"
    echo "     Command: ${failed_cmd}"

    echo "  🔎 Diagnostics:"
    if command -v python3 >/dev/null 2>&1; then
        echo "     python3: $(python3 --version 2>&1)"
    else
        echo "     python3: not found"
    fi

    if [ -x ".venv/bin/python" ]; then
        echo "     .venv python: $(.venv/bin/python --version 2>&1)"
    elif [ -d ".venv" ]; then
        echo "     .venv exists but may be incomplete"
    else
        echo "     .venv not found"
    fi

    if command -v pip >/dev/null 2>&1; then
        local global_user
        global_user="$(pip config get global.user 2>/dev/null || true)"
        local user_user
        user_user="$(pip config get user.user 2>/dev/null || true)"
        [ -n "$global_user" ] && echo "     pip config global.user=$global_user"
        [ -n "$user_user" ] && echo "     pip config user.user=$user_user"
    fi

    echo "  💡 Tip: run 'bash -x setup.sh' for full trace"
}

trap 'on_setup_error $LINENO' ERR

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │   isrc101-agent v1.0.0 — Setup      │"
echo "  └─────────────────────────────────────┘"
echo ""

# ── Fix flat directory structure ───────────────────

if [ -f "__init__.py" ] && [ ! -d "isrc101_agent" ]; then
    echo "  🔧 Fixing directory structure..."
    mkdir -p isrc101_agent/tools

    for f in __init__.py main.py agent.py llm.py config.py; do
        [ -f "$f" ] && mv "$f" isrc101_agent/
    done
    for f in schemas.py file_ops.py shell.py git_ops.py registry.py; do
        [ -f "$f" ] && mv "$f" isrc101_agent/tools/
    done

    if [ ! -f "isrc101_agent/tools/__init__.py" ]; then
        cat > isrc101_agent/tools/__init__.py << 'PYEOF'
from .registry import ToolRegistry
from .schemas import TOOL_SCHEMAS, get_tools_for_mode
from .git_ops import GitOps
__all__ = ["ToolRegistry", "TOOL_SCHEMAS", "get_tools_for_mode", "GitOps"]
PYEOF
    fi

    rm -rf *.egg-info build mnt files.zip 2>/dev/null || true
    echo "  ✓ Structure fixed"
fi

if [ ! -f "isrc101_agent/__init__.py" ]; then
    echo "  ❌ isrc101_agent/__init__.py not found."
    exit 1
fi

echo "  📁 isrc101_agent/       $(ls isrc101_agent/*.py 2>/dev/null | wc -l) modules"
echo "  📁 isrc101_agent/tools/ $(ls isrc101_agent/tools/*.py 2>/dev/null | wc -l) modules"

# ── Venv + install ─────────────────────────────────

if [ ! -f ".venv/bin/activate" ]; then
    [ -d ".venv" ] && echo "  ⚠️  Found incomplete .venv, recreating..."
    rm -rf .venv

    # Custom shell prompt label shown after activation: (isrc101)
    if ! python3 -m venv --prompt isrc101 .venv; then
        echo "  ❌ Failed to create virtual environment."
        echo "     Please install venv support, then rerun setup.sh"
        echo "     Ubuntu/Debian: sudo apt install -y python3-venv python3.12-venv"
        exit 1
    fi
fi

source .venv/bin/activate
if ! python -m pip install --upgrade pip --no-user -q; then
    echo "  ⚠️  Skipping pip self-upgrade; using current pip"
fi
python -m pip install -e . --no-user -q
echo "  ✓ Installed (editable mode)"

# ── Generate .agent.conf.yml ───────────────────────

if [ ! -f ".agent.conf.yml" ]; then
    cat > .agent.conf.yml << 'YAML_EOF'
# ══════════════════════════════════════════════════
#  isrc101-agent Configuration
#  /model and /skills to switch behavior interactively
# ══════════════════════════════════════════════════

active-model: local

max-iterations: 30
auto-confirm: false
chat-mode: code
auto-commit: true
commit-prefix: "isrc101: "
command-timeout: 180
skills-dir: skills
web-enabled: false
enabled-skills:
  - python-bugfix
  - test-designer
  - security-review

models:

  local:
    provider: local
    model: openai/model
    api-base: http://localhost:8080/v1
    api-key: not-needed
    description: "Local model (vLLM / llama.cpp on :8080)"
    temperature: 0.0
    max-tokens: 4096

  deepseek-chat:
    provider: deepseek
    model: deepseek/deepseek-chat
    api-key: YOUR_DEEPSEEK_API_KEY_HERE
    description: "DeepSeek V3.2 (non-thinking)"
    temperature: 0.0
    max-tokens: 4096

  deepseek-reasoner:
    provider: deepseek
    model: deepseek/deepseek-reasoner
    api-key: YOUR_DEEPSEEK_API_KEY_HERE
    description: "DeepSeek V3.2 (thinking)"
    temperature: 0.0
    max-tokens: 4096

  # ── BLSC Qwen3-VL models ──
  # Get API key from your BLSC account

  qwen3-vl-235b:
    provider: openai
    model: openai/Qwen3-VL-235B-A22B-Instruct
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 235B Instruct (BLSC)"
    temperature: 0.0
    max-tokens: 4096

  qwen3-vl-235b-think:
    provider: openai
    model: openai/Qwen3-VL-235B-A22B-Thinking
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 235B Thinking (BLSC)"
    temperature: 0.0
    max-tokens: 4096

  qwen3-vl-30b:
    provider: openai
    model: openai/Qwen3-VL-30B-A3B-Instruct
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 30B Instruct (BLSC)"
    temperature: 0.0
    max-tokens: 4096

  qwen3-vl-30b-think:
    provider: openai
    model: openai/Qwen3-VL-30B-A3B-Thinking
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 30B Thinking (BLSC)"
    temperature: 0.0
    max-tokens: 4096


YAML_EOF
    echo "  ✓ Created .agent.conf.yml"
else
    echo "  ✓ .agent.conf.yml exists"
fi

# ── Done ───────────────────────────────────────────

echo ""
echo "  ═══════════════════════════════════════"
echo "  ✅ Ready!"
echo ""
echo "    source .venv/bin/activate"
echo "    cd /path/to/project"
echo "    isrc run"
echo ""
echo "    /model   switch models (↑↓ Enter)"
echo "    /skills  select built-in skills"
echo "    /web     toggle web access"
echo "    /help    all commands"
echo "  ═══════════════════════════════════════"
echo ""
