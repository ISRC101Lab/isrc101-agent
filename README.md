# isrc101-agent

AI 编程助手，运行在你的终端中。受 Aider 和 Claude Code 启发，专为代码项目优化。

## 快速开始

```bash
# 克隆项目
git clone https://github.com/ISRC101Lab/isrc101-agent.git
cd isrc101-agent

# 一键安装
bash setup.sh

# 激活虚拟环境
source .venv/bin/activate

# 进入你的项目目录
cd /path/to/your/project

# 启动助手
isrc run
```

`setup.sh` 脚本会自动处理所有依赖：创建虚拟环境、安装包、生成配置文件。

## 核心特性

### 🤖 智能模型支持
- **DeepSeek 优先**: 深度集成 DeepSeek V3 Chat 和 R1 Reasoner
- **本地模型**: 支持 vLLM / llama.cpp 等本地部署
- **交互式选择**: `/model` 命令快速切换模型
- **长响应支持**: 默认 4096 tokens，可按模型单独调高

### 💻 精准代码操作
- **安全编辑**: `str_replace` 精确替换，避免意外修改
- **智能浏览**: 自动调整目录深度，高效查看项目结构
- **代码搜索**: 正则表达式搜索，快速定位代码
- **Git 集成**: 自动提交修改，记录 AI 协作历史

### 🎯 三种工作模式
- **code 模式** (默认): 读写文件 + 执行命令，完整编程协助
- **ask 模式**: 只读分析，安全查看和理解代码
- **architect 模式**: 架构讨论和规划，不修改文件

### 🧭 Codex 风格交互
- **极简状态栏**: 启动信息采用无框状态行，降低视觉噪音
- **命令面板**: 输入 `/` 即弹出双列命令面板（方向键选择）
- **智能匹配**: 支持前缀 + fuzzy 匹配（例如 `/wb` 命中 `/web`）
- **低干扰配色**: 弱对比高亮与紧凑排版，长时间使用更舒适
- **更窄行高**: `/model` 与 `/skills` 选择器使用统一紧凑行距与对齐规则
- **选择器一致性**: `/model` 与 `/skills` 共享同一套无框交互与键位

### ⚙️ 灵活配置
- **项目级配置**: `.agent.conf.yml` 覆盖全局设置
- **技能系统**: `skills/*/SKILL.md` 提供可插拔专业工作流
- **环境变量**: API 密钥安全管理

## 常用命令

```
# 模型管理
/model              交互式选择模型 (↑↓ Enter)
/model list         表格显示所有可用模型
/model add ...      添加新模型预设
/model rm <n>       删除模型预设

# Skills 管理
/skills             交互式选择技能 (Space 开关, Enter 保存)
/skills list        查看可用技能与启用状态
/skills on <name>   启用技能
/skills off <name>  禁用技能
/skills clear       清空所有技能

# 模式切换
/mode code          切换到代码编辑模式
/mode ask           切换到只读分析模式
/mode architect     切换到架构讨论模式

# 系统命令
/config             显示当前配置
/web                切换联网抓取开关（web_fetch）
/web on brief       开启联网并使用极简显示（推荐）
/web on summary     开启联网并使用摘要显示
/web on full        开启联网并显示完整抓取内容
/display            查看当前 thinking/web 显示策略
/display thinking off|summary|full
/display web brief|summary|full
/display answer concise|balanced|detailed
/git                查看 Git 状态和提交历史
/stats              显示会话统计信息
/reset              清空当前对话
/help               显示帮助信息
/quit               退出程序
```


退出保护：在交互模式下需要连续按两次 `Ctrl-D` 才会退出，避免误触。

## 配置说明

### 默认模型配置
项目预配置了以下模型模板：

1. **local** (默认激活)
   - 提供商: local
   - 模型: openai/model
   - 描述: 本地模型 (vLLM / llama.cpp)
   - API: http://localhost:8080/v1 (默认本地地址)

