---
name: test-designer
description: "Design focused, high-signal tests for new features and bugfixes across unit/integration/CLI levels. Use when users ask to add tests, prevent regressions, improve coverage, or validate edge cases."
---

# Test Designer

## Workflow

1. 锁定目标行为：先明确“预期输入/输出/副作用”。
2. 选测试层级：单元优先，必要时补集成或 CLI 测试。
3. 设计样例：覆盖 happy path、边界、错误分支。
4. 执行与迭代：先跑最小相关测试，再扩大范围。
5. 保持稳定：避免脆弱断言和与实现细节强耦合。

## Test Design Rules

- 每个测试只验证一个核心行为。
- 名称使用 `test_<when>_<then>` 风格，便于定位。
- 失败信息应直接指出原因。
- Mock 只用于外部依赖，不 mock 业务核心。

## Coverage Strategy

- 新增功能：至少 1 个正向 + 1 个边界。
- 修复缺陷：必须有回归用例（修复前失败、修复后通过）。
- 配置/CLI：覆盖无效参数和缺省参数路径。
