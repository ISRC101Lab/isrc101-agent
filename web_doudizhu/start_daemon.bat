@echo off
REM 后台启动脚本 (Windows)
REM 用法: start_daemon.bat [start|stop|restart|status]

setlocal enabledelayedexpansion

set "NAME=dou_dizhu"
set "PID_FILE=logs\%NAME%.pid"
set "LOG_FILE=logs\%NAME%.log"
set "MAIN_FILE=main.py"

if not exist "logs" mkdir logs

if "%~1"=="" goto usage
if "%~1"=="start" goto start
if "%~1"=="stop" goto stop
if "%~1"=="restart" goto restart
if "%~1"=="status" goto status
goto usage

:start
echo 正在启动斗地主服务器...
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    tasklist /FI "PID eq %PID%" 2>nul | findstr /I "%PID%" >nul
    if !errorlevel! equ 0 (
        echo 服务器已在运行中 (PID: !PID!)
        exit /b 1
    )
)
start /b python "%MAIN_FILE%" > "%LOG_FILE%" 2>&1
timeout /t 2 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo 服务器启动成功 (PID: %%a)
    echo %%a > "%PID_FILE%"
    echo 日志文件: %LOG_FILE%
    echo 访问地址: http://localhost:8000/frontend
    goto started
)
echo 检查日志文件确认启动状态
echo %%a > "%PID_FILE%"
:started
exit /b 0

:stop
echo 正在停止服务器...
if not exist "%PID_FILE%" (
    echo 服务器未运行
    exit /b 1
)
set /p PID=<"%PID_FILE%"
taskkill /PID %PID% /F >nul 2>&1
del "%PID_FILE%" 2>nul
echo 服务器已停止
exit /b 0

:status
if not exist "%PID_FILE%" (
    echo 服务器未运行
    exit /b 1
)
set /p PID=<"%PID_FILE%"
tasklist /FI "PID eq %PID%" 2>nul | findstr /I "%PID%" >nul
if %errorlevel% equ 0 (
    echo 服务器运行中 (PID: !PID!)
    exit /b 0
) else (
    echo 服务器未运行
    del "%PID_FILE%" 2>nul
    exit /b 1
)

:restart
call :stop
timeout /t 1 /nobreak >nul
call :start
exit /b 0

:usage
echo 用法: %0 [start^|stop^|restart^|status]
exit /b 1
