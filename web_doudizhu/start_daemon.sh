#!/bin/bash
# 后台启动脚本 (Linux/Mac)
# 用法: ./start_daemon.sh [start|stop|restart|status]

NAME="dou_dizhu"
PID_FILE="logs/${NAME}.pid"
LOG_FILE="logs/${NAME}.log"
MAIN_FILE="main.py"

# 创建日志目录
mkdir -p logs

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

start() {
    echo "正在启动斗地主服务器..."
    
    # 检查是否已运行
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "服务器已在运行中 (PID: $PID)"
            return 1
        fi
    fi
    
    # 检查Python环境
    if ! command -v python3 &> /dev/null; then
        echo "错误: 未找到Python3"
        exit 1
    fi
    
    # 后台启动
    nohup python3 "$MAIN_FILE" > "$LOG_FILE" 2>&1 &
    PID=$!
    
    # 保存PID
    echo $PID > "$PID_FILE"
    
    # 等待一下检查是否启动成功
    sleep 2
    
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "服务器启动成功 (PID: $PID)"
        echo "日志文件: $LOG_FILE"
        echo "访问地址: http://localhost:8000/frontend"
    else
        echo "服务器启动失败"
        cat "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop() {
    echo "正在停止服务器..."
    
    if [ ! -f "$PID_FILE" ]; then
        echo "服务器未运行"
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ps -p "$PID" > /dev/null 2>&1; then
        kill "$PID"
        sleep 2
        
        # 强制杀死如果还没停止
        if ps -p "$PID" > /dev/null 2>&1; then
            kill -9 "$PID"
        fi
        
        echo "服务器已停止"
    else
        echo "服务器未运行"
    fi
    
    rm -f "$PID_FILE"
}

status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "服务器未运行"
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "服务器运行中 (PID: $PID)"
        return 0
    else
        echo "服务器未运行 (PID文件存在但进程不存在)"
        rm -f "$PID_FILE"
        return 1
    fi
}

restart() {
    stop
    sleep 1
    start
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
