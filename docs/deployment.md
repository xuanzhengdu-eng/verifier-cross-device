# 同一份代码部署到三个节点

## 原则

1. `10.0.9.5`、摩尔线程工作容器、华为工作容器使用同一个 Git commit 的 `verifier-cross-device`。
2. 不再复制或安装 `op-verify`；VCD 已包含 KS3、数据格式和校验实现。
3. 三端差异只存在于启动命令、设备参数和 Controller 配置。
4. 不修改两个 `gosim_server` 基础容器。
5. 密钥只在进程启动时注入，不写入代码、配置或镜像。

部署前在三个节点分别确认代码版本；输出必须一致：

```bash
git -C /opt/verifier-cross-device rev-parse HEAD
```

如果以不含 `.git` 的归档部署，则记录归档来源 commit，并用下面命令确认包版本：

```bash
python3 -c "import importlib.metadata as m; print(m.version('verifier-cross-device'))"
```

## 两台设备首次克隆容器

把本仓库的 `deploy/container_clone.py` 复制到设备宿主机。摩尔线程：

```bash
python3 container_clone.py clone \
  --base gosim_server \
  --work vcd-moer-work \
  --snapshot-image vcd/moer-base:20260818 \
  --host-port 9100 --container-port 9100
```

华为 910B：

```bash
python3 container_clone.py clone \
  --base gosim_server \
  --work vcd-huawei-work \
  --snapshot-image vcd/huawei-base:20260818 \
  --host-port 9100 --container-port 9100
```

克隆工具拒绝使用相同的基础/工作容器名，也拒绝覆盖已有工作容器。默认排除 `/data`、`/home`、`/root` 共享挂载。华为基础容器使用 host network，因此不会再创建 Docker 端口映射；摩尔 bridge network 使用 `9100:9100`。

## 部署同一仓库

在 `10.0.9.5` 安装完整依赖：

```bash
cd /root/workspace/dxz-workspace/cross-device-kernel-verification/verifier-cross-device
python3 -m pip install -e .
```

将这同一个仓库快照分别放入两个工作容器的 `/opt/verifier-cross-device`，只安装 VCD：

```bash
docker cp verifier-cross-device vcd-DEVICE-work:/opt/verifier-cross-device
docker exec vcd-DEVICE-work \
  python3 -m pip install -e /opt/verifier-cross-device --no-deps
```

设备容器的 `--no-deps` 用来保护厂商 PyTorch。部署前应确认 FastAPI、pydantic、requests、safetensors、uvicorn 已存在；缺少普通依赖时单独安装，不能替换厂商 torch。

## 启动评测服务

推荐通过已安装命令 `vcd-evaluator-daemon` 从标准输入读取且只读取：

```json
{"VCD_KS3_AK":"...","VCD_KS3_SK":"...","VCD_SERVICE_TOKEN":"..."}
```

摩尔线程参数：

```bash
python3 -c 'import json,os; print(json.dumps({k:os.environ[k] for k in ("VCD_KS3_AK","VCD_KS3_SK","VCD_SERVICE_TOKEN")}))' | \
vcd-evaluator-daemon start -- \
  --backend musa --device musa:0 \
  --host 0.0.0.0 --port 9100 \
  --storage-config /opt/verifier-cross-device/examples/run.ks3.cross-device.smoke.json \
  --allow-solution-code --require-auth --iterations 10
```

华为参数仅修改 backend/device：

```bash
python3 -c 'import json,os; print(json.dumps({k:os.environ[k] for k in ("VCD_KS3_AK","VCD_KS3_SK","VCD_SERVICE_TOKEN")}))' | \
vcd-evaluator-daemon start -- \
  --backend ascend --device npu:0 \
  --host 0.0.0.0 --port 9100 \
  --storage-config /opt/verifier-cross-device/examples/run.ks3.cross-device.smoke.json \
  --allow-solution-code --require-auth --iterations 10
```

PID 和日志分别位于 `/run/vcd-agent.pid`、`/var/log/vcd-agent.log`，文件名为旧版本兼容而保留。查看/停止：

```bash
vcd-evaluator-daemon status
vcd-evaluator-daemon stop
```

切换正式评测服务前，应停止旧的宿主机端口测试监听并确认 9100 空闲：

```bash
systemctl stop cross-device-listener-9100.service
ss -lntp | grep ':9100'
```

## Controller

`10.0.9.5` 使用同一仓库的 `vcd-controller` 命令；配置中的 `service` URL 和 solution 路径决定调用哪个评测服务、下发哪份平台实现：

```bash
vcd-controller dataset-run \
  --config examples/run.ks3.cross-device.smoke.json \
  --problem activation_norm/relu2 \
  --case 0 --op reference \
  --report reports/relu2.json
```

## 保存与恢复工作容器

保存前停止评测服务，再保存并停止工作容器：

```bash
vcd-evaluator-daemon stop
python3 container_clone.py save \
  --work vcd-DEVICE-work \
  --image vcd/DEVICE-work:20260818-v2 \
  --stop
```

下次继续使用：

```bash
python3 container_clone.py resume --work vcd-DEVICE-work
```

容器文件系统会保留，版本镜像用于回滚。环境变量密钥不会被 commit 保存，恢复后必须重新注入并启动评测服务。
