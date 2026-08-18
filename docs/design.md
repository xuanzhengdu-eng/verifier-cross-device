# 跨机器 Kernel 验证设计

## 目标

让同一个 case 的相同输入在多台异构设备上执行各自的 kernel solution，并统一产出正确性和性能报告。Controller 不需要加速卡；Agent 只运行在设备工作容器中。

## 架构

```text
                         control: HTTP
Controller 10.0.9.5  ------------------------>  Moer Agent :9100
        |               ------------------------>  Huawei Agent :9100
        |
        | data: HTTPS 443             data: HTTPS 443
        +---------------- KS3 <------------------+
```

控制面只包含：job/case ID、problem/op、artifact key、solution 源码及哈希、标量耗时和错误。Tensor 只通过 KS3/LocalStorage 传输。

## 模式一：动态 reference

1. Controller 的 `input_build` 在 CPU 生成一次输入。
2. 输入以 safetensors 写入 Storage。
3. reference Agent 执行 `ref_compute` 并写回 output。
4. target Agents 并发执行各自 `res_compute`。
5. Controller 下载 output 并调用题目作者的 compare。

该模式兼容原 `vcd` 四角色题目：`input_build / compute_ref / compute_res / compare`。

## 模式二：op-verify KS3 dataset

1. Controller 下载 `op-verify/v2/manifest.json`。
2. 每个 Agent 从 KS3 下载同一个 `inputs.safetensors`。
3. Agent 使用 op-verify 的 `unpack_inputs` 恢复 tensor/scalar 输入，并在本机设备执行 solution。
4. Agent 把实际 output 写回 KS3。
5. Controller 下载预生成 `ref_output.safetensors`，使用 op-verify 的 check descriptor/strategy 比较。

该模式不需要 reference Agent；摩尔和华为都作为 target，最适合当前两台国产设备。

## 存储

`Storage` 接口为 `put/get/exists/list`，实现：

- `LocalStorage`：仅用于 loopback/NFS；路径解析后必须位于 root 内。
- `KS3Storage`：复用 `op_verify.storage.KS3Client`，默认 HTTPS，AK/SK 只从命名环境变量读取。

VCD 自有 bundle/output 使用 safetensors。op-verify dataset 输入/golden 保持其原始格式，由 op-verify 序列化模块读取。

## Agent

`GET /health` 返回服务版本、设备信息和已注册题目。`POST /execute` 支持：

- `input_format=vcd`：执行四角色 registry；
- `input_format=op_verify`：直接执行 solution 入口函数。

Agent 对每个请求验证 Bearer token、字段格式、solution 大小和 SHA-256。执行由进程锁串行化，避免多个请求同时覆盖 `kernelgenbench.solution` 或争抢同一设备。

solution 源码执行本质上是不可信代码执行，因此必须满足：

- 只运行在克隆工作容器；
- 使用网络 ACL 限制 Controller 来源；
- 启用 Bearer token；
- 不在容器中放 Git/SSH/个人凭证；
- KS3 凭证使用最小权限并定期轮换。

## 设备与计时

设备自动发现顺序：MUSA、Ascend NPU、CUDA、CPU；也可显式配置 `musa:0`、`npu:0` 等。

每次采样前后调用对应 torch backend 的 `synchronize()`，使用单调高精度时钟记录 wall time。报告包括 p20、p50、p80、mean 和迭代次数。该方法不依赖某一家 Triton，在 MUSA/NPU 环境均可用。

## 失败语义

- Agent HTTP/鉴权失败：case target FAIL；
- input/storage 失败：Agent 返回 `input_error`；
- solution 编译/入口缺失：`solution_error/unsupported`；
- kernel 执行失败：`execution_error/unsupported`；
- 输出数量/结构不同：FAIL，不允许 `zip` 静默忽略；
- check strategy 不通过：FAIL 并保留误差指标。

CLI 只要存在 FAIL 或 case error 就返回非零退出码，便于 CI 集成。

## 容器不变量

设备原容器（当前为 `gosim_server`）永远不用于安装或调试。只允许对其执行 inspect/commit 以产生 snapshot image。所有代码修改、pip editable install、Agent 进程和日志都位于标记为 `vcd.role=work` 的工作容器。

阶段结束时 commit 工作容器为版本镜像并停止；下次优先 `docker start` 恢复同一工作容器，或从已保存镜像创建新的工作容器。
