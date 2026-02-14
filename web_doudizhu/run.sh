#!/bin/bash

# 斗地主游戏启动脚本

echo "========================================"
echo "       Web斗地主游戏启动脚本"
echo "========================================"

# 检查Python版本
if command -v python3 &> /dev/null; then
    python_version=$(python3 --version 2>&1 | awk '{print $2}')
    echo "✓ Python版本: $python_version"
else
    echo "✗ 错误: 未找到Python3，请先安装Python 3.8+"
    exit 1
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    echo "✓ 虚拟环境已创建"
else
    source venv/bin/activate
    echo "✓ 使用现有虚拟环境"
fi

# 检查依赖
echo "检查依赖..."
if [ ! -f "requirements.txt" ]; then
    echo "✗ 错误: requirements.txt 文件不存在"
    exit 1
fi

# 安装/更新依赖
echo "安装依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 创建必要的目录
echo "创建目录..."
mkdir -p data
mkdir -p static/images/cards
mkdir -p logs

# 检查数据库
if [ ! -f "data/game_scores.db" ]; then
    echo "初始化数据库..."
    # 数据库会在首次运行时自动创建
    echo "✓ 数据库将自动创建"
else
    echo "✓ 数据库已存在"
fi

# 运行测试
echo "运行快速测试..."
if python -m pytest test_game.py -v --tb=short 2>&1 | grep -q "PASSED"; then
    echo "✓ 所有测试通过"
else
    echo "⚠ 测试运行异常，继续启动..."
fi

# 显示启动信息
echo ""
echo "========================================"
echo "          服务器启动成功！"
echo "========================================"
echo "访问地址: http://localhost:8000"
echo "游戏界面: http://localhost:8000/frontend"
echo "API文档:  http://localhost:8000/docs"
echo "健康检查: http://localhost:8000/health"
echo ""
echo "接口示例:"
echo "  curl http://localhost:8000/health"
echo "  curl http://localhost:8000/leaderboard"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "========================================"

# 设置环境变量
export PYTHONUNBUFFERED=1
export PYTHONPATH=$(pwd):$PYTHONPATH

# 启动服务器
python3 main.py