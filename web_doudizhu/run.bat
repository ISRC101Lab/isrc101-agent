@echo off
REM 斗地主游戏启动脚本（Windows）

echo ========================================
echo        Web斗地主游戏启动脚本
echo ========================================

REM 检查Python版本
python --version
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.10+
    pause
    exit /b 1
)

REM 检查依赖
echo 检查依赖...
if not exist "requirements.txt" (
    echo 错误: requirements.txt 文件不存在
    pause
    exit /b 1
)

REM 安装依赖（如果未安装）
echo 安装依赖...
pip install -r requirements.txt

REM 创建必要的目录
echo 创建目录...
if not exist "data" mkdir data
if not exist "static\images" mkdir static\images

REM 启动服务器
echo 启动游戏服务器...
echo 访问地址: http://localhost:8000
echo API文档: http://localhost:8000/docs
echo 前端界面: http://localhost:8000/frontend
echo 按 Ctrl+C 停止服务器
echo ========================================

python main.py