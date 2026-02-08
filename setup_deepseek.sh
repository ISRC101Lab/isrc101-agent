#!/bin/bash
# ══════════════════════════════════════════════════
#  DeepSeek API 配置脚本
#  Run: bash setup_deepseek.sh your-api-key
# ══════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │   DeepSeek API 配置                 │"
echo "  └─────────────────────────────────────┘"
echo ""

# 检查是否提供了 API 密钥
if [ -z "$1" ]; then
    echo "  ❌ 未提供 API 密钥"
    echo ""
    echo "  用法: bash setup_deepseek.sh your-api-key"
    echo ""
    echo "  或设置环境变量:"
    echo "    export DEEPSEEK_API_KEY='your-api-key'"
    echo "    source .venv/bin/activate"
    echo "    isrc run"
    echo ""
    exit 1
fi

API_KEY="$1"

# 检查配置文件是否存在
if [ ! -f ".agent.conf.yml" ]; then
    echo "  ❌ 配置文件 .agent.conf.yml 不存在"
    echo "  请先运行: bash setup.sh"
    exit 1
fi

# 备份原配置文件
cp .agent.conf.yml .agent.conf.yml.backup
echo "  ✓ 已备份原配置到 .agent.conf.yml.backup"

# 更新配置文件
sed -i "s|api-key: YOUR_DEEPSEEK_API_KEY_HERE|api-key: ${API_KEY}|g" .agent.conf.yml
sed -i "s|# api-key-env: DEEPSEEK_API_KEY|api-key-env: DEEPSEEK_API_KEY|g" .agent.conf.yml

echo "  ✓ 已更新 .agent.conf.yml"

# 设置环境变量（临时）
export DEEPSEEK_API_KEY="$API_KEY"

echo ""
echo "  ═══════════════════════════════════════"
echo "  ✅ DeepSeek API 配置完成！"
echo ""
echo "  配置信息:"
echo "    - API Key: ${API_KEY:0:8}...${API_KEY: -4}"
echo "    - 配置文件: .agent.conf.yml"
echo ""
echo "  测试命令:"
echo "    source .venv/bin/activate"
echo "    isrc run"
echo "    /model deepseek-chat"
echo "    /model deepseek-reasoner"
echo ""
echo "  或使用环境变量:"
echo "    export DEEPSEEK_API_KEY='$API_KEY'"
echo "    isrc run"
echo ""
echo "  ═══════════════════════════════════════"
echo ""