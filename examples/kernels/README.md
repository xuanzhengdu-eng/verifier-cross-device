# 跨设备 Kernel 示例

本目录提供可直接用于运行时 Reference 流程的示例。每个问题采用相同的文件结构：

```text
<category>/<problem>/
├── reference.py  # Reference 评测服务运行的可信 PyTorch 实现
├── musa.py       # 调用摩尔线程 FlagGems 后端的 MUSA 实现
├── ascend.py     # 调用 Ascend FlagGems 后端的实现
└── test_*.py     # 四角色 pytest 定义
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

## 四角色 pytest

每个 `test_*.py` 保持相同的四个角色：

1. `input_build(config)`：构造该 case 的关键字参数；
2. `compute_ref(**inputs)`：执行可信 reference；
3. `compute_res(**inputs)`：执行当前待测实现；
4. `compare(ref_out, res_out)`：定义该算子的正确性规则。

测试调用 `vcd.operator_test.run_local_case`，并使用 `LocalStorage` 完成输入和输出的
写入、读取以及 safetensors 编解码。因此本地测试和跨机器评测共享数据协议，而不是
维护一套只用于 pytest 的旁路格式。

CPU 本地开发默认用 `reference.py` 作为待测实现，以检查四角色、存储和序列化流程：

```bash
python3 -m pip install -e '.[test]'
python3 -m pytest examples/kernels/elementwise/add3/test_add3.py
```

在对应国产设备环境中设置 backend 后，pytest 会加载同目录的平台实现：

```bash
VCD_TEST_BACKEND=musa VCD_TEST_DEVICE=musa:0 \
  python3 -m pytest examples/kernels/elementwise/add3/test_add3.py

VCD_TEST_BACKEND=ascend VCD_TEST_DEVICE=npu:0 \
  python3 -m pytest examples/kernels/elementwise/add3/test_add3.py
```

新增算子时复制任意一个目录的结构、实现上述四个角色并声明 `COMBOS` 即可。四角色
pytest 也可以直接交给跨机 Controller：

```bash
vcd-controller run \
  --config examples/run.four-role.local.json \
  --module examples.kernels.elementwise.add3.test_add3 \
  --test test_add3 \
  --problem-key elementwise/add3 \
  --report reports/add3.json
```

任务配置为 reference 和每个 target 指定对应 solution。Controller 在跨机模式下自动
装配四个角色：`input_build` 将输入写入配置的 Storage，`compute_ref/compute_res` 分发
到评测服务，`compare` 在 Controller 比较结果。评测服务可以保持通用启动方式，不必
为每个算子修改服务代码。
