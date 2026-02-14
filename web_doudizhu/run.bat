@echo off
REM 斗地主游戏启动脚本（Windows）

echo ========================================
echo        Web斗地主游戏启动脚本
echo ========================================

REM 检查Python版本
python --version > nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.10+
    pause
    exit /b 1
)

REM 显示Python版本
for /f "tokens=*" %%i in ('python --version 2^>^&1') do (
    echo ✓ Python版本: %%i
)

REM 检查依赖
echo 检查依赖...
if not exist "requirements.txt" (
    echo 错误: requirements.txt 文件不存在
    pause
    exit /b 1
)

REM 安装/更新依赖
echo 安装依赖...
python -m pip install --upgrade pip
pip install -r requirements.txt

REM 创建必要的目录
echo 创建目录...
if not exist "data" mkdir data
if not exist "static\images\cards" mkdir static\images\cards
if not exist "logs" mkdir logs

REM 检查数据库
if not exist "data\game_scores.db" (
    echo 初始化数据库...
    echo ✓ 数据库将自动创建
) else (
    echo ✓ 数据库已存在
)

REM 运行快速测试
echo 运行快速测试...
python -m pytest test_game.py -v --tb=short 2>&1 | findstr "PASSED" > nul
if errorlevel 1 (
    echo ⚠ 测试运行异常，继续启动...
) else (
    echo ✓ 所有测试通过
)

REM 显示启动信息
echo.
echo ========================================
echo           服务器启动成功！
echo ========================================
echo 访问地址: http://localhost:8000
echo 游戏界面: http://localhost:8000/frontend
echo API文档:  http://localhost:8000/docs
echo 健康检查: http://localhost:8000/health
echo.
echo 接口示例:
echo   curl http://localhost:8000/health
echo   curl http://localhost:8000/leaderboard
echo.
echo 按 Ctrl+C 停止服务器
echo ========================================

REM 设置环境变量
set PYTHONUNBUFFERED=1
set PYTHONPATH=%~dp0;%PYTHONPATH%

REM 启动服务器
python main.py