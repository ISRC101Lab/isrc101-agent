# 斗地主游戏快速启动指南

## 启动服务器

### 方法1：直接运行（推荐）
```bash
cd web_doudizhu
python main.py
```

### 方法2：使用启动脚本
```bash
cd web_doudizhu

# Linux/macOS
chmod +x run.sh
./run.sh

# Windows
run.bat
```

## 访问游戏

1. **打开浏览器** 访问: http://localhost:8000/frontend

2. **连接服务器**:
   - 输入玩家名称
   - 点击 "Connect to Server" 按钮
   - 状态应显示为 "✅ 已连接"

3. **创建或加入房间**:
   - **创建房间**: 输入房间名称（可选），点击 "Create"
   - **加入房间**: 输入房间ID，点击 "Join"

4. **开始游戏**:
   - 游戏会自动添加AI玩家（共3名玩家）
   - 等待发牌
   - 叫地主阶段：选择叫分或Pass
   - 出牌阶段：选择手牌并出牌

## 故障排除

### 1. 连接显示 "已断开"
- **检查服务器是否运行**: 确保终端显示服务器启动信息
- **检查端口**: 确保端口8000未被其他程序占用
- **运行诊断工具**: `python diagnose_connection.py`

### 2. 无法访问游戏界面
- **检查URL**: 确保访问 http://localhost:8000/frontend
- **检查前端文件**: 确保 frontend/ 目录存在且包含必要文件
- **查看浏览器控制台**: 按F12打开开发者工具，查看Console标签页中的错误信息

### 3. API错误
- **检查API路径**: 确保API端点正常工作
- **运行诊断**: 使用诊断工具检查API连接
- **查看服务器日志**: 查看终端中的错误信息

## 游戏控制

### 键盘快捷键
- **空格键**: 排序手牌
- **Ctrl+Enter**: 发送聊天消息
- **ESC**: 关闭所有模态框

### 游戏功能
- **叫地主**: 选择叫分倍数（1x, 2x, 3x）或Pass
- **出牌**: 点击手牌选择，点击"Play Cards"出牌
- **过牌**: 点击"Pass Turn"跳过当前回合
- **提示**: 点击"Get Hint"获取出牌建议
- **排序**: 点击"Sort Hand"或按空格键排序手牌

## 技术信息

### 服务器信息
- **地址**: http://localhost:8000
- **API文档**: http://localhost:8000/docs (自动生成的Swagger UI)
- **健康检查**: http://localhost:8000/health

### 默认配置
- **主机**: 0.0.0.0 (所有网络接口)
- **端口**: 8000
- **日志级别**: info

### 修改配置
可以通过环境变量修改配置：
```bash
# 修改端口
export PORT=8080
python main.py

# 修改主机
export HOST=127.0.0.1
python main.py

# 启用调试模式
export DEBUG=true
python main.py
```

## 获取帮助

如果遇到问题：
1. 首先运行诊断工具: `python diagnose_connection.py`
2. 查看服务器终端输出的错误信息
3. 检查浏览器控制台错误 (F12 → Console)
4. 确保所有依赖已安装: `pip install -r requirements.txt`

游戏现已完善，包含完整的前端交互和静态资源显示！