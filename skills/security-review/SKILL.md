---
name: security-review
description: "Perform practical application security review for code changes and existing modules. Use when users ask for vulnerability analysis, secure coding checks, secret leakage review, command execution safety, or threat-focused hardening."
---

# Security Review

## Workflow

1. 明确边界：识别输入面、执行面、存储面、网络面。
2. 快速筛查：优先看高风险点（命令执行、反序列化、路径拼接、鉴权）。
3. 深入验证：给出可复现思路或最小 PoC 级描述。
4. 风险分级：按 High/Medium/Low 说明影响与利用条件。
5. 修复建议：提供最小可实施补丁与回归验证建议。

## Review Checklist

- 输入校验与输出编码是否完整。
- 文件操作是否存在路径穿越。
- shell/子进程调用是否有注入面。
- 配置/日志是否泄露密钥或隐私数据。
- 权限边界是否被绕过（模式、角色、命令黑白名单）。

## Reporting Format

- `Finding`: 一句话问题定义。
- `Risk`: High/Medium/Low。
- `Evidence`: 文件与触发路径。
- `Fix`: 最小修复建议。
- `Validation`: 如何验证修复有效。
