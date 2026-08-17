# 跨机算子验证框架 设计文档

> 目标：把 KernelGenBench 的算子题目搬到多台异构硬件（NVIDIA / Ascend / AMD ...）上，做**跨硬件正确性 + 性能验证**。
> 以某设备上的**参考实现**为 reference（golden），各设备上**各自的 solution** 为 res，统一比较数值指标 + 运行耗时。

---

## 1. 系统总览

一句话：这是一个把 **KernelGenBench 的算子题目**（类 pytest 生成）搬到**多台异构机器**上做**跨硬件正确性 + 性能验证**的框架。

```text
KernelGenBench 题目（类 pytest，@parametrize）
        │  每题拆成 4 个角色函数（input_build / ref_compute / res_compute / compare）
        ▼
  ┌───────────────── Controller（编排）──────────────────┐
  │ 枚举 problem × 参数组合 → 逐 case 驱动 4 角色流水线     │
  └──────┬────────────────┬────────────────┬─────────────┘
         │ input_build     │ ref_compute     │ res_compute（扇出多台）
         ▼ (CPU 生成)       ▼                ▼
     输入包 → 数据层    ref 机(参考实现)   各 res 机(各自 solution.py)
                          │ output→数据层    │ output→数据层
                          └────────┬─────────┘
                                   ▼
                        Comparator（controller, CPU）
                        逐 (res_i, ref) 判 pass/fail + 各自 latency
                                   ▼
                                 Report
```

**reference / res 语义**：

| 概念 | 含义 |
|---|---|
| reference | 参考实现 `kernelgenbench.baseline.<op>` 在 **ref 设备**上的输出（golden） |
| res（solution） | 每后端**各自的** solution `.py`（`kernelgenbench.solution.<op>`）在**该 res 设备**上的输出 |
| 验证 | 每个 res 输出 vs reference 输出的数值指标（多个）+ 每台各自的 latency |

**分层一句话**：

- **控制面**（HTTP/gRPC）：输入包引用 + 瘦 metadata + solution `.py` 源码 + 编排/状态/结果指标。
- **数据面**（S3/MinIO/NFS）：输入包（张量 + kwargs 整包）+ output tensor。

细节见：§5（分层）、§6（与 KGB 结合）、§7（题目契约，核心）。

### 1.1 使用流程（开发完成后怎么用）

**准备（一次性）**

1. **每台机器起 agent 常驻**（本机 backend/device/端口/共享存储/题目模块由命令行指定）：
   ```bash
   python -m agent.server --backend nvidia --port 9101 --storage <shared> --test-module <题目模块> --device cuda
   python -m agent.server --backend amd    --port 9102 --storage <shared> --test-module <题目模块> --device cuda
   python -m agent.server --backend ascend --port 9103 --storage <shared> --test-module <题目模块> --device npu
   ```
2. **写一个 test 文件**：4 角色函数（`input_build`/`ref_compute`/`res_compute`/`compare`）+ 一个 `test_` 组合体（见 §7），随 benchmark 代码部署到 controller 与所有 agent。
3. **准备各后端的 solution `.py`** + 一份 **run 配置**（`run.json`，见 §8.1）：谁 ref、谁 res、各 agent 地址、每个 res 后端用哪份 solution。

**跑一次**

4. 用 `VCD_MODE` 切模式（入口 `test_single_operator.py` 按模式分流；cross 走独立 CPU controller，不进 `Verifier.verify`）：
   ```bash
   # 单机（=今天 KGB）：正参是单个 solution.py
   VCD_MODE=local python -m sandbox.server.test_single_operator solution.py --test-module test_addmm.py
   # 跨机：solution 由 run.json 按后端指定
   VCD_MODE=cross VCD_CONFIG=run.json python -m sandbox.server.test_single_operator --test-module test_addmm.py
   ```
   `test_` 代码一字不改；cross 模式下装饰器把 `input_build`→数据层、`ref/res`→各 agent、`compare`→controller。

**看结果**

5. 每个 res 设备一行：pass/fail + 各自 latency（+ 作者可选指标；见 §13/§14）。

> 一句话：**起 agent（一次）→ 写 test + 放 solution + run.json → `VCD_MODE=cross ...` 跑 → 看报告**。

---

## 2. 需求与场景

- 有多台异构机器，例如 NV（CUDA）、Ascend（NPU/CANN）、AMD（ROCm）。
- 在 ref 设备上跑参考实现得到 golden 输出；把**同一份输入**分发到各设备，各自跑 solution 得到输出。
- 统一比较：
  - **Correctness**：pass/fail（比较逻辑 + 容差由作者在 `@vcd.compare` 定）+ 作者可选误差指标（见 §13）。
  - **Performance**：do_bench 分位 latency（p50 / p20 / p80）、相对 reference 的 speedup。
- 以后能自然扩展到 CUDA / ROCm / CANN / XPU / CPU，以及不同 runtime 版本。

---

## 3. 核心设计原则

三条最重要、建议一开始就定死的架构决策：

1. **Controller / Agent 分离**
   - `Controller = orchestration`（编排）
   - `Agent = execution`（执行）
2. **Control Plane / Data Plane 分离**：控制面传引用 + 瘦 metadata，数据面传输入包 / output（详见 §5）。
3. **Backend 抽象**：`Backend` 描述「怎么执行」；「在哪里执行」第一版按 run.json 固定绑定，多机多卡再上 scheduler（见 §16）。

配套原则：

- **控制面不传 Tensor**：算子的**全部输入**（张量 + 非张量 kwargs）打包进 Data Plane，控制面只传**输入包引用 + 瘦 metadata**（op / shape / dtype / tolerance）。
- **输入一次生成、全体复用**：reference 端生成并物化；跨硬件 RNG 不一致，不能各机按 seed 各自生成（见 §9.2）。
- **不同硬件不能假设精度一致**，必须用 tolerance 而非 `torch.equal`。
- **题目不感知厂商**：test 文件只写算子逻辑；「哪台是什么后端 / agent 地址 / 用哪份 solution」全在 run.json（见 §8.1），agent 自身的 backend/device 由启动命令行给定。

---

## 4. 整体架构

```text
                         ┌─────────────────────┐
                         │      Controller      │
                         │                     │
                         │  Input Build (CPU)   │
                         │  Dispatcher (HTTP)   │
                         │  Comparator          │
                         │  Reporter            │
                         └──────────┬──────────┘
                                    │
                     RPC / HTTP / gRPC   (Control Plane)
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
        ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
        │ NV Agent     │    │ Ascend Agent │    │ AMD Agent    │
        │ CUDA/Torch   │    │ CANN/Torch   │    │ ROCm/Torch   │
        └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
               │                   │                   │
               ▼                   ▼                   ▼
          NVIDIA GPU          Ascend NPU          AMD GPU

                         ┌────────────────┐
                         │  Artifact Store │   (Data Plane)
                         │  MinIO / S3 /   │
                         │  NFS            │
                         │  input / output │
                         └────────────────┘
```

