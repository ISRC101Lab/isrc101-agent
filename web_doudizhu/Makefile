# 斗地主游戏Makefile

.PHONY: help install run test clean docker-build docker-run lint format

# 默认目标
help:
	@echo "斗地主游戏管理命令:"
	@echo "  make install    安装依赖"
	@echo "  make run        启动开发服务器"
	@echo "  make run-prod   启动生产服务器"
	@echo "  make test       运行测试"
	@echo "  make lint       代码检查"
	@echo "  make format     代码格式化"
	@echo "  make clean      清理临时文件"
	@echo "  make docker-build  构建Docker镜像"
	@echo "  make docker-run    运行Docker容器"
	@echo "  make demo-data     初始化演示数据"

# 安装依赖
install:
	@echo "安装Python依赖..."
	pip install -r requirements.txt
	@echo "✓ 依赖安装完成"

# 启动开发服务器
run:
	@echo "启动开发服务器..."
	python main.py

# 启动生产服务器 (使用gunicorn)
run-prod:
	@echo "启动生产服务器..."
	gunicorn -c gunicorn_config.py main:app

# 运行测试
test:
	@echo "运行测试..."
	pytest test_game.py -v --cov=backend --cov-report=html

# 代码检查
lint:
	@echo "代码检查..."
	@echo "Python代码检查..."
	flake8 backend/ tests/
	@echo "✓ 代码检查完成"

# 代码格式化
format:
	@echo "代码格式化..."
	black backend/ tests/
	isort backend/ tests/
	@echo "✓ 代码格式化完成"

# 清理临时文件
clean:
	@echo "清理临时文件..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type f -name ".coverage" -delete
	@echo "✓ 清理完成"

# Docker构建
docker-build:
	@echo "构建Docker镜像..."
	docker build -t dou-dizhu-game:latest .

# Docker运行
docker-run:
	@echo "运行Docker容器..."
	docker run -d -p 8000:8000 --name dou-dizhu dou-dizhu-game:latest
	@echo "✓ 容器已启动，访问 http://localhost:8000"

# 初始化演示数据
demo-data:
	@echo "初始化演示数据..."
	python init_demo_data.py
	@echo "✓ 演示数据已初始化"

# 数据库备份
db-backup:
	@echo "备份数据库..."
	@if [ -f "data/game_scores.db" ]; then \
		cp data/game_scores.db "data/game_scores_backup_$$(date +%Y%m%d_%H%M%S).db"; \
		echo "✓ 数据库备份完成"; \
	else \
		echo "⚠ 数据库文件不存在"; \
	fi

# 查看日志
logs:
	@if [ -f "logs/game_server.log" ]; then \
		tail -f logs/game_server.log; \
	else \
		echo "日志文件不存在"; \
	fi