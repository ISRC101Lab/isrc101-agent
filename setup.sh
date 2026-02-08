#!/usr/bin/env bash
# ══════════════════════════════════════════════════
#  isrc101-agent v1.0.0 — One-step setup
#  Run: bash setup.sh
# ══════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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

[ ! -d ".venv" ] && python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q 2>/dev/null
pip install -e . -q 2>/dev/null
echo "  ✓ Installed (editable mode)"

# ── Generate .agent.conf.yml ───────────────────────

if [ ! -f ".agent.conf.yml" ]; then
    cat > .agent.conf.yml << 'YAML_EOF'
# ══════════════════════════════════════════════════
#  isrc101-agent Configuration
#  /model to switch models interactively
# ══════════════════════════════════════════════════

active-model: local

max-iterations: 30
auto-confirm: false
chat-mode: code
auto-commit: true
commit-prefix: "isrc101: "
command-timeout: 30

models:

  local:
    provider: local
    model: openai/model
    api-base: http://localhost:8080/v1
    api-key: not-needed
    description: "Local model (vLLM / llama.cpp on :8080)"
    temperature: 0.0
    max-tokens: 8192

  deepseek-chat:
    provider: deepseek
    model: deepseek/deepseek-chat
    api-key: YOUR_DEEPSEEK_API_KEY_HERE
    description: "DeepSeek V3.2 (non-thinking)"
    temperature: 0.0
    max-tokens: 8192

  deepseek-reasoner:
    provider: deepseek
    model: deepseek/deepseek-reasoner
    api-key: YOUR_DEEPSEEK_API_KEY_HERE
    description: "DeepSeek V3.2 (thinking)"
    temperature: 0.0
    max-tokens: 8192

  # ── BLSC Qwen3-VL models ──
  # Get API key from your BLSC account

  qwen3-vl-235b:
    provider: openai
    model: openai/Qwen3-VL-235B-A22B-Instruct
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 235B Instruct (BLSC)"
    temperature: 0.0
    max-tokens: 8192

  qwen3-vl-235b-think:
    provider: openai
    model: openai/Qwen3-VL-235B-A22B-Thinking
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 235B Thinking (BLSC)"
    temperature: 0.0
    max-tokens: 8192

  qwen3-vl-30b:
    provider: openai
    model: openai/Qwen3-VL-30B-A3B-Instruct
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 30B Instruct (BLSC)"
    temperature: 0.0
    max-tokens: 8192

  qwen3-vl-30b-think:
    provider: openai
    model: openai/Qwen3-VL-30B-A3B-Thinking
    api-base: https://llmapi.blsc.cn/v1/
    api-key: YOUR_BLSC_API_KEY_HERE
    description: "Qwen3-VL 30B Thinking (BLSC)"
    temperature: 0.0
    max-tokens: 8192


YAML_EOF
    echo "  ✓ Created .agent.conf.yml"
else
    echo "  ✓ .agent.conf.yml exists"
fi

# ── Generate AGENT.md ──────────────────────────────

if [ ! -f "AGENT.md" ]; then
    cat > AGENT.md << 'MD_EOF'
# Project Instructions

<!-- isrc101-agent reads this file automatically. -->

## Tech Stack
<!-- e.g. Python 3.12, CUDA, C++ -->

## Coding Conventions
<!-- e.g. PEP 8, type hints -->

## Important Notes
<!-- e.g. Don't touch migrations/ -->
MD_EOF
    echo "  ✓ Created AGENT.md"
else
    echo "  ✓ AGENT.md exists"
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
echo "    /help    all commands"
echo "  ═══════════════════════════════════════"
echo ""