**Controller 不负责真正执行算子**，只做：

```text
生成输入 → 按 run.json 分发给各 agent → 收集结果 → 比较 → 生成 report
```

真正的 `output = operator(input)` 由每台机器的 **Agent** 完成。

### Agent 常驻 / Controller 一次性

- **Agent 是常驻 server**（`python -m agent.server`）：每台机器起一个，一直挂着等 `/execute` 请求。
- **Controller 第一版是一次性编排进程**（入口在 `test_single_operator.py` 按 `VCD_MODE` 分流：`local`→原 `Verifier` 路径不变；`cross`→**独立 CPU 编排函数**），本质是 **agent 的客户端**：读 case + 机器配置 → 生成输入、扇出 HTTP 给各 agent → 收结果 → compare → 出报告 → **退出**。它不监听端口、不常驻。
  - **cross 不经过 `Verifier.verify`**：那三层是「本机自己执行算子」的外壳，与 controller「自己不执行、扇到多机」相悖；cross 只复用 case 枚举 + 命名空间注册两个位置无关原语，编排循环另写（详见 §6.3）。
- Controller 变成常驻 server 是 Phase 3 的事（要排队提交、Web UI、多人异步提交 + 轮询状态时才需要）。

### Controller 运行位置 / input_build 归属

- **Controller 全程不碰 GPU/NPU**，干的都是 CPU 活（读配置、生成输入、发 HTTP、下载 output、CPU 上 compare、写报告）。所以它跑在**任意一台 CPU 机器**上即可：独立协调机 / 开发机 / CI runner（推荐），或其中一台 GPU 机器（能跑但没必要，用不到它的 GPU）。要求仅：Python + torch(CPU) + 同版本 benchmark 代码 + 能访问各 agent URL 与存储。
- **Controller ≠ reference 机器**：reference 只是它调用的一个 agent；Controller 自己在计算拓扑之外。
- **`input_build` 的运行位置不写死**。关键不变量是「输入包是 **CPU 数据、只生成一次、物化到存储、全体加载同一份**」；因为产物设备无关，在哪台机器的 CPU 上生成都行——默认 Controller 本地生成（最简单、少一跳），也可派给某个 agent 生成。框架按此保持灵活，不绑定具体机器。

### 为什么必须有 Agent（而不是 Controller 直接 ssh）

Agent 让各机器自管环境（conda/docker/超时/进程/日志），Controller 只发 RPC，不必把这些塞进 ssh 脚本。Agent 本身可以是很简单的 FastAPI / gRPC server。

---

## 5. 控制面 / 数据面

| 平面 | 负责内容 | 载体 |
|---|---|---|
| Control Plane | 输入包引用 + 瘦 metadata（op/dtype/shape/tolerance/kwargs 摘要）/ solution `.py` 源码 / device info / job scheduling / status / result 指标 / error / logs | HTTP / gRPC |
| Data Plane | 输入包（张量 + kwargs 整包）/ output tensor | S3 / MinIO / NFS / shared FS |

**不变量**：控制面消息里绝不出现张量本体，只出现输入包引用 + 瘦 metadata；Agent 从 Data Plane 拉输入包、把 output 张量推回 Data Plane，控制面只回传 output 引用 + 标量指标（latency、误差等）。solution 只考虑 `.py` 源码（体量小），走控制面 HTTP body（可按 hash 缓存），不进 Data Plane（见 §7.2）。

控制面 API 示例：

```http
POST /jobs
GET  /jobs/{job_id}
GET  /results/{job_id}
```

### 5.1 存储抽象层（Data Plane 后端）

数据面做成**可插拔的抽象层**，接口极简：

```python
class Storage(ABC):
    def put(self, key: str, data: bytes): ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
```

- **PoC 已实现：`LocalStorage`**（本地/共享目录后端，`storage/local.py`）——loopback PoC 里三个 agent + controller 共用同一个目录（真三机时挂 NFS 共享盘即可用同一份）。第一版调试最省事，免搭服务。
- **目标后端 KS3**（金山云对象存储，待实现）：直接复用 `cross-check/op-verify` 里的 `KS3Client`（`op_verify/storage.py`）——S3 兼容、HMAC-SHA1 V2 签名、不依赖 boto3，`upload/download/exists/list_prefix` 已齐全。配置沿用其约定：endpoint `ks3-cn-beijing.ksyuncs.com` / bucket `baai-sailing` / prefix，**AK/SK 走环境变量，不写进仓库**。
- 其他（S3 / MinIO 等）按需加 = 实现一个 `Storage` 子类。
- **序列化用 safetensors**（PoC `storage/serialize.py` 已实现，思路同 op-verify）：张量存为张量、**非张量 kwargs 塞进 safetensors 的 metadata header（JSON）**。选它而非 `torch.save` 是因为**不 pickle**——agent 上已经要跑不可信的 solution 代码，数据层不该再引入 pickle 反序列化的风险。它天然满足「一个 artifact 里张量 + 标量都有」。

---

## 6. 与 KernelGenBench 的结合

分析了现有的 `KernelGenBench/src`（一套「类 pytest」的算子验证 + benchmark 体系）。**结论：可以结合，而且已有相当一部分基础设施能直接复用；但 KGB 单测的「reference/target」语义和跨机框架不同，测试函数需要做职责拆分，不能原样搬。**

### 6.1 KGB 现在的测试模型

不是真的 pytest，而是自定义装饰器 + 自研 runner：

- `@label("op")` + `@parametrize("shape", [...])` 把测试函数注册进 `_label_registry / _parameter_registry`；
- `Verifier.run_tests()` 用 `expand_params()` 做笛卡尔积展开成 `combo`，再 `func(**combo)`；
- 每个测试函数体内**同时干了三件事**（以 `test_log_sigmoid_backward_tensor` 为例）：

```python
def test_xxx(shape, dtype):
    self = torch.randn(shape, dtype=dtype, device=device)   # (a) 本机生成输入
    ref_out = torch.ops.aten.log_sigmoid_backward(...)      # (b) 参考实现 = 原生 torch 算子
    with kernelgenbench.use_ops(REGISTERED_OPS):
        act_out = torch.ops.aten.log_sigmoid_backward(...)  # (b') 被测实现 = 生成的 kernel
    assert_close(act_out, ref_out, dtype=dtype)             # (c) 同进程内比较
    ms_torch  = do_bench(lambda: ref_impl())                # 基准
    ms_triton = do_bench(lambda: act_impl())
    return CustomBenchmarkResult(ref_time=ms_torch, res_time=ms_triton, speedup=...)
```

