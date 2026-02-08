# DeepSeek API 配置指南

## 问题诊断

你遇到的错误：
```
Authentication Fails, Your api key: ****HERE is invalid
```

这是因为 DeepSeek 模型的 API 密钥配置不正确。

## 解决方案

### 方法 1：使用环境变量（推荐）

```bash
# 1. 设置 DeepSeek API 密钥
export DEEPSEEK_API_KEY="你的实际 DeepSeek API 密钥"

# 2. 激活虚拟环境
source .venv/bin/activate

# 3. 运行 isrc101-agent
isrc run

# 4. 切换到 DeepSeek 模型
/model deepseek-chat
/model deepseek-reasoner
```

### 方法 2：直接修改配置文件

```bash
# 1. 编辑配置文件
vim .agent.conf.yml

# 2. 找到 deepseek-chat 和 deepseek-reasoner 配置
# 将 api-key-env: DEEPSEEK_API_KEY 改为 api-key: 你的实际密钥

# 3. 保存并运行
isrc run
```

### 方法 3：使用配置脚本

```bash
# 运行配置脚本
bash setup_deepseek.sh 你的实际 DeepSeek API 密钥

# 然后运行
isrc run
```

## 获取 DeepSeek API 密钥

1. 访问 [DeepSeek 平台](https://platform.deepseek.com/)
2. 注册账号
3. 进入 API Keys 页面
4. 创建新的 API Key
5. 复制密钥并按照上述方法配置

## DeepSeek 模型特点

### deepseek-chat
- **模型**: deepseek/deepseek-chat
- **用途**: 通用对话和代码生成
- **特点**: 速度快，适合日常编程任务

### deepseek-reasoner
- **模型**: deepseek/deepseek-reasoner
- **用途**: 推理和复杂问题解决
- **特点**: 思考过程更深入，但速度较慢
- **注意**: 不支持工具调用（tools）

## 验证配置

运行配置检查脚本：

```bash
python check_config.py
```

应该看到 DeepSeek 模型的 API Key 状态为 `✓`。

## 常见问题

### Q: 为什么 DeepSeek Reasoner 不支持工具？
A: DeepSeek Reasoner 模型目前不支持 function calling，所以代码中已经做了特殊处理，自动移除 tools 参数。

### Q: API 密钥安全吗？
A: 使用环境变量是最安全的方式，不会将密钥写入配置文件。

### Q: 配置后还是报错怎么办？
A: 请检查：
1. API 密钥是否正确
2. 网络连接是否正常
3. DeepSeek 服务是否可用
4. 运行 `python check_config.py` 查看详细诊断信息

## 技术细节

### 代码中的特殊处理

1. **DeepSeek Reasoner**:
   - 自动检测模型名称
   - 移除 tools 参数
   - 处理 reasoning_content 格式

2. **错误处理**:
   - 认证错误：提示检查 API 密钥
   - 连接错误：提示检查网络和 API Base
   - Reasoning 错误：自动调整消息格式

### 配置文件格式

```yaml
deepseek-chat:
  provider: deepseek
  model: deepseek/deepseek-chat
  description: DeepSeek V3 Chat
  temperature: 0.0
  max-tokens: 8192
  api-base: https://api.deepseek.com
  api-key-env: DEEPSEEK_API_KEY  # 推荐使用环境变量
  # 或者: api-key: 你的实际密钥

deepseek-reasoner:
  provider: deepseek
  model: deepseek/deepseek-reasoner
  description: DeepSeek R1 Reasoner
  temperature: 0.0
  max-tokens: 8192
  api-base: https://api.deepseek.com
  api-key-env: DEEPSEEK_API_KEY  # 推荐使用环境变量
  # 或者: api-key: 你的实际密钥
```

## 下一步

配置完成后，你可以：

1. 启动 isrc101-agent
2. 使用 `/model deepseek-chat` 切换到聊天模型
3. 使用 `/model deepseek-reasoner` 切换到推理模型
4. 开始编程任务！