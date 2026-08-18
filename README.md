# verifier-cross-device

跨机器 Kernel 正确性与性能验证服务。Controller 运行在 `10.0.9.5`，通过 HTTP 调用国产设备 Agent；输入、golden output 和执行结果通过 KS3 交换，控制面不传 Tensor。

## 当前拓扑

| 设备 | 内部监听 | Controller 访问入口 |
|---|---|---|
| 摩尔线程 `10.121.38.9` | `0.0.0.0:9100` | `http://100.122.235.76:8002` |
| 华为 910B `10.0.0.7` | `0.0.0.0:9100` | `http://100.122.173.134:8002` |

有效映射：

```text
100.122.235.76:8002  -> 10.121.38.9:9100
100.122.173.134:8002 -> 10.0.0.7:9100
```

业务 HTTP 不经过 JumpServer；JumpServer 只用于 SSH 管理。

## 已实现能力

- Controller/Agent 控制面与 Local/KS3 数据面分离。
- 直接复用 sibling `op-verify` 的 KS3 客户端、序列化和检查策略。
- 两种运行方式：
  - `run`：Controller 生成输入，reference Agent 生成 golden，多个 target Agent 执行 solution。
  - `dataset-run`：读取 `op-verify` 已上传到 KS3 的输入/golden，两个国产 Agent 都作为 target。
- MUSA、Ascend NPU、CUDA、CPU 自动发现和显式同步计时，输出 p20/p50/p80/mean。
- target 并发执行、健康预检、HTTP 超时、Bearer token、solution SHA-256、case 独立 artifact key。
- safetensors 数据格式，不使用 pickle；本地存储拒绝路径穿越。
- JSON 报告及非零失败退出码。
- 基础设备容器只读，使用独立克隆工作容器并支持保存/恢复。

## 安装

设备镜像应预装对应厂商的 torch。不要让 pip 覆盖厂商 torch：

```bash
python3 -m pip install -e ../op-verify --no-deps
python3 -m pip install -e . --no-deps
```

Controller/Agent 均通过环境变量读取凭证：

```bash
export OP_VERIFY_KS3_AK='...'
export OP_VERIFY_KS3_SK='...'
export VCD_AGENT_TOKEN='...'
```

不要把实际值写入 JSON、Git 或命令历史。

## 启动 Agent

摩尔线程工作容器：

```bash
vcd-agent \
  --backend musa --device musa:0 \
  --host 0.0.0.0 --port 9100 \
  --storage-config /opt/vcd/run.ks3.json \
  --allow-solution-code --require-auth \
  --iterations 10
```

华为工作容器：

```bash
vcd-agent \
  --backend ascend --device npu:0 \
  --host 0.0.0.0 --port 9100 \
  --storage-config /opt/vcd/run.ks3.json \
  --allow-solution-code --require-auth \
  --iterations 10
```

`--allow-solution-code` 只应在隔离工作容器中使用。Agent 不应部署在基础容器或宿主机运行时环境中。

## 使用 KS3 golden 验证

复制 [run.ks3.cross-device.example.json](examples/run.ks3.cross-device.example.json)，把两个 `solution` 路径替换成该题目的摩尔/华为实现，然后运行：

```bash
PYTHONPATH=../op-verify:$PYTHONPATH \
vcd-controller dataset-run \
  --config examples/run.ks3.cross-device.json \
  --problem activation_norm/relu2 \
  --case 0 \
  --op reference \
  --report reports/relu2.json
```

真实 solution 的函数名不是 `reference` 时，用 `--op` 指定其入口函数名。

## 回归测试

```bash
CUDA_VISIBLE_DEVICES='' python3 -m unittest discover -s tests -v
CUDA_VISIBLE_DEVICES='' python3 examples/run_local_poc.py
CUDA_VISIBLE_DEVICES='' python3 examples/run_cross_poc.py
```

KS3 loopback 回归配置见 [run.ks3.loopback.json](examples/run.ks3.loopback.json)。完整架构见 [design.md](docs/design.md)，克隆容器部署流程见 [deployment.md](docs/deployment.md)。