### 6.2 关键语义差异

| 维度 | KernelGenBench | 跨机验证框架 |
|---|---|---|
| reference | 原生 torch 算子 | 参考实现在 **ref 设备**上的输出 |
| target | 同卡上生成的 kernel | 每后端 solution 在**各 res 设备**上的输出 |
| 执行位置 | **同机、同进程** | **跨机、跨进程** |
| 输入 | 测试函数内 `torch.randn(device=device)` 本地生成 | 必须一次生成 → 物化 → 全体加载（见 §9.2） |
| 比较 | 进程内 `assert_close(act, ref)` | 各机产出 output artifact → Controller 统一 compare |

最大的坑正是 §9.2 说的：KGB 每台机器各自 `torch.randn(..., device=device)`，跨硬件 RNG 不一致，**直接跨机跑会把「输入不同」误判成「算子精度差异」**。

### 6.3 可以直接复用的部分

KGB 里已经有跨机框架需要的「半成品」，但**要分清复用侧**——agent 侧几乎照搬，controller 侧只借「执行位置无关」的纯原语：

| 跨机框架组件 | KGB 现成件 | 复用侧 | 说明 |
|---|---|---|---|
| Agent（执行服务） | `sandbox/server/verifier_server.py` | agent | 已是 FastAPI server：`POST /test`、`/status`、`/health` |
| Controller→Agent 客户端 | `sandbox/server/verifier_client.py` | controller | 已封装 HTTP 调用 |
| 本机多卡管理 / 隔离 | `DeviceStatesManager` + subprocess `CUDA_VISIBLE_DEVICES` | **agent** | 管本机 idle/busy + 进程级隔离；controller 不碰 GPU |
| Backend/厂商识别 | `kernelgenbench/runtime/vendor.py` 的 `Vendor` | agent | 已识别 nvidia/hygon/ascend/iluvatar/mthreads/metax |
| 设备抽象开关 | `sandbox/config.py` 的 `DEVICE`/`TO_CPU`，`to_reference`/`to_cpu` | agent | 已能把张量搬到 CPU |
| case 枚举 | `get_funcs_by_label` + `expand_params` | **controller** | 执行位置无关的纯原语，cross 编排循环用 |
| 命名空间注册 | `sandbox/register.py` | agent | 装 solution `.py` 进 `.solution`（见 §7.2） |
| 算子测试定义 | 上百个 `@label/@parametrize` 题目 | 两端 | 最底层 Operator Test Definition + 枚举源 |

**不复用**：

- **`Verifier.verify`/`_verify_with_one_device`/`run_tests` 三层不复用**——它们是「本机自己执行算子」的编排（本地多卡扇出、`CUDA_VISIBLE_DEVICES`、本地超时 kill、单进程 `func(**combo)`），与 controller「自己不执行、扇到多机」相悖。cross 的编排循环 + 结果收集**另写**。
- **`CustomBenchmarkResult`（`ref_time/res_time/speedup`）不作为跨机报告结构**——那是**同机**加速比；cross 报告是「每 res 一条 correctness + 各自 latency」的新 schema（见 §13）。它只在 `local` 模式沿用。

也就是说：**agent ≈ 现有 VerifierServer 的演进**（照搬为主）；**controller 是新写的一次性 CPU 编排**，只从 KGB 借「case 枚举 + 命名空间注册」两个纯原语。

### 6.4 必须改造的部分

1. **拆分测试函数的职责**：把「输入构造 / ref 计算 / res 计算 / 对比」从一个函数里拆成 4 个角色函数（详见 §7），比较交给 Controller，**不再在测试体内 `assert_close`**。
2. **输入物化 + 加载**：`input_build` 在 CPU 生成整包输入并物化到数据层；各 agent load 后把张量项搬到本机设备。同一份测试通过「执行模式」既能本地跑（老行为）又能跨机跑。
3. **benchmark 统一用 `triton.testing.do_bench`**：沿用 KGB 现成计时（warmup + 多次迭代 + 分位 p50/p20/p80）。各后端（NV/AMD/Ascend）的同步/对齐**由 do_bench 内部处理**，框架不分厂商、不自造 timer（见 §12）。
4. **ref / solution 分命名空间**：`ref` 调 `kernelgenbench.baseline.<op>`、`res` 调 `kernelgenbench.solution.<op>`；solution 注入 = 在 res agent 上注册收到的 `.py`（详见 §7.2），不需要 `use_ops` dispatch swap。

### 6.5 推荐的结合方式

不要手改自动生成的 11k 行测试文件（`test_ops_with_benchmark.py` 头部标注是 `convert_kernelgenbench_tests.py` 自动生成的）。正确做法：

- **在代码生成器层面**改造，把测试统一生成成 §7 的「4 裸角色 + test_ 组合体」形态；
- 加一层 **执行模式（execution mode）**，用环境变量 `VCD_MODE` 在 `test_single_operator.py` 入口**分流**（见 §7）：
  - `VCD_MODE=local` = 现在的行为（生成 + ref/res + assert，单机），走原 `Verifier` 路径，保持 KGB 原有用法不破坏；
  - `VCD_MODE=cross` = **绕开 `Verifier.verify`**，交给一个**独立 CPU 编排函数**驱动：`input_build`→数据层，`ref/res`→各机 agent（每步 HTTP 到对应 device 侧 server）→artifact，controller 统一 compare + report。
- **cross 只借两个位置无关原语**：case 枚举（`get_funcs_by_label` + `expand_params`）与命名空间注册（`register.py`）；`Verifier.verify` 那套本机执行编排不复用，编排循环另写（见 §6.3）。
- 把 KGB 的每个 `@parametrize` 定义，通过 problem key 装配成 §7 的 4 角色流水线（`input_build` 物化输入包，`kwargs` 来自 `parametrize` 的非张量参数）。

这样上百个现有算子 case 可以整体复用，从 3 台机器扩到 300 台时 Scheduler 层自然演进；加新硬件基本只是「加一个 Backend + Agent 配置 + Vendor 分支」。

### 6.6 vcd / KGB 边界与依赖

