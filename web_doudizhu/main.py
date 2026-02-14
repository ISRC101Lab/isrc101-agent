#!/usr/bin/env python3
"""
斗地主游戏主入口
"""

import os
import uvicorn
from dotenv import load_dotenv
from backend.api import app

# 加载环境变量
load_dotenv()

def get_env_bool(key: str, default: bool = False) -> bool:
    """获取布尔类型的环境变量"""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 't', 'yes', 'y')

def main():
    """主函数"""
    # 获取配置
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = get_env_bool("DEBUG", False)
    log_level = os.getenv("LOG_LEVEL", "info")
    
    # 显示启动信息
    print("=" * 50)
    print("          斗地主游戏服务器")
    print("=" * 50)
    print(f"版本: 1.0.0")
    print(f"环境: {'开发' if debug else '生产'}")
    print(f"地址: http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    print(f"日志级别: {log_level}")
    print()
    print("访问地址:")
    print(f"  游戏界面: http://localhost:{port}/frontend")
    print(f"  API文档:  http://localhost:{port}/docs")
    print(f"  健康检查: http://localhost:{port}/health")
    print()
    print("按 Ctrl+C 停止服务器")
    print("=" * 50)
    
    # 启动服务器
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        reload=debug,
        access_log=True
    )

if __name__ == "__main__":
    main()