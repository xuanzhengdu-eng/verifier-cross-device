# 跨设备 Kernel 示例

本目录提供可直接用于运行时 Reference 流程的示例。每个问题采用相同的文件结构：

```text
<category>/<problem>/
├── reference.py  # Reference 评测服务运行的可信 PyTorch 实现
├── musa.py       # 调用摩尔线程 FlagGems 后端的 MUSA 实现
└── ascend.py     # 调用 Ascend FlagGems 后端的实现
```

平台文件直接调用 FlagGems 算子，不启用全局 PyTorch monkey patch。这样可以明确
被计时的实现，并避免修改长时间运行的评测服务中的其他 PyTorch 操作。

示例覆盖：

- `activation_norm/relu2`；
- `activation_norm/silu_and_mul`；
- `activation_norm/l2norm`；
- `elementwise/add3`；
- `elementwise/add_constant`。

这些代码用于验证任务调度、数据传输、正确性比较、设备同步和报告生成。项目不将
它们声明为对应设备上的最优实现。正式性能优化应使用经过调优的平台 Kernel 替换
相应文件，并保持函数签名不变。
