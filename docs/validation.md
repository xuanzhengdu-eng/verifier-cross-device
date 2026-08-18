# 验证记录

## 验证范围

2026-08-18，项目使用一个 NVIDIA H20 Reference 评测服务和两个 Target 评测服务
完成运行时 Reference 流程验证：

- MUSA Target 使用摩尔线程 FlagGems 后端；
- Ascend Target 使用 Ascend FlagGems 后端。

同一 case 的所有评测服务读取相同的 KS3 输入。H20 执行该问题的 `reference.py`，
两个 Target 分别执行 [`examples/kernels`](../examples/kernels/README.md) 中的平台实现。
正确性基线是同一 job 内 H20 实际产生的输出。

## 验证结果

验证覆盖五个问题，每个问题执行全部四个数据集 case，共产生 20 次 Reference 执行
和 40 次独立的 Target 正确性检查。

| Problem | Cases | MUSA | Ascend | Reference p50 | MUSA p50 | Ascend p50 |
|---|---:|---:|---:|---:|---:|---:|
| `activation_norm/relu2` | 4 | 4/4 PASS | 4/4 PASS | 0.0357–0.0548 ms | 0.2781–0.2903 ms | 0.5925–0.6029 ms |
| `activation_norm/silu_and_mul` | 4 | 4/4 PASS | 4/4 PASS | 0.0500–0.0512 ms | 0.2086–0.4039 ms | 0.6678–0.6819 ms |
| `activation_norm/l2norm` | 4 | 4/4 PASS | 4/4 PASS | 0.0574–0.0644 ms | 0.3070–0.6724 ms | 1.1653–1.1936 ms |
| `elementwise/add3` | 4 | 4/4 PASS | 4/4 PASS | 0.0191–0.0195 ms | 0.3620–0.3729 ms | 0.5176–0.5279 ms |
| `elementwise/add_constant` | 4 | 4/4 PASS | 4/4 PASS | 0.0141–0.0148 ms | 0.1178–0.2145 ms | 0.2846–0.2881 ms |

最终结果为：**40/40 Target 检查通过，Reference 执行失败数为 0**。

## 结果解释

上述结果证明了真实设备执行和平台 FlagGems Kernel 可以完成端到端跨设备验证。这些
示例 Target 在当前小规模输入上的耗时高于 H20 Reference，因此不能表述为性能优化
成果。框架保留并如实报告该结果，不会将正确性冒烟 Kernel 包装为性能领先实现。

性能数据与运行环境相关。复现时需要保持输入数据集、设备软件栈、warmup 次数、
iteration 次数和 solution 源码一致。
