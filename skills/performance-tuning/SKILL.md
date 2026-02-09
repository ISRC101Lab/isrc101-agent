---
name: performance-tuning
description: "Profile and optimize latency, throughput, and memory usage for CLI/services/scripts with measurable before/after evidence. Use when users report slowness, high CPU/memory, long startup, or request performance optimization."
---

# Performance Tuning

## Workflow

1. 先测量：建立 baseline（耗时、峰值内存、吞吐）。
2. 找热点：用 profiling 或分段计时定位瓶颈。
3. 选策略：算法优先，其次 I/O、缓存、并发、批处理。
4. 小步改进：一次只做一类优化，便于归因。
5. 复测对比：给出 before/after 数据与副作用说明。

## Optimization Priorities

- 减少重复计算与重复 I/O。
- 降低不必要对象创建与拷贝。
- 对热点路径使用更低复杂度实现。
- 针对批量任务引入分块与并行（确保顺序语义不变）。

## Validation Rules

- 至少提供 1 组可复现 benchmark 命令。
- 报告性能提升比例（例如 -35% latency）。
- 明确是否影响可读性、内存占用或行为一致性。
