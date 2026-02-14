<p align="center">
  <img src="assets/banner.svg" alt="isrc101-agent banner" width="100%"/>
</p>

<p align="center">
  <strong>AI 编程助手，运行在你的终端中</strong><br/>
  受 Aider 和 Claude Code 启发，专为代码项目优化<br/>
  <strong>🚀 重大更新：多智能体协作系统现已上线！</strong>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> &nbsp;·&nbsp;
  <a href="#核心特性">特性</a> &nbsp;·&nbsp;
  <a href="#命令速查">命令</a> &nbsp;·&nbsp;
  <a href="#配置">配置</a> &nbsp;·&nbsp;
  <a href="#架构">架构</a>
</p>

---

## 🚀 重大更新：多智能体协作系统

**isrc101-agent v1.0** 引入了革命性的多智能体协作系统，支持：

- **四角色协作**：coder、reviewer、researcher、tester 专业分工
- **动态扩展**：支持创建多个相同角色的实例并行工作
- **128K上下文**：处理超长复杂任务，支持深度代码分析
- **智能任务分解**：自动将复杂任务分解为可并行执行的子任务
- **自动审查循环**：coder → reviewer → rework 质量保证流程
- **共享token预算**：200K tokens全局控制，防止资源耗尽

**使用示例**：
```bash
/crew 重构整个项目的用户认证模块，添加测试并审查代码质量
/crew 实现完整的支付系统，包括API、数据库和前端集成
/crew 优化项目性能，分析瓶颈并实施改进方案
```

## 快速开始

### 方法一：使用安装包（推荐）
```bash
git clone https://github.com/ISRC101Lab/isrc101-agent.git
cd isrc101-agent
bash setup.sh               # 一键安装（虚拟环境 + 依赖 + 配置）
source .venv/bin/activate
cd /path/to/your/project
isrc run
```

### 方法二：直接运行（无需安装）
```bash
git clone https://github.com/ISRC101Lab/isrc101-agent.git
cd isrc101-agent
python main.py run          # 使用项目根目录的main.py
# 或者
python run.py               # 使用便捷启动脚本
```

### 方法三：单次查询
```bash
# 使用安装包
isrc ask "帮我分析这个Python代码"

# 直接运行
python main.py ask "帮我分析这个Python代码"
```

## 核心特性

| 特性 | 说明 |
|------|------|
| **多模型切换** | DeepSeek V3/R1、Qwen3-VL、本地模型 (vLLM/llama.cpp)，`/model` 一键切换 |
| **精准编辑** | `str_replace` 精确替换 + Git 自动提交，不会破坏上下文 |
| **双模式** | `agent` 模式（读写 + 命令执行）/ `ask` 模式（只读分析与回答） |
| **多智能体协作** | `/crew` 启动 coder / reviewer / researcher / tester 四角色协作，自动分解任务、并行执行、代码审查，支持128K上下文和动态角色扩展 |
| **联网搜索** | Jina Reader 抓取 + Bing 搜索（免费、无需 API key），`/web on` 开启 |
| **技能系统** | `skills/*/SKILL.md` 可插拔工作流 — git-workflow · code-review · smart-refactor · python-bugfix |
| **并行工具调用** | 自动并行执行独立只读工具调用，减少往返轮数 |
| **纯文本输出** | 参考 Claude Code 设计，全程纯文本输出，流式渲染零延迟，无 markdown 符号干扰 |
| **Codex 风格 UI** | `/` 命令面板、fuzzy 匹配、低干扰配色 |

## 命令速查

| 命令 | 功能 | 命令 | 功能 |
|------|------|------|------|
| `/model` | 选择模型 | `/mode agent\|ask` | 切换模式 |
| `/skills` | 管理技能 | `/web on\|off` | 联网开关 |
| `/crew <task>` | **多智能体协作** | `/grounding` | 证据约束模式 |
| `/config` | 显示配置 | `/display` | 显示策略 |
| `/git` | Git 状态 | `/stats` | 会话统计 |
| `/reset` | 清空对话 | `/quit` | 退出 |

