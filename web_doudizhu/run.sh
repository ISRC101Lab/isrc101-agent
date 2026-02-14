#!/bin/bash

# 斗地主游戏启动脚本

echo "========================================"
echo "       Web斗地主游戏启动脚本"
echo "========================================"

# 检查Python版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python版本: $python_version"

# 检查依赖
echo "检查依赖..."
if [ ! -f "requirements.txt" ]; then
    echo "错误: requirements.txt 文件不存在"
    exit 1
fi

# 安装依赖（如果未安装）
echo "安装依赖..."
pip install -r requirements.txt

# 创建必要的目录
echo "创建目录..."
mkdir -p data
mkdir -p static/images

# 启动服务器
echo "启动游戏服务器..."
echo "访问地址: http://localhost:8000"
echo "API文档: http://localhost:8000/docs"
echo "前端界面: http://localhost:8000/frontend"
echo "按 Ctrl+C 停止服务器"
echo "========================================"

python3 main.py