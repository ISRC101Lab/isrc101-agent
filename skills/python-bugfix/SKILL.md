---
name: python-bugfix
description: "Diagnose and fix Python runtime/import/type/logic failures with minimal diffs and reproducible verification. Use when tasks mention Traceback, failing scripts/tests, exceptions, regressions, or broken CLI behavior."
---

# Python Bugfix

## Workflow

1. 复现问题：先运行最小复现命令，记录报错栈、输入和环境。
2. 定位根因：优先看第一处真实异常，而不是最后一层包装错误。
3. 最小修复：只改导致失败的逻辑，避免顺手重构。
4. 回归验证：至少验证复现场景，再验证一个相邻路径。
5. 交付说明：明确根因、改动点、验证命令、残留风险。

## Bugfix Rules

- 不要用“吞异常”掩盖错误（避免裸 `except:`）。
- 优先修复输入校验、状态一致性、边界条件和空值分支。
- 修改接口行为时，保持向后兼容或明确给出迁移说明。
- 涉及配置读取时，给出清晰错误信息与修复提示。

## Verification Checklist

- 复现命令在修复前失败、修复后通过。
- 与改动相关的单测或脚本已运行。
- 未引入新的 lint/语法错误。
- 输出对用户可读，包含下一步建议。
