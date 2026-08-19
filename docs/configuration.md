# 任务配置

## 1. 配置结构

`dataset-run` 使用一个 JSON 文件描述 reference、targets、存储后端和 HTTP 参数。
项目提供 `config/run.example.json` 模板。首次使用时复制并填写当前环境配置：

```bash
cp config/run.example.json config/run.internal.json
```

```json
{
  "reference": {
    "backend": "cuda",
    "service": "http://reference-evaluator.example:9100",
    "solution": "solutions/example/reference.py",
    "token_env": "VCD_SERVICE_TOKEN"
  },
  "targets": {
    "target_a": {
      "backend": "accelerator-a",
      "service": "http://target-a.example:9100",
      "solution": "solutions/example/target_a.py",
      "token_env": "VCD_SERVICE_TOKEN"
    },
    "target_b": {
      "backend": "accelerator-b",
      "service": "http://target-b.example:9100",
      "solution": "solutions/example/target_b.py",
      "token_env": "VCD_SERVICE_TOKEN"
    }
  },
  "storage": {
    "type": "ks3",
    "scheme": "https",
    "endpoint": "ks3.example.com",
    "bucket": "kernel-verification",
    "prefix": "datasets/v1",
    "ak_env": "VCD_KS3_AK",
    "sk_env": "VCD_KS3_SK"
  },
  "http": {
    "connect_timeout": 10,
    "read_timeout": 600,
    "retries": 2
  }
}
```

## 2. Reference

`reference` 是必填对象，并且任务中只能有一个：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `backend` | 是 | 后端标签，例如 `cuda` |
| `service` | 是 | 评测服务 HTTP URL |
| `solution` | 是 | Controller 本地的 reference 源码路径 |
| `token_env` | 否 | 保存 Bearer token 的环境变量名称 |

reference 设备不固定为某个厂商。当前可以使用 NVIDIA CUDA 作为 reference，也可以按验证规范替换为其他具备可信参考实现的设备。

## 3. Targets

`targets` 是非空对象，可以包含任意数量的命名 target。每个 target 字段与 reference 相同，但 solution 指向该平台的特化实现。

target 名称用于：

- 报告标识；
- artifact 路径隔离；
- 同 backend 多节点区分。

名称必须以字母或数字开头，只能包含字母、数字、点、下划线和连字符；`reference` 是保留名称。

增加或删除 target 不需要修改 Controller 或评测服务代码。

## 4. Solution 路径与入口

相对路径以任务配置文件所在目录为基准。Controller 会验证文件存在、读取源码并计算 SHA-256。

CLI 的 `--op` 指定源码入口函数：

```bash
vcd-controller dataset-run \
  --config config/run.internal.json \
  --problem group/problem \
  --op kernel_entry
```

未传 `--op` 时，默认使用 problem key 最后一个路径段。

四角色 `vcd-controller run` 同样使用这些 solution 路径。若 `reference.solution` 已
配置，Controller 会把 reference 源码发送给 Reference 评测服务；否则仅为兼容旧式
预注册模块，使用评测服务中已注册的 `compute_ref`。

## 5. Storage

正式跨机器评测使用 `storage.type: "ks3"`。本地开发和 pytest 可以使用
`storage.type: "local"`，两者都实现 `put/get/exists/list` 接口并使用相同的数据格式：

```json
{
  "storage": {
    "type": "local",
    "root": "./artifacts"
  }
}
```

存储中至少需要：

- `manifest.json`；
- manifest 为每个 case 声明或约定的 `inputs.safetensors`。

manifest 的 `check_descriptor` 决定正确性检查策略。离线 golden 可以保留用于数据集审计，但不会替代本次 reference 执行输出。

AK/SK 只能通过 `ak_env` 和 `sk_env` 指定的环境变量提供。

## 6. HTTP

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `connect_timeout` | 10 秒 | 建立连接超时 |
| `read_timeout` | 600 秒 | 单次执行响应超时 |
| `retries` | 2 | 健康检查和可安全重试请求的重试次数 |

## 7. 报告字段

每个 case 包含：

- `job_id`、`problem`、`case_index` 和 `inputs_key`；
- `check_descriptor`；
- `reference` 执行状态、设备、输出路径和时延；
- `results` 中每个 target 的执行状态、正确性、误差和时延；
- `speedup_vs_reference`。

加速比定义为：

```text
reference.latency_ms / target.latency_ms
```

reference 失败时，该 case 的所有 target 正确性均为 FAIL，且不产生有效加速比结论。
