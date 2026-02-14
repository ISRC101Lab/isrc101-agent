#!/usr/bin/env python3
"""
斗地主游戏主入口
"""

import os
import sys
import logging
import uvicorn
from dotenv import load_dotenv
from backend.api import app

# 加载环境变量
load_dotenv()

# 配置日志
def setup_logging():
    """配置日志系统"""
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    log_file = os.path.join(log_dir, "server.log")
    
    # 配置日志格式
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # 文件日志处理器
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # 控制台日志处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return root_logger

logger = setup_logging()

def get_env_bool(key: str, default: bool = False) -> bool:
    """获取布尔类型的环境变量"""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 't', 'yes', 'y')

def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("          斗地主游戏服务器启动")
    logger.info("=" * 50)
    
    # 获取配置
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = get_env_bool("DEBUG", False)
    log_level = os.getenv("LOG_LEVEL", "info")
    
    # 显示启动信息
    logger.info(f"版本: 1.0.0")
    logger.info(f"环境: {'开发' if debug else '生产'}")
    logger.info(f"地址: http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    logger.info(f"日志级别: {log_level}")
    logger.info("")
    logger.info("访问地址:")
    logger.info(f"  游戏界面: http://localhost:{port}/frontend")
    logger.info(f"  API文档:  http://localhost:{port}/docs")
    logger.info(f"  健康检查: http://localhost:{port}/health")
    logger.info("")
    logger.info("按 Ctrl+C 停止服务器")
    logger.info("=" * 50)
    
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