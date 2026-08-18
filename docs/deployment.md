# 部署与运行

## 1. 部署原则

Controller、reference 节点和所有 target 节点必须使用同一版本的 `verifier-cross-device`。建议以固定 Git commit、wheel 或经过校验的源码归档作为发布单元。

部署角色分为：

- Controller：运行调度和结果比较；
- Evaluation service：运行 reference 或 target Kernel；
- Object storage：保存数据集输入和任务输出。

reference 与 target 不需要不同的软件包。

## 2. 环境要求

所有节点要求 Python 3.10 或更高。评测节点还需要：

- 对应设备驱动和运行时；
- 与设备匹配的 PyTorch 发行版；
- FastAPI、pydantic、requests、safetensors 和 uvicorn；
- 到对象存储的网络访问能力。

Controller 不要求加速卡，但需要安装 PyTorch CPU 版本以读取和比较输出。

## 3. 发布同一代码版本

在发布端生成固定版本构件：

```bash
git rev-parse HEAD
python3 -m pip wheel --no-deps . --wheel-dir dist
sha256sum dist/verifier_cross_device-*.whl
```

所有节点安装同一 wheel，或检出同一 commit：

```bash
python3 -m pip install verifier_cross_device-<version>-py3-none-any.whl --no-deps
```

设备镜像已包含厂商 PyTorch 时使用 `--no-deps`，防止通用 PyTorch 覆盖设备版本。普通依赖应在镜像构建阶段显式安装和锁定。

## 4. 隔离评测环境

评测服务会执行任务提供的 solution，应部署在独立工作容器中。现有设备基础容器仅用于生成工作镜像，不应直接安装项目或运行评测任务。

仓库提供 `deploy/container_clone.py` 创建和保存工作容器：

```bash
python3 deploy/container_clone.py clone \
  --base <base-container> \
  --work <evaluation-container> \
  --snapshot-image <base-snapshot-image> \
  --host-port 9100 \
  --container-port 9100
```

工作容器可以按阶段保存：

```bash
python3 deploy/container_clone.py save \
  --work <evaluation-container> \
  --image <evaluation-image:version> \
  --stop
```

## 5. 对象存储配置

每个评测服务只需要存储配置，不需要完整任务配置。参考 [存储配置模板](../examples/storage.ks3.example.json)：

```json
{
  "type": "ks3",
  "scheme": "https",
  "endpoint": "ks3.example.com",
  "bucket": "kernel-verification",
  "prefix": "datasets/v1",
  "ak_env": "VCD_KS3_AK",
  "sk_env": "VCD_KS3_SK"
}
```

将配置部署为 `/etc/vcd/storage.json`。配置只保存环境变量名称，不保存实际凭证。

## 6. 启动评测服务

统一环境变量：

```bash
export VCD_KS3_AK='<access-key>'
export VCD_KS3_SK='<secret-key>'
export VCD_SERVICE_TOKEN='<service-token>'
```

NVIDIA reference 示例：

```bash
vcd-evaluator \
  --backend cuda --device cuda:0 \
  --host 0.0.0.0 --port 9100 \
  --storage-config /etc/vcd/storage.json \
  --allow-solution-code --require-auth
```

target 使用同一完整命令，只修改 `--backend` 和 `--device`。例如摩尔线程使用
`--backend musa --device musa:0`，华为 Ascend 使用
`--backend ascend --device npu:0`。

需要后台运行时，可使用 `vcd-evaluator-daemon`。该命令从标准输入接收 JSON 凭证，不将密钥写入命令参数或镜像层。

## 7. 健康检查

Controller 执行任务前会调用每个服务的 `/health`。也可以独立检查：

```bash
curl \
  -H "Authorization: Bearer ${VCD_SERVICE_TOKEN}" \
  http://<evaluation-service>:9100/health
```

响应应包含服务版本、backend、device、PyTorch 版本和设备名称。正式任务开始前应确认所有节点的软件版本一致。

## 8. Controller 配置与运行

Controller 使用完整任务配置，包含一个 reference 和一个或多个 targets。配置格式见 [任务配置](configuration.md)。

```bash
vcd-controller dataset-run \
  --config /etc/vcd/run.json \
  --problem <problem-key> \
  --case <case-index> \
  --op <entry-function> \
  --report /var/lib/vcd/reports/result.json
```

任务配置中的 solution 文件只需要存在于 Controller。Controller 会读取源码、计算 SHA-256 并通过控制面发送给对应评测服务。

## 9. 升级与回滚

升级顺序建议为：

1. 构建并校验新版本；
2. 停止评测服务；
3. 保存当前工作容器或镜像；
4. 在所有节点安装同一新版本；
5. 启动服务并检查 `/health`；
6. 执行小规模回归 case；
7. 再开放正式任务。

回滚时恢复上一版本镜像或安装上一版本 wheel，并重新注入运行时凭证。