- **vcd 是独立 repo**（当前 `verifier-cross-backend`），只提供「机制」：装饰器 / cross controller / agent / storage / comparator（计时统一调 do_bench，不单列 timer 模块；见 §17）。
- **vcd 保持 KGB-agnostic**：controller **不 import KGB**。它只认一个抽象——「一批 `(4 角色函数集, 参数组合)`」，由调用方枚举好喂进来；vcd 不关心这些来自 `@label/@parametrize` 还是别的。以后换个 benchmark 也能复用。
- **依赖方向单向：KGB → vcd**。KGB 侧只加一层**薄集成**：
  1. test 文件写 4 个**按约定命名的裸函数**（无 `@vcd.*`）+ `@label`/`@parametrize` 挂 `test_` 上；
  2. 入口 import 题目模块后调 `vcd.autowire(mod, key)`（key 从 `@label` 取）自动装配；`VCD_MODE=cross` 时用 `get_funcs_by_label`+`expand_params` 枚举交给 `vcd` controller；
  3. agent 用 KGB 的 `register` 把收到的 solution 装进 `.solution` 命名空间。
- **部署**：每台机器装 **KGB + vcd（同版本）**；agent 机额外要该后端 torch，controller 机 torch(CPU)。

---

## 7. 测试题目契约（核心）

**pytest 外壳不动，作者也不写任何 `@vcd.*`**：把「输入构造 / ref / res / 对比」写成同一模块里 4 个**按约定命名的裸函数**（`input_build`/`compute_ref`/`compute_res`/`compare`），`@label`/`@parametrize` 照旧挂 `test_` 组合体上。框架 import 后按名字 + `@label` 的 key **自动装配**（`vcd.autowire`）成角色行为，靠 `VCD_MODE` 在 local / cross 间切换。

### 7.1 四个角色

| 角色 | 装饰器 | 行为 |
|---|---|---|
| 输入构造 | `@vcd.input_build(key)` | 在 **CPU** 上生成完整输入包（张量 + 标量 + 派生张量），整包物化到数据层，返回 handle；瘦 metadata（dtype/shape/tolerance）进控制层 |
| ref 计算 | `@vcd.ref_compute(key)` | 异步派到 **ref 机**（哪台由框架配置）；agent load 输入包、把张量项搬到本机设备、跑、输出落数据层 |
| res 计算 | `@vcd.res_compute(key)` | 异步扇出到 **各 res 机**（可多台）；agent 先装上本 backend 的 solution `.py`，再跑，各自输出落数据层 |
| 对比 | `@vcd.compare(key)` | 等齐所有 agent，在 controller 的 CPU 上逐一 `(res_i, ref)` 跑作者比较：记 pass/fail + 完整 error（作者可选 return 指标），容错（见 §13） |

四个角色都用 `func(**kwargs)` 命名参数约定（与 `expand_params` 的 `combo` 一致）。**作者不写任何 `@vcd.*`**：题目里 4 个**裸函数**按约定名命名，框架 import 后自动装配（`vcd.autowire`），key 从 `@label` 取。`@label/@parametrize` 照旧挂 `test_` 上，`test_` 组合体照写。

| 约定函数名 | 装配为角色 | 行为 |
|---|---|---|
| `input_build` | 输入构造 | 在 **CPU** 生成整包输入，物化到数据层 |
| `compute_ref` | ref 计算 | 派到 **ref 机**；agent load、搬本机设备、跑 `baseline`、输出落数据层 |
| `compute_res` | res 计算 | 扇出 **各 res 机**；agent 装本 backend solution、跑 `solution`、输出落数据层 |
| `compare` | 对比 | controller CPU 上逐 `(res_i, ref)` 跑作者比较：pass/fail + 完整 error（可选 return 指标），容错（见 §13） |

```python
# 4 个裸函数（无 @vcd.*）；名字即角色（见 vcd.autowire）
def input_build(config):
    m, k, n, dtype = config
    return {"input": ..., "mat1": ..., "mat2": ..., "beta": 1.0, "alpha": 1.0}  # CPU 生成

def compute_ref(input, mat1, mat2, beta, alpha):
    return kernelgenbench.baseline.addmm(input, mat1, mat2, beta=beta, alpha=alpha)

def compute_res(input, mat1, mat2, beta, alpha):        # 调 solution 命名空间；每 backend 各自的 .py
    return kernelgenbench.solution.addmm(input, mat1, mat2, beta=beta, alpha=alpha)

def compare(ref_out, res_out, dtype=None):              # 比较逻辑归作者；可选 return dict 记为指标
    ...

@label("addmm")                                          # key 从这里取
@parametrize("config", [(1024, 4096, 4096, torch.float16)])
def test_addmm(config):                                  # 组合体照写；名字自然走 autowire 包装版
    inp = input_build(config)
    ref_out = compute_ref(**inp)
    res_out = compute_res(**inp)
    compare(ref_out, res_out, dtype=config[-1])
```

**装配机制**：框架（KGB 集成入口）import 题目模块后调 `vcd.autowire(module, key)`——按约定名把 4 个裸函数包装成角色行为，并**回写模块同名属性**，于是 `test_` 组合体里 `input_build(...)`/`compute_ref(...)` 自然走包装版；同时填 `vcd.REGISTRY[key]`（agent 从中查角色函数本地执行）。key 由集成层从 `@label` 提取（`get_all_labels`），vcd 核心不 import KGB。

**执行模式由环境变量切换（test 代码一字不改）**：

```bash
# test_single_operator.py 在入口按 VCD_MODE 分流（不是给 Verifier 加开关）
# local：正参是单个 solution.py（=今天 KGB 单机行为，走原 Verifier 路径）
VCD_MODE=local python -m sandbox.server.test_single_operator solution.py --test-module test_addmm.py
# cross：绕开 Verifier.verify，走独立 CPU 编排；solution 由 run 配置按后端指定（见 §8.1）
VCD_MODE=cross VCD_CONFIG=run.json python -m sandbox.server.test_single_operator --test-module test_addmm.py
```

- `local`：装饰器近乎透传，`build/ref/res/compare` 在本机同进程顺序执行（原 `Verifier` 路径）。
- `cross`：入口分流到**独立 CPU 编排函数**（不进 `Verifier.verify`，见 §4/§6.5）。该函数用 `get_funcs_by_label`+`expand_params` 枚举 case，在**普通 CPU 进程**里顺序调用 `build/ref/res/compare`——每一步由装饰器转成 **HTTP 到对应 device 侧 agent**：`build`→物化输入包到数据层，`ref/res`→派到各 agent（各机加载输入包、搬本地设备、执行、output 落存储），`compare`→controller 下载 output 在 CPU 上比较。cross 还需 controller/agent 连接信息（`VCD_CONFIG=run.json`）。

