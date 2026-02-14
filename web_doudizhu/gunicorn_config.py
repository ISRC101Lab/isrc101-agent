# Gunicorn配置文件
import multiprocessing
import os

# 服务器设置
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "uvicorn.workers.UvicornWorker")

# 进程设置
threads = int(os.getenv("GUNICORN_THREADS", 2))
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", 1000))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", 50))
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", 2))

# 日志设置
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")  # 访问日志输出到stdout
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")    # 错误日志输出到stdout
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# 安全设置
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# 进程名称
proc_name = "dou_dizhu_game"

# 预加载应用
preload_app = True

# 守护进程模式（生产环境启用）
daemon = False

# 用户/组设置（需要root权限）
# user = "appuser"
# group = "appuser"

# 环境变量
raw_env = [
    "PYTHONPATH=/app",
    "PYTHONUNBUFFERED=1",
]

# 工作目录
chdir = "/app"

def post_fork(server, worker):
    """Worker进程创建后调用"""
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def worker_int(worker):
    """Worker收到中断信号时调用"""
    worker.log.info("Worker received interrupt signal")

def worker_abort(worker):
    """Worker异常终止时调用"""
    worker.log.info("Worker aborted")

def on_exit(server):
    """服务器退出时调用"""
    server.log.info("Server exiting")