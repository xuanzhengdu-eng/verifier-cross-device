# verifier-cross-device

独立、完整的跨机器 Kernel 正确性与性能验证项目。同一份仓库代码部署到 Controller、摩尔线程和华为 910B 三个节点；节点角色只由启动命令和配置决定。

## 独立性保证

本仓库已内置完整运行链路：

- Controller 调度、并发请求和 JSON 报告；
- HTTP 评测服务、Bearer 鉴权和 solution 哈希校验；
- MUSA、Ascend NPU、CUDA、CPU 设备发现与同步计时；
- KS3 V2 签名客户端和 Local/KS3 存储后端；
- KS3 数据集 input/golden 的 safetensors 编解码；
- standard、exact、mismatch-fraction 正确性检查策略；
- 基础容器克隆、评测服务守护和设备探测脚本。

运行时不需要克隆、安装或设置 `PYTHONPATH` 指向 `op-verify`。现有 KS3 数据仍位于 `op-verify/v2` 前缀，这是对象存储中的兼容数据路径，不是代码依赖。

第三方 Python 包（PyTorch、FastAPI、requests、safetensors、uvicorn、pydantic）仍需安装；设备服务器应继续使用厂商镜像自带的 PyTorch/MUSA/torch_npu，不要用普通 pip 覆盖。

## 三个节点，一份代码

| 节点 | 运行角色 | 命令 |
|---|---|---|
| `10.0.9.5` | Controller | `vcd-controller dataset-run ...` |
| 摩尔线程 `10.121.38.9` | MUSA 评测服务 | `vcd-evaluator --backend musa --device musa:0 ...` |
| 华为 910B `10.0.0.7` | Ascend 评测服务 | `vcd-evaluator --backend ascend --device npu:0 ...` |

Controller 访问入口：

```text
http://100.122.235.76:8002 -> 10.121.38.9:9100
http://100.122.173.134:8002 -> 10.0.0.7:9100
```

业务 HTTP 不经过 JumpServer；JumpServer 只用于 SSH 管理。三台机器均主动通过 HTTPS 443 访问 KS3，KS3 不会反向连接服务器。

## 安装

普通 CPU/Controller 环境：

```bash
python3 -m pip install -e .
```

已经预装厂商 PyTorch 和全部依赖的设备工作容器：

```bash
python3 -m pip install -e /opt/verifier-cross-device --no-deps
```

`--no-deps` 用于保护厂商 PyTorch，不表示还需要另一个项目。可用下面命令检查当前安装的同一项目版本：

```bash
python3 -c "import importlib.metadata as m; print(m.version('verifier-cross-device'))"
```

## 凭证

三个角色统一使用以下环境变量：

```bash
export VCD_KS3_AK='...'
export VCD_KS3_SK='...'
export VCD_SERVICE_TOKEN='...'
```

不要把实际值写进 Git、JSON、镜像层或命令历史。评测服务守护脚本支持从标准输入临时注入，详见 [部署文档](docs/deployment.md)。

## 启动两个评测服务

摩尔线程工作容器：

```bash
vcd-evaluator \
  --backend musa --device musa:0 \
  --host 0.0.0.0 --port 9100 \
  --storage-config /opt/verifier-cross-device/examples/run.ks3.cross-device.smoke.json \
  --allow-solution-code --require-auth --iterations 10
```

华为 910B 工作容器使用同一命令，只修改设备参数：

```bash
vcd-evaluator \
  --backend ascend --device npu:0 \
  --host 0.0.0.0 --port 9100 \
  --storage-config /opt/verifier-cross-device/examples/run.ks3.cross-device.smoke.json \
  --allow-solution-code --require-auth --iterations 10
```

`vcd-agent` 暂时保留为兼容命令，正式文档统一称为“评测服务”。`--allow-solution-code` 只允许在隔离工作容器中使用。

## 发起 KS3 数据集验证

复制 [配置模板](examples/run.ks3.cross-device.example.json)，把两端 `solution` 路径替换为题目的平台实现，然后在 `10.0.9.5` 运行：

```bash
vcd-controller dataset-run \
  --config examples/run.ks3.cross-device.smoke.json \
  --problem activation_norm/relu2 \
  --case 0 \
  --op reference \
  --report reports/relu2.json
```

Controller 读取同一份输入和 golden，两个评测服务分别在国产设备上执行各自 solution，最终由 Controller 统一比较并生成报告。solution 的函数名不是题目 basename 时用 `--op` 指定。

## 测试

```bash
CUDA_VISIBLE_DEVICES='' python3 -m unittest discover -s tests -v
CUDA_VISIBLE_DEVICES='' python3 examples/run_local_poc.py
CUDA_VISIBLE_DEVICES='' python3 examples/run_cross_poc.py
```

完整架构见 [设计文档](docs/design.md)，两台服务器的克隆容器流程见 [部署文档](docs/deployment.md)。