框架幕后串接（DAG 由 problem key 装配）：

```text
build(**combo) → inputs(dict)
   └ 装饰器：整包序列化（safetensors，见 §5.1）到数据层 → input_handle；瘦 metadata 进控制层
ref(**inputs)  → 派到 ref 机；agent load、Tensor 项搬设备、func(**inputs)
   └ 返回值落存储 → ref_out_handle + latency
res(**inputs)  → 扇出各 res 机；agent 装上本 backend solution.py 后 func(**inputs)
   └ 各自 res_out_handle + latency
compare(...)   → controller 收齐，逐 (res_i, ref) 在 CPU load 后跑作者比较；记 pass/fail + 完整 error（+ 作者可选指标），容错
```

要点：

- **张量/标量不需作者标注**：装饰器 load 时用 `isinstance(x, torch.Tensor)` 自动把张量项搬设备，标量原样——这是搬运细节，不违背「input 全进数据层」。
- **传标识不传代码**：跨机时框架发的是「跑 problem=addmm 的 ref/res + 输入 handle + kwargs」，不序列化函数体。隐含部署假设：**所有 agent 与 controller 的 benchmark 代码版本一致**。

### 7.2 ref / solution 的命名空间与注入

复用 KGB 的 `register(namespace=...)` 机制（`sandbox/register.py`：`setattr(kernelgenbench.<ns>, <op>, func)`）。`kernelgenbench.<ns>.<op>` 是**晚绑定句柄**，加载对应 `.py` 时才挂上。

| 命名空间 | 内容 | 谁部署 | 谁调用 |
|---|---|---|---|
| `kernelgenbench.baseline.<op>` | 参考实现（baseline；aten 算子可直接包 `torch.ops.aten.<op>`） | 随 benchmark 代码部署在**所有 agent** | ref agent |
| `kernelgenbench.solution.<op>` | 每 backend 各自的 solution（**仅 `.py` 源码**） | **HTTP 发给对应 res agent** 后注册进该命名空间 | res agent |

- `.solution` 是**后端中性的新别名**；KGB 历史的 `.triton` 作为其 alias 保留兼容（`.triton` 名称在跨后端语境下会误导——Ascend 是 CANN、AMD 是 ROCm）。
- **solution 注入 = 在该 res agent 上把收到的 `.py` 注册进 `.solution` 命名空间**，不需要 `use_ops` 之类的 dispatch swap。ref/res 的差别是「调不同命名空间」，本就是两份代码。
- solution 只考虑 `.py` 源码 → 走控制层 HTTP body（可按 hash 缓存，命中不重发）；不进数据层。数据层只放输入包。

### 7.3 in-place 与多输出算子

in-place（`add_`、`index_put_`、`zero_`、`copy_`、`fill_`）的「输出」是被就地改写的入参，不是返回值；且重复调用会累积改写。处理办法：

1. **compute 显式 `return` 要比较的张量**（in-place 就 return 被改的入参），框架**统一只抓返回值**，不引入额外「输出声明」机制：
   ```python
   @vcd.res_compute("add_")
   def res(input, other):
       kernelgenbench.solution.add_(input, other)
       return input          # 显式把被改写的张量作为输出
   ```
2. **每次调用前 clone 输入**：正确性跑 1 次 + benchmark 每个 warmup/迭代各 1 次，都在 clone 上跑，避免累积改写污染数据与计时；**clone 耗时排除在计时之外**（compute/bench harness 负责）。
3. **benchmark per-iteration reset**：in-place 基准每迭代需拿未改写的输入——预克隆轮用，或在计时循环加不计入耗时的 reset 回调。`triton.testing.do_bench` 简单签名不支持 reset，harness 需改造。
4. **多输出**（如 `sort → (values, indices)`）：compute 返回 tuple，**怎么比由作者在 compare 里写**（values 带容差、indices 用 `assert_equal` 精确比），框架不自动切；比较逻辑和单输出一样归作者（见 §13）。

> 演进：以上先支持「返回值（可为 tuple）」这条主干；若将来要支持「输出显式绑定到某个具名入参」而非依赖 return，可再加一个可选的 `outputs=[...]` 声明。

---

## 8. TestCase 定义

一个 case 的「测试描述」分两处编写，没有独立的 YAML testcase：

- **test 文件（§7）= 唯一编写事实源**：输入生成 / kwargs / 对比逻辑，都是 4 角色函数里的 Python；case 由 `@parametrize` + `expand_params` 笛卡尔积展开。
- **run.json（§8.1）= 部署绑定**：谁 ref、谁 target、agent 地址、每个 res 用哪份 solution。

比较逻辑（含容差）在 `@vcd.compare` 里由作者自定义（见 §13）；硬件型号由 agent 运行时上报（§10）——都不需另写配置。

controller 在 cross 模式下**运行时生成**每个 case 的机器可读描述（Controller ↔ Agent 传输的派生产物，非手写）：

```json
{
  "case_id": "addmm_001",
  "op": "addmm",
  "input_bundle": "s3://operator-test/cases/addmm/001/inputs.safetensors",
  "meta": {
    "dtype": "float16",
    "shapes": {"input": [1024, 4096], "mat1": [1024, 4096], "mat2": [4096, 4096]},
    "tolerance": {"atol": 1e-2, "rtol": 1e-2}
  }
}
```

`input_bundle` 是**整包输入**（张量 + kwargs，见 §9）在 Data Plane 的引用；`meta` 是**瘦 metadata**，供 Comparator 判定用，**不是输入本体**。控制面消息里不出现任何张量。

### 8.1 跨机 run 配置

`VCD_MODE=cross` 时还需一份 **run 配置**（`VCD_CONFIG=run.json`），指明 ref/res 角色、各 agent 地址、以及**每个 res 后端用哪份 solution `.py`**——这些 test 文件里没有。

```json
{
  "reference": {"backend": "nvidia", "agent": "http://nv01:8001"},
  "targets": {
    "amd":    {"agent": "http://amd01:8001",    "solution": "solutions/addmm/rocm.py"},
    "ascend": {"agent": "http://ascend01:8001", "solution": "solutions/addmm/ascend.py"}
  },
  "storage": "s3://operator-test/"
}
```

