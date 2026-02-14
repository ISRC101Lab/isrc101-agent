# Web斗地主游戏

一个基于Web的斗地主游戏，支持3名玩家（1名真人玩家 + 2名AI玩家）。

## 功能特性

- 完整的斗地主游戏规则实现
- 实时WebSocket通信
- 智能AI对手
- 响应式Web界面
- 游戏状态持久化
- 计分系统

## 技术栈

- 后端: FastAPI + WebSocket
- 前端: HTML5 + CSS3 + JavaScript
- 数据库: SQLite (用于游戏记录)
- AI: 基于规则的智能算法

## 安装

1. 克隆项目
2. 安装依赖:
   ```bash
   pip install -r requirements.txt
   ```

## 快速开始

### 1. 安装依赖
```bash
cd web_doudizhu
pip install -r requirements.txt
```

### 2. 运行游戏服务器
```bash
# 方法1: 直接运行
python main.py

# 方法2: 使用启动脚本
# Linux/macOS:
chmod +x run.sh
./run.sh

# Windows:
run.bat
```

### 3. 访问游戏
服务器启动后，打开浏览器访问：
- 游戏界面: http://localhost:8000/frontend
- API文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 4. 开始游戏
1. 输入玩家名称
2. 创建新房间或加入已有房间
3. 等待AI玩家自动加入（或邀请好友）
4. 开始叫地主并享受游戏！

## 部署

### 使用Docker（推荐）
```bash
# 构建Docker镜像
docker build -t dou-dizhu-game .

# 运行容器
docker run -d -p 8000:8000 --name dou-dizhu dou-dizhu-game
```

### 生产环境部署
建议使用：
- **Gunicorn + Uvicorn** (ASGI服务器)
- **Nginx** (反向代理和静态文件服务)
- **Supervisor** (进程管理)

配置示例 (gunicorn_config.py):
```python
bind = "0.0.0.0:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
```

启动命令:
```bash
gunicorn -c gunicorn_config.py main:app
```

## 游戏规则

### 基本规则
- 3名玩家，使用54张牌（包含大小王）
- 叫地主阶段：玩家依次叫分（1-3分）
- 地主获得3张底牌
- 地主先出牌，按逆时针顺序出牌
- 牌型必须大于上家或为炸弹/火箭

### 牌型
1. 单张
2. 对子
3. 三张
4. 三带一
5. 三带二
6. 顺子（5张或以上连续单张）
7. 连对（3对或以上连续对子）
8. 飞机（2个或以上连续三张）
9. 炸弹（4张相同点数）
10. 火箭（大小王）

## API文档

启动服务器后访问: http://localhost:8000/docs (自动生成的Swagger UI)

### 主要API端点

#### 游戏管理
- `GET /` - API信息
- `GET /health` - 健康检查
- `GET /rooms` - 获取房间列表
- `POST /rooms` - 创建房间
- `GET /rooms/{room_id}` - 获取房间信息
- `POST /rooms/{room_id}/join` - 加入房间
- `POST /rooms/{room_id}/ai` - 添加AI玩家

#### 游戏操作
- `POST /rooms/{room_id}/bid` - 叫地主
- `POST /rooms/{room_id}/play` - 出牌
- `POST /rooms/{room_id}/pass` - 过牌

#### 统计数据
- `GET /leaderboard` - 获取排行榜
- `GET /players/{player_id}/stats` - 获取玩家统计
- `GET /games/history` - 获取游戏历史

### WebSocket端点
- `ws://localhost:8000/ws/{room_id}/{player_id}` - 游戏实时通信

### 前端访问
- `GET /frontend` - 游戏Web界面
- 静态资源: `/frontend/*` (CSS, JS文件)
- 图片资源: `/static/*` (图片资源)

## 项目结构

```
web_doudizhu/
├── backend/           # 后端代码
│   ├── card.py       # 牌型判断
│   ├── game.py       # 游戏逻辑
│   ├── ai.py         # AI算法
│   ├── scoring.py    # 计分系统
│   └── api.py        # FastAPI接口
├── frontend/         # 前端代码
│   ├── index.html    # 游戏界面
│   └── style.css     # 样式文件
├── static/           # 静态资源
├── data/             # 数据文件
├── main.py           # 主入口
├── requirements.txt  # 依赖列表
└── README.md         # 说明文档
```

## 测试

运行测试:
```bash
pytest test_game.py
```

## 许可证

MIT License