### 多智能体协作示例
```bash
/crew 重构用户认证模块，添加测试并审查代码质量
/crew 实现支付功能，包括API接口、数据库迁移和单元测试
/crew 优化项目性能，分析瓶颈并实施改进方案
```

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
use-unicode: true                    # 使用 Unicode 图标（false = ASCII 回退）

# Crew 多智能体配置
crew:
  max-parallel: 2              # 每个角色的最大并行实例数（1-8）
  token-budget: 200000         # 全 crew 共享 token 预算
  auto-review: true            # coder 产出自动送 reviewer 审查
  max-rework: 2                # 审查不通过时最大返工次数
  message-timeout: 60.0        # 消息总线超时（秒）
  # 角色配置示例
  roles:
    senior-coder:
      description: "高级开发工程师"
      instructions: "编写高质量、可维护的生产代码"
      mode: "agent"
      model-override: "deepseek-reasoner"
    security-reviewer:
      description: "安全审查专家"
      instructions: "专注于安全漏洞和最佳实践审查"
      mode: "ask"
      allowed-tools: ["read_file", "search_files"]
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
├── stream_renderer.py   纯文本流式渲染（零延迟直写 stdout）
├── rendering.py         工具结果 / diff / 面板渲染
├── ui.py                终端 UI（prompt_toolkit + rich）
├── crew/
│   ├── coordinator.py   任务分解 + 事件循环 + 结果综合
│   ├── worker.py        AgentWorker 线程（每角色独立 Agent 实例）
│   ├── roles.py         角色定义（coder / reviewer / researcher / tester）
│   ├── board.py         TaskBoard 线程安全状态机
│   ├── messages.py      MessageBus 跨智能体通信
│   ├── context.py       SharedTokenBudget 全局 token 预算
│   ├── tasks.py         CrewTask 和 TaskResult 数据定义
│   └── rendering.py     Crew 专用进度 / 摘要渲染
└── tools/
    ├── registry.py      工具注册表（dict-based, O(1) 分发）
    ├── file_ops.py      文件操作（read / write / str_replace）
    ├── git_ops.py       Git 操作（auto-commit）
    └── web_ops.py       联网（Jina Reader + Bing HTML 搜索）
```

**设计要点**

- **O(1) 工具调度** — dict 查找替代 match/case
- **模式隔离** — ask 模式自动过滤写入与命令执行工具
- **纯文本直出** — 模型输出纯文本，流式路径直写 stdout，非流式路径 `markup=False` 打印，无 markdown 解析开销
- **多智能体协作** — Coordinator 分解任务 → Worker 线程并行执行 → MessageBus 通信 → 可选 code review 循环
  - **动态角色扩展**：支持创建多个相同角色的实例并行工作
  - **共享token预算**：200K tokens全局预算控制
  - **128K上下文**：支持超长对话和复杂任务
  - **自动审查循环**：coder → reviewer → rework 质量保证流程
- **Web 策略** — system prompt 引导 LLM 先搜后 fetch，严格基于抓取内容回复

## 技术栈

```
Python >= 3.10
litellm · rich · click · prompt_toolkit · pyyaml · requests · tiktoken · python-dotenv
```


## Roadmap

- [ ] 上下文压缩 — 长对话自动摘要，降低 token 消耗
- [ ] MCP 协议 — 接入 Model Context Protocol，扩展外部工具生态
- [ ] RAG 集成 — 项目级向量索引，大型代码库精准检索
- [x] **多智能体协作** — `/crew` 四角色协作系统（coder / reviewer / researcher / tester）
  - ✅ 动态角色扩展：支持创建多个相同角色的实例
  - ✅ 128K上下文支持：处理超长复杂任务
  - ✅ 共享token预算：200K tokens全局控制
  - ✅ 自动审查循环：coder → reviewer → rework 质量保证
- [ ] 多模型混合 — reasoner 规划 + chat 执行的双模型流水线

## 许可证

[MIT License](LICENSE)