- **ref 不需要 solution**：它跑随代码部署在 ref agent 上的参考实现（`kernelgenbench.baseline.<op>`，见 §7.2），只需 agent 地址。
- **角色划分与绑定都在 run.json**：既然砍掉了 YAML testcase，**谁是 ref、谁是 target 由 run.json 声明**（它天然按 backend 组织，`reference` 一个、`targets` 多个），同时把每个后端**绑定到物理资源**（agent 地址 + 每个 res 的 solution 路径）。test 文件只定义 ref/res 的**计算逻辑**，不列举 target backend——「有哪些 target」取决于你手上有哪些机器，是部署 concern，不是算子逻辑。
- 分工一句话：**test 文件** = 算子逻辑（input 生成 / ref / res / compare，唯一编写事实源）；**run.json** = 在哪跑 + 谁 ref / 谁 target + 每个后端用哪份 solution。agent 地址相对固定（可拆成常驻集群配置），solution 映射每次 run 可能变。

---

## 9. 输入的跨机传输

### 9.1 算子输入 = 张量参数 + 非张量参数

一次算子调用的输入不只是张量。它是一组位置/关键字参数的混合体：

- **张量参数（tensor args）**：`mat1`、`mat2`、`Q/K/V` 等，体量大、需要 bitwise 一致。
- **非张量参数（non-tensor args）**：标量（`alpha=1.0`、`beta=1.0`）、维度/形状（`dim=-1`、`keepdim=True`）、`dtype`、布尔标志、int/float/字符串、list/tuple、enum（如 reduction=`"mean"`）等。

以 `addmm` 为例，一次真实调用是：

```python
torch.addmm(input, mat1, mat2, beta=1.0, alpha=1.0)
#           └──────tensor─────┘  └──non-tensor──┘
```

所以分发一个 testcase 时，要同时携带这两类参数——它们**打进同一个输入包**（见 9.3）。

### 9.2 张量参数：生成方（CPU）生成一次 → 物化 → 全体加载

不同硬件的 RNG 实现（CUDA / ROCm / Ascend / CPU）**不保证 bitwise identical**，所以绝不能让各机器靠同一个 seed 各自生成张量——那样比较出来的差异里会混入「输入本身就不同」的噪声，无法归因到算子。必须让所有机器加载 **同一份物化好的张量**。

```text
生成方(CPU, 见 §4) → generate → inputs.safetensors
                                       │
                          ┌────────────┼────────────┐
                          ▼            ▼            ▼
                         NV          Ascend         AMD   （各自 .to(device)）
                          ▼            ▼            ▼
                     output_nv    output_npu    output_amd
```

```python
# 生成方（CPU，设备无关；见 §4 input_build 归属）：只生成一次，物化到 artifact
x = torch.randn(...)                                  # 在 CPU 上生成
save_bundle("inputs.safetensors", {"x": x, ...})      # safetensors，见 §5.1

# 各 Agent 端：加载同一份输入，再把张量搬到本地设备
bundle = load_bundle("inputs.safetensors")
x = bundle["x"].to(device)
```

要点：

- 输入在 **生成方（CPU）生成一次**，之后所有机器都从这份物化文件加载，保证各台拿到 **完全相同** 的张量。
- 生成用哪台机器不重要（产物是设备无关的 CPU 数据），重要的是「只生成一次 + 全体复用」。
- dtype 保持不变落盘（fp16 就存 fp16），避免落盘/加载过程引入额外的精度转换。
- 非张量参数不需要「生成」，但它们和张量**一起打进同一个输入包**（见 9.3），不单独走控制面。

### 9.3 分流规则：算子输入整包进 Data Plane，控制面只带引用 + 瘦 metadata

**不按类型分、也不按大小分**。规则很简单：

> - 算子的**全部输入**（张量 + 非张量 kwargs + 派生张量）打成**一个输入包**，物化到 Data Plane；控制面只传**输入包引用**。
> - 控制面另带一份**瘦 metadata**（dtype / shape / tolerance / 关键 kwargs 摘要），供 Comparator 判定用——它是输入的「摘要」，不是输入本体。

为什么这样最干净：

- **唯一契约**：`input_build` 产出任意 Python 结构（tensor 套 scalar 都行），一把梭序列化成一个包（**safetensors 优先**，张量存张量、标量进 metadata header；见 §5.1）；agent 一把梭 load 重建全部入参，**不用逐参数判断「是不是张量」**。
- **Controller 永不接触张量本体**：输入 1KB 还是 10GB，代码路径和内存占用都一样，也不会成为大张量转发瓶颈。
- **comparator 要 dtype/tolerance 不必下载整包**：这些在控制面的瘦 metadata 里就有。

搬运细节：agent load 输入包后，用 `isinstance(x, torch.Tensor)` 把张量项搬到本机设备、标量原样——这是搬运，不是路由决策。

```text
              ┌───────────────┐
              │ Object Storage│  inputs.safetensors (整包) / output.safetensors
              └───────┬───────┘
                      ▲   │ download
               upload │   ▼
                    NV   NV / Ascend / AMD
```

存储布局示例：

```text
s3://operator-test/
  cases/addmm/001/
    inputs.safetensors     # 整包：张量 + kwargs(metadata header)
    meta.json             # 瘦 metadata
    nvidia/output.safetensors
    amd/output.safetensors
    ascend/output.safetensors
```

---

## 10. Agent API

```http
POST /execute
```

请求（对齐 PoC 实现 `agent/server.py`）：

```json
{
  "job_id": "abc123",
  "problem_key": "addmm",
  "op": "addmm",
  "role": "res",
  "input_key": "addmm/<run_id>/inputs.safetensors",
  "solution_code": "<solution .py 源码>"
}
```

`role` = `ref` / `res`（res 才带 `solution_code`）。Agent 侧：从数据层拉整包、张量项搬本地设备、标量原样，(res 先把 `solution_code` 装进 `kernelgenbench.solution`)，再跑角色函数：

```python
bundle = deserialize_bundle(storage.get(input_key))          # safetensors：{张量..., 标量...}
args = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in bundle.items()}
out = role_fn(**args)   # ref→baseline.<op>；res→solution.<op>（见 §7.2）
p50, *_ = triton.testing.do_bench(lambda: role_fn(**args), quantiles=[0.5, 0.2, 0.8])
```

响应：

```json
{
  "status": "success",
  "backend": "nvidia",
  "output_key": "addmm/<run_id>/inputs.safetensors.out.nvidia",
  "latency_ms": 0.153,
  "device": {"backend": "nvidia", "device": "cuda", "name": "A100"}
}
```

> 目标态（PoC 未实现）：`solution` 按 hash 缓存（命中不重发源码）、`config:{warmup,iterations}` 覆盖 do_bench 参数、`unsupported` 三态。

---

## 11. Backend 抽象

**Backend 决定「怎么执行」**，与「在哪里执行」解耦。

