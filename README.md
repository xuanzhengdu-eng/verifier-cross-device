# verifier-cross-device

`verifier-cross-device` 是一个面向异构加速设备的 Kernel 正确性与性能验证系统。系统在 reference 设备上运行参考实现，在一个或多个 target 设备上运行平台特化实现，并对同一测试输入下的输出和执行时延进行统一分析。

当前测试环境包含 NVIDIA、摩尔线程和华为 Ascend 设备。系统架构不限定厂商或节点数量；新增设备只需部署相同的评测服务，并在任务配置中增加 target。

## 核心流程

```text
                              ┌─ Reference evaluator ─ reference.py
Dataset ─ Object Storage ─────┼─ Target evaluator A ─ platform_a.py
                              ├─ Target evaluator B ─ platform_b.py
                              └─ Target evaluator N ─ platform_n.py
                                           │
Controller ───────── HTTP control ──────────┘
     │
     └─ correctness results, latency statistics, speedup report
```

对于每个测试 case：

1. 所有评测服务读取同一份输入；
2. reference 评测服务执行 `reference.py`，产生本次验证的参考输出和参考时延；
3. target 评测服务并发执行各自的平台特化实现；
4. Controller 将每个 target 输出与本次 reference 输出比较；
5. Controller 计算 `reference p50 / target p50`，并生成结构化报告。

对象存储中的输入由 manifest 管理。预生成输出不作为本流程的最终正确性基线；正确性基线来自本次 reference 实际执行结果。

## 系统组成

- `vcd-controller`：读取任务配置、调度各评测服务、比较结果并生成报告；
- `vcd-evaluator`：在指定设备上加载输入、执行实现并记录同步后的时延；
- `storage`：提供 KS3 和本地存储适配；
- `vcd.dataset_format`：提供 safetensors 数据集协议；
- `vcd.checks`：提供 standard、exact 和 mismatch-fraction 检查策略；
- `deploy`：提供评测容器克隆、服务守护和设备探测工具。

同一份代码安装在 Controller 和所有评测节点。节点角色、设备类型和任务关系完全由启动参数与任务配置决定。

## 支持的运行时

设备发现和同步计时目前支持：

- NVIDIA CUDA：`cuda:N`；
- 摩尔线程 MUSA：`musa:N`；
- 华为 Ascend：`npu:N`；
- CPU：`cpu`，主要用于开发和回归测试。

评测服务接口与具体厂商解耦，可继续增加其他运行时适配。

## 安装

Python 版本要求为 3.10 或更高。

普通环境：

```bash
python3 -m pip install -e .
```

设备环境应优先使用厂商提供的 PyTorch 发行版。若依赖已由设备镜像提供，可避免重新解析依赖：

```bash
python3 -m pip install -e /opt/verifier-cross-device --no-deps
```

## 启动评测服务

所有评测节点使用相同命令，仅修改 backend 和 device：

```bash
vcd-evaluator \
  --backend cuda \
  --device cuda:0 \
  --host 0.0.0.0 \
  --port 9100 \
  --storage-config /etc/vcd/storage.json \
  --allow-solution-code \
  --require-auth
```

常用运行时参数：

| 运行时 | `--backend` | `--device` 示例 |
|---|---|---|
| NVIDIA CUDA | `cuda` | `cuda:0` |
| 摩尔线程 MUSA | `musa` | `musa:0` |
| 华为 Ascend | `ascend` | `npu:0` |

执行外部 solution 必须在隔离的评测环境中启用。生产环境应同时配置服务鉴权、网络访问控制和最小权限对象存储凭证。

## 运行验证任务

复制并修改 [任务配置模板](config/run.example.json)，配置一个 reference 和任意数量 targets：

```bash
cp config/run.example.json config/run.internal.json
```

```bash
vcd-controller dataset-run \
  --config config/run.internal.json \
  --problem activation_norm/relu2 \
  --case 0 \
  --op reference \
  --report reports/relu2.json
```

报告包含：

- reference 和每个 target 的设备信息；
- p20、p50、p80、mean 和迭代次数；
- 每个 target 的正确性结论与误差指标；
- 每个 target 相对 reference 的加速比。

## 测试

```bash
python3 -m pip install -e '.[test]'
python3 -m pytest
CUDA_VISIBLE_DEVICES='' python3 -m unittest discover -s tests -v
CUDA_VISIBLE_DEVICES='' python3 examples/run_local_poc.py
CUDA_VISIBLE_DEVICES='' python3 examples/run_cross_poc.py
```

仓库还提供五组真实设备示例，包含 PyTorch reference、MUSA FlagGems 实现和
Ascend FlagGems 实现，见 [Kernel 示例](examples/kernels/README.md)。已完成的
三端验证范围和结果见 [验证记录](docs/validation.md)。

## 文档

- [系统设计](docs/design.md)
- [任务配置](docs/configuration.md)
- [部署与运行](docs/deployment.md)
- [文件说明](docs/files.md)
- [验证记录](docs/validation.md)

## Roadmap

- [ ] **GPU 管理**：agent 侧增加多卡管理（单机多 GPU 的空闲/busy 追踪、进程级隔离）+ 多机管理（controller 侧按 backend 感知哪台机器可用）；目前 PoC 是固定 run.json 绑定，一 backend 对应一个 agent 地址。
- [ ] **input_build 模式**：支持两种模式——每次重新生成新输入（当前行为）、复用 storage 中已有的输入包（跳过 input_build，直接用已物化的 artifact）；适合多次跑同一组输入对比不同 solution。
