# verifier-cross-device

跨机算子验证框架（cross-backend operator verifier）—— 把 KernelGenBench 的算子题目搬到多台异构硬件
（NVIDIA / Ascend / AMD ...）上做**跨硬件正确性 + 性能验证**：以某设备上的参考实现为 reference，
各设备各自的 solution 为 res，统一比较数值差异 + 运行耗时。

设计文档见 [`docs/design.md`](docs/design.md)。

## 结构

- `vcd/` —— 框架核心（KGB-agnostic）：4 角色装配（autowire）、执行上下文（VCD_MODE）、cross 编排、比较记录。
- `agent/` —— 执行 server（`/execute`）。
- `storage/` —— 数据面抽象 + 本地后端 + safetensors 序列化。
- `examples/` —— PoC 题目（`test_addmm.py`）与跑测脚本。

## 跑 PoC

```bash
# local（单机，无网络）
python examples/run_local_poc.py

# cross（同机起 3 个 agent 模拟 nvidia/amd/ascend；需要能 bind 本地端口）
python examples/run_cross_poc.py
```

> 需要 `torch`、`safetensors`、`fastapi`、`uvicorn`、`requests`，以及 `KernelGenBench/src` 在 `PYTHONPATH`。

## Roadmap

- [ ] **GPU 管理**：agent 侧增加多卡管理（单机多 GPU 的空闲/busy 追踪、进程级隔离）+ 多机管理（controller 侧按 backend 感知哪台机器可用）；目前 PoC 是固定 run.json 绑定，一 backend 对应一个 agent 地址。