```python
class Backend(ABC):
    name: str
    def prepare(self): ...
    def load_input(self, artifact): ...      # 从数据层拉输入包、把张量搬本机设备
    def execute(self, op, inputs, kwargs): ...
    def benchmark(self, fn): ...             # 直接调 triton.testing.do_bench（见 §12）
    def save_output(self, output): ...       # output 推回数据层
    def get_device_info(self): ...           # vendor / 型号 / driver，随结果上报
```

```text
Backend
   ├── CUDABackend      # device="cuda"
   ├── ROCmBackend      # ROCm 下 PyTorch 仍用 cuda API
   └── AscendBackend    # device="npu"（torch_npu）
```

> 计时不在 Backend 里分厂商——统一走 do_bench，同步/对齐由它内部处理（§12）。Backend 只管「在本机哪张卡、怎么加载/执行/落盘」。

每台机器的 backend/device 由 **agent 启动命令行**给定（`--backend --device`，见 §1.1），不需要额外的 machines.yaml；「哪台当 ref/res、地址、solution」在 run.json（§8.1）。PoC 里 loopback 三个 agent 同机不同端口，仅用 `--backend` 打标签模拟异构。

---

## 12. Benchmark

**GPU 测时间不能用裸 wall clock**（op 异步，裸计时可能只测到 kernel launch）——但这些坑不用自己处理：**统一用 `triton.testing.do_bench`**，和 KGB 一致。

```python
# 和 KGB 完全一致的计时；warmup + 多次迭代 + 分位都在 do_bench 内部
p50, p20, p80 = triton.testing.do_bench(fn, quantiles=[0.5, 0.2, 0.8])
```

要点：

- **不分厂商、不自造 timer**：NV / AMD / Ascend 的同步与对齐（cuda/npu event、synchronize 等）**厂商已在 do_bench 内部做好**——triton 在这几个后端上都有（triton-ascend、ROCm triton）。框架直接调 do_bench 即可。
- do_bench 只返回耗时、**不返回算子输出**：所以 agent 侧先单独取一次 output 交给 compare，再用 do_bench 测时（PoC `vcd/decorators.py:_timed` 即如此）。
- in-place 算子的 per-iteration reset 见 §7.3（do_bench 简单签名不重置输入，需 harness 配合）。

---

## 13. Correctness

**比较逻辑完全归作者**——在 `@vcd.compare` 里写，和 `@vcd.input_build` 一样。用什么容差、什么方法、报什么失败消息，框架一概不管、也不假设输出是张量。

框架对 accuracy 只做记录，三条：

- 没报错 → **PASS**；
- 报错（任何异常，同 KGB）→ **FAIL**，存**完整** error 消息；
- 作者可选 `return` 一个 dict → 原样记进 `metrics`（框架不计算、不解读；须 JSON-safe）。

```json
{"passed": true, "error": null, "metrics": {"my_max_rel": 0.001}}
```

怎么比是作者的事（不要用 `torch.equal`——不同硬件即使都是 FP16 也有 rounding/accumulation/implementation 差异，尤其 matmul/softmax/layernorm/reduction/attention，逐 bit 相等几乎必然误报）：

- 最常用：复用 KGB 的 `assert_close(res, ref, dtype, reduce_dim=K)`（内部按 dtype 取 rtol、按归约维放 atol）或 `assert_equal`（整型/索引精确比）；
- 也可自写任意逻辑：cosine / top-k 重合 / SNR / 升 fp32 再比……

**失败消息由比较逻辑自己给**（`torch.testing.assert_close` 的富消息，或作者 assert 的串），框架只捕获存下。若想让 PASS 也带误差数值，作者在 compare 里算好 `return`（想要标准一组可 `from vcd.comparator import metrics` 取）。

报告示例（每 res 一条：pass/fail + 各自 latency + 作者可选指标；FAIL 带完整消息）：

```text
NVIDIA A100   reference   0.153 ms
AMD  MI300    PASS        0.172 ms   {'my_max_rel': 0.001}
Ascend 910B   FAIL        0.181 ms   (max rel error 1.0e-1 exceeds 1e-2)
```

---

## 14. 执行流水线

```text
                 TestCase
                    ▼
              Input Build（CPU 生成 → 输入包 → 数据层）
                    ▼
             Reference Runner（ref 设备，参考实现）
                    │ reference output
                    ▼
              Res Runner（各 res 设备，各自 solution）
             /             \
       AMD output        Ascend output
            └───────┬───────┘
                    ▼
               Comparator（逐 res 判 pass/fail）
                    ▼
                 Report
```

最终一个 case（入口 `test_single_operator.py` 按 `VCD_MODE` 分流，cross 走独立 CPU controller、不进 `Verifier.verify`；第一版不做独立 CLI）：

```bash
VCD_MODE=cross VCD_CONFIG=run.json python -m sandbox.server.test_single_operator --test-module test_addmm.py
```

自动得到：

```text
                    correctness       latency
NVIDIA A100          reference        0.153 ms
AMD MI300            PASS             0.172 ms   max_error=... rtol=...
Ascend 910B          PASS             0.181 ms   max_error=... rtol=...
```

---

## 15. 关于负载均衡

第一版**不需要负载均衡**：异构节点 + 一个 case 有明确 target backend，本质是**按 backend 派发**（run.json 固定绑定），不是 round-robin LB。何时才需要按规模看：

| 拓扑 | 方案 |
|---|---|
| 1 backend → 1 机器 | 直接 RPC（现在） |
| 1 backend → N 机器 | scheduler / worker pool（见 §16） |
| N Controller + 大并发 | 才考虑 Nginx / Gateway / Queue |

---

## 16. 多机多卡时的调度（演进方向）

当一种 backend 对应多机多卡时，需要 **GPU/NPU-aware scheduler**（不是 HTTP LB——它不懂空闲/显存/型号）。三层职责分离：

```text
Scheduler     「这个 job 去哪里跑？」
   ▼
Resource Pool 「哪些机器/卡现在可用？」
   ▼
Backend       「在这张卡上具体怎么执行？」
```

- 资源粒度：`Cluster → Machine → Device → Execution Slot`；用 `CUDA_VISIBLE_DEVICES` 做进程级隔离。
- **跨硬件验证的一个 testcase 是一个 Job Group**（ref + 各 res 多边同时执行、任选空闲卡）。
- 调度指标：是否空闲 / 显存 / 当前 job 数 / **GPU 型号**（benchmark 必须知道具体硬件）。

Scheduler 接口示意：

```python
resource = scheduler.allocate(backend="cuda", device_count=1, memory_required=20*GB)
# ... 使用 ...
scheduler.release(resource)
```

---

