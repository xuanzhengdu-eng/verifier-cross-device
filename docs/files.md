# 文件说明

本文档按路径平铺列出仓库中的 Git 跟踪文件。每个文件单独一条，便于在浏览目录时
快速判断其用途。`.git/`、`build/`、`reports/`、`__pycache__/`、运行时 artifact、
本地凭证和容器内部文件不属于源码清单，因此不在这里列出。

| 文件 | 用途 |
|---|---|
| `.gitignore` | 定义 Git 不跟踪的构建产物、Python 缓存、本地报告和临时运行数据。 |
| `README.md` | 项目总入口，介绍系统目标、架构、安装方法、服务启动、任务运行和文档索引。 |
| `agent/__init__.py` | 将 `agent` 声明为 Python 包。 |
| `agent/server.py` | 通用评测服务；提供 `/health` 和 `/execute`，读取 Storage 输入、加载 solution、在指定设备执行和计时，并写回输出。 |
| `deploy/__init__.py` | 将 `deploy` 声明为 Python 包，使部署工具可以作为模块和命令入口安装。 |
| `deploy/agent_daemon.py` | 评测服务守护启动器；通过标准输入接收凭证，在后台启动或停止 evaluator，并维护 PID 与日志文件。 |
| `deploy/container_clone.py` | 从基础容器创建隔离工作容器，复用设备和必要挂载，并支持把工作容器保存成镜像或恢复运行。 |
| `deploy/probe_device.py` | 设备探测小工具；验证 PyTorch 能在指定设备创建、计算和同步 Tensor，并打印设备信息。 |
| `docs/configuration.md` | 正式说明任务配置中的 reference、targets、solution、Storage、HTTP 和报告字段。 |
| `docs/deployment.md` | 正式说明 Controller 与评测节点的安装、容器隔离、服务启动、健康检查、升级和回滚。 |
| `docs/design.md` | 描述系统设计目标、控制面与数据面、执行时序、正确性模型、性能模型和安全边界。 |
| `docs/files.md` | 本文件；平铺说明仓库内每个 Git 跟踪文件的用途。 |
| `docs/validation.md` | 记录 H20、摩尔线程和 Ascend 三端真实验证范围、通过情况与性能数据。 |
| `examples/__init__.py` | 将 `examples` 声明为可导入的 Python 包。 |
| `examples/kernels/README.md` | 说明真实 Kernel 示例的目录规范、四角色 pytest 写法、本地运行和跨机运行方式。 |
| `examples/kernels/__init__.py` | 将 Kernel 示例目录声明为 Python 包，保证 pytest 和 Controller 可以按模块路径导入。 |
| `examples/kernels/activation_norm/__init__.py` | 将 activation/normalization 示例分类声明为 Python 子包。 |
| `examples/kernels/activation_norm/l2norm/__init__.py` | 将 `l2norm` 示例目录声明为 Python 子包。 |
| `examples/kernels/activation_norm/l2norm/ascend.py` | `l2norm` 的 Ascend FlagGems 实现，同时暴露 `l2norm` 和兼容入口 `reference`。 |
| `examples/kernels/activation_norm/l2norm/musa.py` | `l2norm` 的 MUSA FlagGems 实现，同时暴露 `l2norm` 和兼容入口 `reference`。 |
| `examples/kernels/activation_norm/l2norm/reference.py` | `l2norm` 的可信 PyTorch Reference 实现。 |
| `examples/kernels/activation_norm/l2norm/test_l2norm.py` | `l2norm` 的四角色 pytest，定义输入、Reference、Target、比较规则和参数组合。 |
| `examples/kernels/activation_norm/relu2/__init__.py` | 将 `relu2` 示例目录声明为 Python 子包。 |
| `examples/kernels/activation_norm/relu2/ascend.py` | `relu2` 的 Ascend FlagGems 实现，同时暴露 `relu2` 和兼容入口 `reference`。 |
| `examples/kernels/activation_norm/relu2/musa.py` | `relu2` 的 MUSA FlagGems 实现，同时暴露 `relu2` 和兼容入口 `reference`。 |
| `examples/kernels/activation_norm/relu2/reference.py` | `relu2` 的可信 PyTorch Reference 实现。 |
| `examples/kernels/activation_norm/relu2/test_relu2.py` | `relu2` 的四角色 pytest，定义输入、Reference、Target、比较规则和参数组合。 |
| `examples/kernels/activation_norm/silu_and_mul/__init__.py` | 将 `silu_and_mul` 示例目录声明为 Python 子包。 |
| `examples/kernels/activation_norm/silu_and_mul/ascend.py` | `silu_and_mul` 的 Ascend FlagGems 实现，同时暴露规范入口和兼容入口。 |
| `examples/kernels/activation_norm/silu_and_mul/musa.py` | `silu_and_mul` 的 MUSA FlagGems 实现，同时暴露规范入口和兼容入口。 |
| `examples/kernels/activation_norm/silu_and_mul/reference.py` | `silu_and_mul` 的可信 PyTorch Reference 实现。 |
| `examples/kernels/activation_norm/silu_and_mul/test_silu_and_mul.py` | `silu_and_mul` 的四角色 pytest，定义输入、Reference、Target、比较规则和参数组合。 |
| `examples/kernels/elementwise/__init__.py` | 将 elementwise 示例分类声明为 Python 子包。 |
| `examples/kernels/elementwise/add3/__init__.py` | 将 `add3` 示例目录声明为 Python 子包。 |
| `examples/kernels/elementwise/add3/ascend.py` | `add3` 的 Ascend FlagGems 实现，同时暴露 `add3` 和兼容入口 `reference`。 |
| `examples/kernels/elementwise/add3/musa.py` | `add3` 的 MUSA FlagGems 实现，同时暴露 `add3` 和兼容入口 `reference`。 |
| `examples/kernels/elementwise/add3/reference.py` | `add3` 的可信 PyTorch Reference 实现。 |
| `examples/kernels/elementwise/add3/test_add3.py` | `add3` 的四角色 pytest，定义输入、Reference、Target、比较规则和参数组合。 |
| `examples/kernels/elementwise/add_constant/__init__.py` | 将 `add_constant` 示例目录声明为 Python 子包。 |
| `examples/kernels/elementwise/add_constant/ascend.py` | `add_constant` 的 Ascend FlagGems 实现，同时暴露规范入口和兼容入口。 |
| `examples/kernels/elementwise/add_constant/musa.py` | `add_constant` 的 MUSA FlagGems 实现，同时暴露规范入口和兼容入口。 |
| `examples/kernels/elementwise/add_constant/reference.py` | `add_constant` 的可信 PyTorch Reference 实现。 |
| `examples/kernels/elementwise/add_constant/test_add_constant.py` | `add_constant` 的四角色 pytest，定义输入、Reference、Target、比较规则和参数组合。 |
| `examples/kernels/testing.py` | Kernel pytest 共用辅助层；选择平台实现和设备，并在 local/cross 模式间复用同一测试组合体。 |
| `examples/kgb_integration.py` | 旧 KGB PoC 集成层；从 KGB label 获取 problem key，再调用 `vcd.autowire` 装配四角色。 |
| `examples/run.four-role.local.json` | 四角色 HTTP loopback 配置；用两个本地 CPU evaluator 和 `LocalStorage` 验证完整跨服务流程。 |
| `examples/run.json` | 旧 `addmm` 跨服务 PoC 配置，定义本地 reference、两个 target 和本地共享存储。 |
| `examples/run.ks3.cross-device.example.json` | 正式跨设备 KS3 任务配置模板，使用占位服务地址和 solution 路径，不包含真实凭证。 |
| `examples/run.ks3.loopback.json` | KS3 dataset loopback 配置模板，用两个本地 CPU 服务检查 KS3 数据流程。 |
| `examples/run_cross_poc.py` | 旧四角色 PoC 启动器；启动多个本地 evaluator 后运行 `addmm` 跨服务测试并清理进程。 |
| `examples/run_local_poc.py` | 旧四角色单机 PoC 启动器；加载 solution 后在同一进程运行 `addmm` 的正确与错误示例。 |
| `examples/solutions/addmm/amd.py` | `addmm` 的正确 PoC solution，用于演示通过结果。 |
| `examples/solutions/addmm/ascend.py` | `addmm` 的故意错误 PoC solution，用于演示框架能够发现数值错误。 |
| `examples/solutions/relu2/reference.py` | 早期 dataset loopback 使用的独立 `relu2` PyTorch solution。 |
| `examples/storage.ks3.example.json` | 单个 evaluator 使用的 KS3 Storage 配置模板，只写环境变量名，不保存 AK/SK。 |
| `examples/test_addmm.py` | 旧 KGB 风格四角色算子示例，包含 `input_build/compute_ref/compute_res/compare` 和参数组合。 |
| `pyproject.toml` | Python 包元数据、运行依赖、测试可选依赖、命令行入口、打包范围和 pytest 收集范围。 |
| `storage/__init__.py` | 汇总导出 Storage 接口、本地/KS3 后端、工厂函数及通用序列化函数。 |
| `storage/base.py` | 定义所有存储后端必须实现的 `put/get/exists/list` 抽象接口。 |
| `storage/factory.py` | 根据配置创建 `LocalStorage` 或 `KS3Storage`，并解析相对本地路径。 |
| `storage/ks3.py` | 将仓库内 KS3 Client 适配成统一 Storage 接口，并从环境变量读取 AK/SK。 |
| `storage/ks3_client.py` | 内置轻量 KS3 HTTP 客户端，负责 KSS 签名、上传、下载、存在性检查和分页列举。 |
| `storage/local.py` | 本地文件系统 Storage；用于开发和 loopback，并阻止 key 路径穿越存储根目录。 |
| `storage/serialize.py` | 通用 VCD safetensors 序列化；打包 Tensor、标量参数及 Tensor/None 输出，不使用 pickle。 |
| `tests/__init__.py` | 将单元测试目录声明为 Python 包。 |
| `tests/test_agent.py` | 测试 evaluator 鉴权、Reference/Target 执行、源码哈希校验、dataset 协议和动态 solution。 |
| `tests/test_config.py` | 测试任务配置解析、服务 URL 校验、token 环境变量、兼容字段和 solution 路径。 |
| `tests/test_container_clone.py` | 测试工作容器命令构造，确认设备和端口被保留、数据目录隔离、系统挂载只读。 |
| `tests/test_daemon.py` | 测试 daemon 凭证字段校验及旧环境变量名到新名称的兼容转换。 |
| `tests/test_dataset.py` | 测试 dataset 输入/输出协议以及 standard、exact 等正确性检查策略。 |
| `tests/test_dataset_run.py` | 测试 manifest 驱动流程、运行时 Reference、Target 比较、加速比、失败语义和本地 Storage。 |
| `tests/test_ks3_client.py` | 测试 KS3 URL、签名头、状态码处理和 marker 分页逻辑，不连接真实 KS3。 |
| `tests/test_runtime.py` | 测试设备选择和同步计时结果的基本性质。 |
| `tests/test_storage.py` | 测试通用序列化往返、tuple/None 输出和 LocalStorage 路径安全。 |
| `vcd/__init__.py` | VCD 包入口；声明版本并导出四角色装饰器、注册表、local/cross runner 和上下文。 |
| `vcd/autowire.py` | 按函数名约定把 pytest 中的四个裸角色自动包装并注册，无需逐个写 VCD 装饰器。 |
| `vcd/checks.py` | dataset 模式的正确性策略实现，包括 standard、exact 和 mismatch-fraction。 |
| `vcd/cli.py` | `vcd-controller` 命令入口；提供四角色 `run` 和 manifest 驱动的 `dataset-run`。 |
| `vcd/client.py` | Controller 使用的 evaluator HTTP 客户端，负责鉴权头、超时、健康检查和安全重试。 |
| `vcd/comparator.py` | 可选误差指标辅助函数，为作者的 `compare` 计算绝对误差、相对误差和余弦相似度。 |
| `vcd/config.py` | 定义并校验 evaluator、HTTP 和四角色 run 配置，解析 token 与 solution 路径。 |
| `vcd/context.py` | 保存 local/cross 模式和当前 job 的线程局部状态，包括输入 key、时延和比较记录。 |
| `vcd/cross.py` | 四角色跨机调度器；上传输入、并发调用 targets、读取输出、执行作者 compare 并生成报告。 |
| `vcd/dataset.py` | manifest 驱动调度器；并发运行实时 Reference 与任意 targets，统一比较并计算加速比。 |
| `vcd/dataset_format.py` | 与 op-verify/KS3 数据集兼容的 safetensors 协议，处理 Tensor、标量、dtype、dataclass 和输出描述。 |
| `vcd/decorators.py` | 实现四角色注册与包装；local 模式就地执行，cross 模式把调用转换为远程调度。 |
| `vcd/errors.py` | 定义配置、评测服务和 Storage 相关的用户可见异常类型。 |
| `vcd/operator_test.py` | 本地四角色 pytest 运行器；通过抽象 Storage 往返输入输出并调用四个角色。 |
| `vcd/runner.py` | 旧四角色 local runner；按参数组合执行测试、收集时延和正确性记录并打印报告。 |
| `vcd/runtime.py` | 设备无关运行时层；识别 CPU/CUDA/MUSA/NPU，完成设备同步、计时分位数和设备信息采集。 |
| `vcd/solution.py` | 进程内动态 solution 注册表，使 pytest 的 `compute_res` 与 evaluator 收到的 solution 源码解耦。 |

## 阅读建议

第一次阅读可以按下面的顺序打开文件：

1. `README.md`：先理解完整流程；
2. `examples/kernels/activation_norm/relu2/test_relu2.py`：看一个标准四角色算子；
3. `vcd/autowire.py`、`vcd/decorators.py`、`vcd/cross.py`：理解 pytest 如何变成跨机调用；
4. `agent/server.py`：理解每台评测机器实际执行什么；
5. `storage/base.py`、`storage/local.py`、`storage/ks3.py`：理解本地与 KS3 如何共用接口；
6. `vcd/runtime.py`：理解不同设备如何同步和计时。
