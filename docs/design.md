# 跨机器 Kernel 验证设计

## 目标与部署模型

同一个 `verifier-cross-device` 代码包安装在三个节点，通过不同命令承担不同角色：

```text
                           control: HTTP
Controller 10.0.9.5  ---------------------->  Moer 评测服务 :9100
        |              ---------------------->  Huawei 评测服务 :9100
        |
        | data: HTTPS 443             data: HTTPS 443
        +------------------ KS3 <------------------+
```

Controller 不需要加速卡。两个评测服务分别运行在国产设备的克隆工作容器中。控制面传递 job/case ID、problem/op、artifact key、solution 源码及 SHA-256、耗时和错误；Tensor 通过 KS3 或共享 LocalStorage 传输。

## 单仓库边界

项目内部提供：

- `storage.ks3_client`：KS3 HTTPS、KSS V2 签名和对象操作；
- `vcd.dataset_format`：既有 KS3 数据集 safetensors 协议；
- `vcd.checks`：manifest check descriptor 对应的检查策略；
- `agent.server`：评测服务 HTTP 实现；
- `vcd.cli`：Controller CLI。

因此运行链路不依赖兄弟源码仓库。`op-verify/v2` 仅是当前 KS3 数据前缀和兼容协议来源。仓库依赖 PyTorch 等第三方运行库，以及外部基础设施 KS3/HTTP 网络；“代码独立”不等于把设备驱动、对象存储服务或 Python 第三方包复制进仓库。

## 模式一：动态 reference

1. Controller 在 CPU 生成一次输入并写入 Storage。
2. reference 评测服务执行 `ref_compute` 并写回 golden。
3. target 评测服务并发执行各自 `res_compute`。
4. Controller 下载所有输出并调用题目作者的 compare。

该模式兼容 VCD 四角色题目：`input_build / compute_ref / compute_res / compare`。

## 模式二：KS3 预生成数据集

1. Controller 下载 `manifest.json` 和预生成 golden。
2. 两个评测服务从 KS3 下载同一个 `inputs.safetensors`。
3. 评测服务使用内置 `unpack_inputs` 恢复 tensor/scalar 输入并执行平台 solution。
4. 两端分别把实际 output 写回 KS3。
5. Controller 使用内置 descriptor/check strategy 与 golden 比较。

此模式不需要 reference 评测服务，适合当前摩尔线程和华为 910B 两台设备。

## HTTP 评测服务

`GET /health` 返回服务版本和设备信息。`POST /execute` 支持：

- `input_format=vcd`：执行四角色 registry；
- `input_format=dataset`：执行 Controller 下发的 solution 入口函数；
- `input_format=op_verify`：仅为旧请求保留的兼容值，内部走相同 dataset 实现。

每个请求校验 Bearer token、字段格式、solution 大小和 SHA-256。执行通过进程锁串行化，避免多个请求覆盖 solution 命名空间或争抢同一设备。

solution 源码属于不可信代码，必须只在克隆工作容器中执行，并配合网络 ACL、Bearer token、最小权限 KS3 凭证；容器中不能放 Git/SSH/个人凭证。

## 存储、格式和计时

- `LocalStorage` 用于 loopback/NFS，并拒绝路径穿越。
- `KS3Storage` 默认 HTTPS，AK/SK 只从环境变量读取。
- Tensor 使用 safetensors，不使用 pickle。
- 设备发现支持 MUSA、Ascend NPU、CUDA、CPU。
- 每次采样前后调用对应 backend 的 `synchronize()`，报告 p20/p50/p80/mean。

## 失败语义

- 评测服务 HTTP/鉴权失败：对应 target FAIL；
- input/storage 失败：返回 `input_error`；
- solution 编译或入口缺失：返回 `solution_error/unsupported`；
- Kernel 执行失败：返回 `execution_error/unsupported`；
- 输出数量、形状或 None 位置不同：FAIL；
- check strategy 不通过：FAIL 并保留误差指标。

任意 target FAIL 时 Controller CLI 返回非零退出码，便于 CI 集成。

## 容器不变量

设备原容器 `gosim_server` 不用于安装、复制代码、调试或运行评测服务。只允许对其执行 inspect/commit 以产生快照。代码安装和运行全部位于标记为 `vcd.role=work` 的克隆工作容器。阶段结束时保存工作容器镜像；下次恢复同一工作容器或从保存镜像创建新容器。