2. **deepseek-chat**
   - 提供商: DeepSeek
   - 模型: deepseek/deepseek-chat
   - 描述: DeepSeek V3 Chat，通用对话模型
   - 需要配置: 你的 DeepSeek API 密钥

3. **deepseek-reasoner**
   - 提供商: DeepSeek
   - 模型: deepseek/deepseek-reasoner
   - 描述: DeepSeek R1 Reasoner，推理专用模型
   - 需要配置: 你的 DeepSeek API 密钥

### 配置文件位置
1. **项目级配置**: `./.agent.conf.yml` (优先使用)
2. **全局配置**: `~/.isrc101-agent/config.yml` (备用)

### Skills 配置示例
```yaml
skills-dir: skills
enabled-skills:
  - python-bugfix
  - performance-tuning
  - test-designer
  - openai-docs
  - gh-address-comments
  - gh-fix-ci
  - playwright
```

内置高价值技能（`./skills`，优先 OpenAI 官方）：
- `python-bugfix`: Python 报错定位与最小修复
- `test-designer`: 高信号测试设计与回归用例
- `performance-tuning`: 性能剖析与优化闭环
- `openai-docs`: OpenAI 官方文档检索与权威引用（实时）
- `gh-address-comments`: 自动化处理 PR review comments 并回填修复
- `gh-fix-ci`: 定位并修复 GitHub Actions 失败项
- `playwright`: 真实浏览器自动化验证与调试

### 自定义配置
编辑 `.agent.conf.yml` 文件可以：
- 修改默认模型
- 调整响应长度 (`max-tokens`)
- 设置 API 密钥（使用环境变量更安全）
- 启用/禁用自动提交
- 配置命令超时时间
- 配置技能目录与默认启用技能（`skills-dir`, `enabled-skills`）
- 配置显示压缩策略（`reasoning-display`, `web-display`）
- 配置 web 预览预算（`web-preview-lines`, `web-preview-chars`, `web-context-chars`）

显示压缩推荐配置：

```yaml
reasoning-display: summary   # off | summary | full
web-display: brief           # brief | summary | full
answer-style: concise        # concise | balanced | detailed
web-preview-lines: 2         # 终端展示最多行数
web-preview-chars: 220       # 终端展示最多字符
web-context-chars: 4000      # 写入上下文的 web 内容上限
```

### ⚠️ 安全提示
1. **不要提交 API 密钥到版本控制**
2. **使用环境变量管理敏感信息**
3. **项目配置文件已使用占位符，请替换为你的实际密钥**
4. **建议使用 `api-key-env` 配置项从环境变量读取密钥**

### 环境变量配置示例
```yaml
deepseek-chat:
  provider: deepseek
  model: deepseek/deepseek-chat
  description: DeepSeek V3 Chat
  temperature: 0.0
  max-tokens: 4096
  api-base: https://api.deepseek.com
  api-key-env: DEEPSEEK_API_KEY  # 从环境变量读取
```

然后在 shell 中设置环境变量：
```bash
export DEEPSEEK_API_KEY="your-actual-api-key-here"
```

## 最佳实践

### 1. 项目初始化
```bash
# 在新项目中创建配置文件
cp ~/.isrc101-agent/config.yml ./.agent.conf.yml

# 编辑项目特定配置
vim ./.agent.conf.yml
```

### 2. 工作流程
1. **探索阶段**: 使用 `list_directory` 了解项目结构
2. **分析阶段**: 使用 `read_file` 查看关键代码
3. **修改阶段**: 使用 `str_replace` 精确编辑
4. **验证阶段**: 运行测试或重新读取文件确认修改

## 技术栈

- **Python**: >= 3.10
- **核心依赖**:
  - `litellm`: 多模型接口统一
  - `rich`: 终端美化输出
  - `click`: 命令行界面
  - `prompt_toolkit`: 交互式提示
  - `gitpython`: Git 操作集成
  - `python-dotenv`: 环境变量管理

## 许可证

MIT License - 详见 LICENSE 文件

## 贡献

欢迎提交 Issue 和 Pull Request！
