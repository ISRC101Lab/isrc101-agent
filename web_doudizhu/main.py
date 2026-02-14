#!/usr/bin/env python3
"""
斗地主游戏主入口
"""

import uvicorn
from backend.api import app

if __name__ == "__main__":
    print("启动斗地主游戏服务器...")
    print("访问地址: http://localhost:8000")
    print("API文档: http://localhost:8000/docs")
    print("前端界面: http://localhost:8000/frontend")
    print("按 Ctrl+C 停止服务器")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )