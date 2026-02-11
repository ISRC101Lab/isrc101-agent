<p align="center">
  <img src="assets/banner.svg" alt="isrc101-agent banner" width="100%"/>
</p>

<p align="center">
  <strong>AI 编程助手，运行在你的终端中</strong><br/>
  受 Aider 和 Claude Code 启发，专为代码项目优化
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> &nbsp;·&nbsp;
  <a href="#核心特性">特性</a> &nbsp;·&nbsp;
  <a href="#命令速查">命令</a> &nbsp;·&nbsp;
  <a href="#配置">配置</a> &nbsp;·&nbsp;
  <a href="#架构">架构</a>
</p>

---

## 快速开始

```bash
git clone https://github.com/ISRC101Lab/isrc101-agent.git
cd isrc101-agent
bash setup.sh               # 一键安装（虚拟环境 + 依赖 + 配置）
source .venv/bin/activate
cd /path/to/your/project
isrc run
```

## 核心特性

| 特性 | 说明 |
|------|------|
| **多模型切换** | DeepSeek V3/R1、Qwen3-VL、本地模型 (vLLM/llama.cpp)，`/model` 一键切换 |
| **精准编辑** | `str_replace` 精确替换 + Git 自动提交，不会破坏上下文 |
| **双模式** | `agent` 模式（读写 + 命令执行）/ `ask` 模式（只读分析与回答） |
| **联网搜索** | Jina Reader 抓取 + Bing 搜索（免费、无需 API key），`/web on` 开启 |
| **技能系统** | `skills/*/SKILL.md` 可插拔工作流 — git-workflow · code-review · smart-refactor · python-bugfix |
| **并行工具调用** | 自动并行执行独立只读工具调用，减少往返轮数 |
| **Codex 风格 UI** | `/` 命令面板、fuzzy 匹配、低干扰配色 |

## 命令速查

| 命令 | 功能 | 命令 | 功能 |
|------|------|------|------|
| `/model` | 选择模型 | `/mode agent\|ask` | 切换模式 |
| `/skills` | 管理技能 | `/web on\|off` | 联网开关 |
| `/grounding` | 证据约束模式 | `/grounding off` | 关闭证据门禁 |
| `/config` | 显示配置 | `/display` | 显示策略 |
| `/git` | Git 状态 | `/stats` | 会话统计 |
| `/reset` | 清空对话 | `/quit` | 退出 |

```bash
# 性能调优
/display tools 6    # 设置并行工具调用上限（1-12）
```

## 配置

配置文件优先级：`./.agent.conf.yml`（项目级）> `~/.isrc101-agent/config.yml`（全局）

```yaml
# 关键配置项
reasoning-display: summary          # off | summary | full
web-display: brief                  # brief | summary | full
answer-style: concise               # concise | balanced | detailed
grounded-web-mode: strict           # off | strict
grounded-retry: 1                   # 0-3, 校验失败自动重试次数
grounded-visible-citations: sources_only  # sources_only | inline
grounded-context-chars: 8000        # 800-40000, 证据上下文预算
tool-parallelism: 4                 # 1-12, 并行工具调用数
api-key-env: DEEPSEEK_API_KEY       # 从环境变量读取密钥（推荐）
```

> **安全提醒**：不要将 API 密钥提交到版本控制，使用 `api-key-env` 从环境变量读取。

## 架构

```
isrc101_agent/
├── main.py              CLI 入口 (click)
├── agent.py             对话循环 + tool call 调度
├── llm.py               LLM 适配层 (litellm) + system prompt
├── config.py            配置加载（YAML + 环境变量）
├── command_router.py    / 命令路由（dict dispatch）
├── skills.py            技能发现与 prompt 注入
├── ui.py                终端 UI（prompt_toolkit + rich）
└── tools/
    ├── registry.py      工具注册表（dict-based, O(1) 分发）
    ├── file_ops.py      文件操作（read / write / str_replace）
    ├── git_ops.py       Git 操作（auto-commit）
    └── web_ops.py       联网（Jina Reader + Bing HTML 搜索）
```

**设计要点**

- **O(1) 工具调度** — dict 查找替代 match/case
- **模式隔离** — ask 模式自动过滤写入与命令执行工具
- **Web 策略** — system prompt 引导 LLM 先搜后 fetch，严格基于抓取内容回复
- **流式输出** — 支持 stable / smooth / ultra 三档 stream profile

## 技术栈

```
Python >= 3.10
litellm · rich · click · prompt_toolkit · pyyaml · requests · tiktoken · python-dotenv
```


## Roadmap

- [ ] 上下文压缩 — 长对话自动摘要，降低 token 消耗
- [ ] MCP 协议 — 接入 Model Context Protocol，扩展外部工具生态
- [ ] RAG 集成 — 项目级向量索引，大型代码库精准检索
- [ ] 多模型协作 — reasoner 规划 + chat 执行的双模型工作流

## 许可证

[MIT License](LICENSE)
