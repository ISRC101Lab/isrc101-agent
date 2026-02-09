# isrc101-agent

AI 编程助手，运行在你的终端中。受 Aider 和 Claude Code 启发，专为代码项目优化。

## 快速开始

```bash
git clone https://github.com/ISRC101Lab/isrc101-agent.git
cd isrc101-agent
bash setup.sh          # 一键安装（虚拟环境 + 依赖 + 配置）
source .venv/bin/activate
cd /path/to/your/project
isrc run
```

## 特性

- **多模型**: DeepSeek V3/R1、本地模型 (vLLM/llama.cpp)，`/model` 快速切换
- **精准编辑**: `str_replace` 精确替换 + Git 自动提交
- **三种模式**: `code`（读写+命令）/ `ask`（只读分析）/ `architect`（架构规划）
- **联网搜索**: Jina Reader 抓取 + DuckDuckGo（免费）/ Tavily（AI 优化），`/web on` 开启
- **技能系统**: `skills/*/SKILL.md` 可插拔工作流（git-workflow、code-review、smart-refactor、python-bugfix）
- **Codex 风格**: `/` 命令面板、fuzzy 匹配、低干扰配色

## 命令速查

```
/model              选择模型          /mode code|ask|architect  切换模式
/skills             管理技能          /web on|off               联网开关
/config             显示配置          /display                  显示策略
/git                Git 状态          /stats                    会话统计
/reset              清空对话          /quit                     退出
```

## 配置

配置文件优先级：`./.agent.conf.yml`（项目级）> `~/.isrc101-agent/config.yml`（全局）

```yaml
# 关键配置项
reasoning-display: summary   # off | summary | full
web-display: brief           # brief | summary | full
answer-style: concise        # concise | balanced | detailed
api-key-env: DEEPSEEK_API_KEY  # 从环境变量读取密钥（推荐）
```

> ⚠️ 不要将 API 密钥提交到版本控制，使用 `api-key-env` 从环境变量读取。

## 技术栈

Python >= 3.10 | litellm · rich · click · prompt_toolkit · requests · ddgs · python-dotenv

可选：`pip install isrc101-agent[tavily]`（Tavily AI 搜索）

## 架构

```
isrc101_agent/
├── main.py            # CLI 入口 (click)
├── agent.py           # 对话循环 + tool call 调度
├── llm.py             # LLM 适配层 (litellm) + system prompt
├── config.py          # 配置加载（YAML + 环境变量）
├── command_router.py  # / 命令路由（dict dispatch）
├── skills.py          # 技能发现与 prompt 注入
├── ui.py              # 终端 UI（prompt_toolkit + rich）
└── tools/
    ├── registry.py    # 工具注册表（dict-based dispatch）
    ├── file_ops.py    # 文件操作（read/write/str_replace）
    ├── git_ops.py     # Git 操作（auto-commit）
    └── web_ops.py     # 联网（Jina Reader + DDG/Tavily）
```

- **工具调度**: dict 查找替代 match/case，O(1) 分发
- **模式隔离**: ask/architect 模式自动过滤写入工具
- **Web 策略**: system prompt 引导 LLM 先搜后 fetch，严格基于抓取内容回复
- **流式输出**: 支持 ultra/fast/normal 三档 stream profile

## 未来展望

- [ ] **多轮 tool call**: 支持单轮返回多个 tool call（parallel function calling）
- [ ] **上下文压缩**: 长对话自动摘要，降低 token 消耗
- [ ] **MCP 协议**: 接入 Model Context Protocol，扩展外部工具生态
- [ ] **RAG 集成**: 项目级向量索引，大型代码库精准检索
- [ ] **多模型协作**: reasoner 规划 + chat 执行的双模型工作流

## 许可证

MIT License
