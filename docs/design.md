# 系统设计

## 1. 设计目标

系统用于验证同一 Kernel 在不同加速设备和实现之间的语义一致性，并记录可比较的执行时延。设计目标包括：

- reference 在指定设备上实时执行，不依赖离线 golden 作为最终基线；
- 同一 case 的所有执行使用相同输入；
- 支持一个 reference 和任意数量 targets；
- 设备评测逻辑与调度、比较逻辑解耦；
- 支持不同厂商运行时的显式同步计时；
- 所有节点部署相同代码，角色由配置决定；
- 结果可追踪、可序列化，并能用于自动化流水线。

## 2. 逻辑架构

```text
                        Control plane: HTTP
                   ┌─────────────────────────┐
                   │                         ▼
Controller ────────┼─────────────── Reference evaluator
    │              │
    │              ├─────────────── Target evaluator 1
    │              ├─────────────── Target evaluator 2
    │              └─────────────── Target evaluator N
    │                                        │
    └──────── Data plane: object storage ────┘
```

### Controller

Controller 负责：

- 解析 manifest、case 和任务配置；
- 将 reference 实现发送给 reference 评测服务；
- 将平台实现发送给对应 target 评测服务；
- 并发调度一次 case 的所有执行；
- 读取执行输出并进行正确性比较；
- 汇总时延、加速比、错误和设备信息。

Controller 不要求安装加速设备运行时。

### Evaluation service

评测服务负责：

- 从对象存储读取任务输入；
- 在本地指定设备上执行收到的实现；
- 完成 warmup、显式同步和多次计时；
- 将输出写回对象存储；
- 通过 HTTP 返回执行状态、设备信息和时延统计。

reference 与 target 使用同一个服务实现。二者区别仅由请求中的角色和 solution 决定。

### Object storage

对象存储承载输入和执行输出，避免通过控制面传输大型 Tensor。存储接口抽象为 `put/get/exists/list`，当前实现包括 KS3 和本地文件系统。

## 3. 单 case 执行时序

```text
Controller        Reference        Target 1 ... Target N        Storage
    │                  │                │                         │
    ├─ read manifest ────────────────────────────────────────────►│
    ├─ execute(ref) ──►│                │                         │
    ├─ execute(t1) ────────────────────►│                         │
    ├─ execute(tN) ───────────────────────────────►│              │
    │                  ├─ read same input ───────────────────────►│
    │                  ├─ run reference.py                       │
    │                  └─ write reference output ───────────────►│
    │                                   ├─ run target solution   │
    │                                   └─ write target output ─►│
    ├─ read all outputs ─────────────────────────────────────────►│
    ├─ compare target outputs with reference output              │
    └─ generate report                                           │
```

reference 和 targets 并发执行。正确性比较必须等待 reference 输出和对应 target 输出均成功产生。

## 4. 正确性模型

reference 本次执行结果是唯一比较基线。每个 target 独立与 reference 比较，一个 target 的失败不影响其他 target 的结果记录。

检查策略来自 manifest 的 `check_descriptor`：

- `standard`：按 dtype 或指定 `atol/rtol` 执行近似比较；
- `exact`：要求 Tensor 完全相等；
- `mismatch_fraction`：允许指定比例的元素不匹配，适用于量化输出。

输出数量、Tensor 形状和 `None` 位置也属于正确性约束，不允许通过截断比较忽略结构差异。

## 5. 性能模型

每个评测服务在对应设备上执行相同的 warmup 和 iteration 策略，并在每次采样前后调用运行时同步接口。报告包含：

- `p20_ms`；
- `p50_ms`；
- `p80_ms`；
- `mean_ms`；
- `iterations`。

target 相对 reference 的加速比定义为：

```text
speedup_vs_reference = reference_p50_ms / target_p50_ms
```

大于 1 表示 target 在该 case 上更快。跨设备性能结果只有在输入、数值精度、计时参数和执行语义一致时才具有可比性；报告保留原始时延，避免只用单个比值表达结果。

## 6. 扩展模型

系统不维护固定设备列表。增加新 target 时只需：

1. 为新运行时实现设备发现和同步适配；
2. 在该节点部署相同版本的评测服务；
3. 在任务配置的 `targets` 中增加节点及其 solution；
4. 确保该节点可访问对象存储和 Controller 可访问其 HTTP 服务。

同一 backend 可以部署多个 target。任务使用 target 名称区分输出路径，避免同类设备之间发生 artifact 冲突。

## 7. 安全边界

solution 源码属于可执行输入，评测服务应运行在隔离容器或等价沙箱中。生产部署至少需要：

- Bearer token 鉴权；
- Controller 来源限制；
- 最小权限对象存储凭证；
- solution 大小和 SHA-256 校验；
- 禁止将个人凭证写入评测镜像；
- 基础设备环境与评测工作环境隔离。

数据序列化使用 safetensors，不使用 pickle。

## 8. 失败语义

- reference 执行失败：该 case 无法形成正确性基线，所有 targets 记为 FAIL；
- 单个 target 执行失败：仅该 target 记为 FAIL；
- 输入或存储失败：执行端返回 `input_error`；
- solution 编译或入口错误：返回 `solution_error` 或 `unsupported`；
- Kernel 执行错误：返回 `execution_error` 或 `unsupported`；
- HTTP 或鉴权失败：Controller 将对应服务标记为不可用；
- 任意 case 或 target 失败：CLI 返回非零退出码。