## 17. 建议的项目结构

**vcd 独立 repo**（KGB-agnostic，见 §6.6）。★ = PoC 已实现，其余为目标态：

```text
verifier-cross-backend/         # = vcd（独立 repo）
├── vcd/
│   ├── decorators.py     ★ 4 角色装饰器工厂 + REGISTRY + run_compare_body
│   ├── autowire.py       ★ 按约定名把裸函数装配成角色（免手写 @vcd.*）
│   ├── context.py        ★ 执行上下文 / VCD_MODE（local 透传 vs cross 转 HTTP）
│   ├── cross.py          ★ cross 编排循环 + agent HTTP 客户端；不 import KGB
│   ├── runner.py         ★ local 模式 runner
│   └── comparator.py     ★ 可选作者 helper（框架不调用；作者可 import 返回标准指标）
├── agent/
│   └── server.py         ★ 执行 server（/execute /health；演进自 verifier_server.py）
├── storage/
│   ├── base.py           ★ Storage 抽象接口（put/get/exists/list）
│   ├── local.py          ★ 本地 / NFS 共享目录后端
│   ├── serialize.py      ★ safetensors 打包/解包（张量+标量 metadata）
│   └── ks3.py            ☐ KS3 后端（复用 op-verify 的 KS3Client）
├── examples/             ★ PoC 题目与跑测
│   ├── test_addmm.py             ★ **单一 test 题目**（baseline+4裸角色+test_组合体，无 @vcd.*；local/cross 共用）
│   ├── kgb_integration.py        ★ 集成层：从 @label 取 key + 调 vcd.autowire（允许 import KGB）
│   ├── run.json                  ★ 部署绑定（ref/targets + agent 地址 + solution 路径）
│   ├── run_local_poc.py          ★ local 启动器（装 solution + autowire + run_local）
│   ├── run_cross_poc.py          ★ cross 启动器（起 3 agent + autowire + run_cross）
│   └── solutions/addmm/{amd,ascend}.py  ★ 各后端 solution
└── README.md             ☐
```

**KGB 侧薄集成**（在 KGB repo 里改，见 §6.6，均待做）：

```text
KernelGenBench/
├── (test 文件)           ☐ import vcd；4 角色 + test_ 组合体
└── sandbox/server/test_single_operator.py   ☐ 入口按 VCD_MODE 分流：
                          #   local → 原 Verifier 路径
                          #   cross → get_funcs_by_label+expand_params 枚举 → 交给 vcd.cross.run_cross
```

---

## 18. 分阶段实施

### 验证三步（落地顺序，先于铺开）

不必一上来就三机 + 开端口，按风险从低到高验证：

1. **local parity**：拿 1~2 个 KGB 算子按约定拆成 4 裸角色，`VCD_MODE=local` 跑，确认结果与今天 KGB 一致——回归安全网，证明拆分没改变语义。
2. **单机 loopback cross**：三个 "agent" 都起在**同一台机**（甚至同进程），走完整 cross 链路（storage + safetensors + 编排 + compare）。**不需要运维开端口、不需要三台机**，用来验证机制正确性。
3. **真三机 cross**：端口开好后，NV/AMD/Ascend 实跑。

#### PoC 现状（本 repo `verifier-cross-backend`）

已跑通前两步（`vcd/` + `storage/` + `agent/` 均 KGB-agnostic，只有 `examples/` 用 KGB 命名空间）：

| 步骤 | 状态 | 复现 |
|---|---|---|
| ① local parity | ✅ | `python examples/run_local_poc.py`（同一 test 文件，启动器装 solution） |
| ② 单机 loopback cross | ✅ | `python examples/run_cross_poc.py`（同机起 3 个 agent 假装 nvidia/amd/ascend） |
| ③ 真三机 cross | 待端口 | 同 ②，把 `examples/run.json` 的 agent 地址换成真实机器即可，**代码不动** |

② 已验证的完整链路：controller 在 CPU 上 `input_build`→safetensors 上传共享存储 → `ref` 派到 nvidia agent 跑 `kernelgenbench.baseline.addmm` → `res` 扇出到 amd/ascend agent（各自安装 run.json 指定的 solution `.py` 进 `kernelgenbench.solution`）→ output 落存储 → controller 逐 backend compare（正确 solution PASS、故意放大 10% 的 solution FAIL 且抓到 `max_rel≈0.10`）+ per-backend latency（do_bench）+ 容错（一个 FAIL 不影响其余）。

关键文件：`vcd/{decorators,autowire,context,cross,comparator,runner}.py`、`storage/{base,local,serialize}.py`、`agent/server.py`、`examples/{test_addmm.py,kgb_integration.py,run_local_poc.py,run_cross_poc.py,run.json,solutions/}`。

> 备注：cross 起 3 个 HTTP server，某些受限沙箱/CI 会在进程启动前拦掉（表现为立即退出、无日志）。直接在普通机器上 `python examples/run_cross_poc.py` 即可复现绿报告。

### Phase 1：先跑通（HTTP + 文件传输）

```text
Controller ──HTTP──▶ Agent
```

```bash
# 三台机器各启 agent server（真实参数见 §1.1）
python -m agent.server --backend nvidia --port 9101 --storage <shared> --test-module <题目模块> --device cuda
python -m agent.server --backend amd    --port 9102 --storage <shared> --test-module <题目模块> --device cuda
python -m agent.server --backend ascend --port 9103 --storage <shared> --test-module <题目模块> --device npu
# Controller 入口：test_single_operator.py 按 VCD_MODE 分流，cross 走独立 CPU controller
VCD_MODE=cross VCD_CONFIG=run.json python -m sandbox.server.test_single_operator --test-module test_add.py
```

第一版组件清单：

| 组件 | 第一版 |
|---|---|
| Controller | ✅ |
| Agent | ✅ |
| HTTP/gRPC | ✅ |
| Artifact Storage | 推荐 ✅ |
| Scheduler | ❌ run.json 固定绑定（多机多卡再上，见 §16） |
| Nginx | ❌ |
| Load Balancer | ❌ |
| Redis/Kafka | ❌ |
| Kubernetes | ❌ |

> 只有 3 台机器时上 Nginx + LB + Redis + K8s，容易把「算子验证框架」做成「搭基础设施」，反而拖慢功能开发。

### Phase 2：加入 Artifact Storage

大 Tensor 不再经过 Controller。

### Phase 3：完整跨硬件 benchmark 框架

加入 Job Queue / Retry / Timeout / Distributed scheduling / GPU isolation / Docker / 环境管理 / Result DB / CLI / Web UI / 历史 benchmark。
