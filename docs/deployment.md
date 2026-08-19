# 评测服务部署与重建

本文用于以下两种场景：

1. 在一台新的加速卡服务器上部署 `verifier-cross-device`；
2. 现有评测容器损坏或需要升级时，从厂商基础容器重新创建干净环境。

部署链路固定为：

```text
厂商基础容器
  → 创建只读基础快照镜像
  → 创建独立评测容器
  → 安装同一版本 verifier-cross-device
  → 配置 KS3
  → 注入 KS3 与服务凭证
  → 启动 TCP 9100 上的 HTTP 评测服务
```

基础容器只用于提供厂商驱动、PyTorch 和设备运行时。禁止直接在基础容器中安装项目、写配置或运行评测任务；所有修改只能发生在新建的评测容器中。

## 1. 部署组成

| 组件 | 作用 | 是否需要加速卡 |
| --- | --- | --- |
| Controller | 读取题目和 solution，调度 Reference/Targets，比较结果并生成报告 | 否；当前 NVIDIA 节点同时承担 Reference 执行 |
| Evaluation service | 在本机加速卡上执行 Reference 或 Target Kernel，监听 9100 | 是 |
| KS3 | 保存各节点共用的输入和各自输出 | 否 |

所有节点部署相同版本的代码。节点角色由 Controller 的任务配置和 evaluator 的 `--backend/--device` 启动参数决定，不需要维护不同的软件包。

## 2. 当前华为节点实例

华为 `10.0.0.7` 当前部署可作为重建时的参数参考：

| 项目 | 当前值 |
| --- | --- |
| 厂商基础容器 | `gosim_server` |
| 基础快照镜像 | `vcd/huawei-base:20260818` |
| 独立评测容器 | `vcd-huawei-work` |
| 已保存工作镜像 | `vcd/huawei-work:0.5.0` |
| 项目目录 | `/opt/verifier-cross-device` |
| 后端与设备 | `ascend` / `npu:0` |
| 网络 | `host` |
| 服务地址 | `10.0.0.7:9100` |

`host` 网络下 `docker ps` 不显示 `9100:9100` 端口映射。容器服务直接监听宿主机的 `0.0.0.0:9100`，这是预期行为。

## 3. 部署前准备

在目标服务器上准备本仓库，并确认 Docker、厂商驱动和基础容器可用：

```bash
export PROJECT_ROOT=/path/to/verifier-cross-device
cd "$PROJECT_ROOT"

git status --short
git rev-parse HEAD
docker inspect <base-container> >/dev/null
```

发布时应记录固定 Git commit。NVIDIA Reference 和所有国产卡 evaluator 必须使用同一 commit。

项目内的本地凭证目录为：

```text
.secrets/ks3_credentials.json
```

文件格式如下。当前工作目录的该文件已配置真实值；新服务器需要通过安全渠道复制，普通 `git clone` 不会得到该文件：

```json
{
  "problems_dir": "...",
  "ks3_ak": "...",
  "ks3_sk": "..."
}
```

`.secrets/` 已加入 `.gitignore`。即使仓库是内部仓库，也不要把真实 AK/SK 提交到 Git 历史。检查权限：

```bash
chmod 700 "$PROJECT_ROOT/.secrets"
chmod 600 "$PROJECT_ROOT/.secrets/ks3_credentials.json"
```

每套部署还需要一个 Controller 与 evaluator 共享的 Bearer token。首次部署可生成：

```bash
umask 077
openssl rand -hex 32 >"$PROJECT_ROOT/.secrets/service_token"
chmod 600 "$PROJECT_ROOT/.secrets/service_token"
```

如果 Controller 已有 token，应安全复制同一 token，而不是重新生成，否则 Controller 会收到 HTTP 401。

## 4. 创建基础快照和独立评测容器

设置本次部署参数。以华为节点为例：

```bash
export BASE_CONTAINER=gosim_server
export WORK_CONTAINER=vcd-huawei-work
export BASE_SNAPSHOT_IMAGE=vcd/huawei-base:20260818
export HOST_PORT=9100
export CONTAINER_PORT=9100
```

确认基础容器中的设备可用，但不要在其中安装或修改任何文件：

```bash
docker inspect "$BASE_CONTAINER" --format \
  'status={{.State.Status}} image={{.Config.Image}} network={{.HostConfig.NetworkMode}}'
docker exec "$BASE_CONTAINER" npu-smi info
```

创建快照和工作容器：

```bash
cd "$PROJECT_ROOT"
python3 deploy/container_clone.py clone \
  --base "$BASE_CONTAINER" \
  --work "$WORK_CONTAINER" \
  --snapshot-image "$BASE_SNAPSHOT_IMAGE" \
  --host-port "$HOST_PORT" \
  --container-port "$CONTAINER_PORT"
```

该工具执行两件事：

1. 用 `docker commit` 把基础容器当前环境保存为快照镜像；
2. 从快照启动带 `vcd.role=work` 标签的新容器，并复用设备、网络和必要的系统挂载。

默认不复用基础容器的 `/root`、`/home` 和 `/data` 挂载，防止评测任务改动原容器数据。厂商驱动和 `/etc` 等系统挂载按只读方式复用；设备日志目录仍按厂商要求可写。

检查结果：

```bash
docker inspect "$WORK_CONTAINER" --format \
  'status={{.State.Status}} role={{index .Config.Labels "vcd.role"}} base={{index .Config.Labels "vcd.base-container"}} network={{.HostConfig.NetworkMode}}'
```

## 5. 安装固定版本代码

不要直接把整个工作目录 `docker cp` 进容器，否则可能把 `.git`、缓存和 `.secrets` 一起复制。使用 `git archive` 只发送当前提交中受 Git 管理的代码：

```bash
cd "$PROJECT_ROOT"
export RELEASE_COMMIT="$(git rev-parse HEAD)"

docker exec "$WORK_CONTAINER" install -d -m 755 /opt/verifier-cross-device
git archive --format=tar "$RELEASE_COMMIT" \
  | docker exec -i "$WORK_CONTAINER" \
      tar -xf - -C /opt/verifier-cross-device
printf '%s\n' "$RELEASE_COMMIT" \
  | docker exec -i "$WORK_CONTAINER" \
      tee /opt/verifier-cross-device/.release-commit >/dev/null

docker exec "$WORK_CONTAINER" \
  python3 -m pip install --no-deps -e /opt/verifier-cross-device
```

必须使用 `--no-deps`，避免 PyPI 通用 `torch` 覆盖厂商定制 PyTorch。若缺少 FastAPI、uvicorn、pydantic、requests 或 safetensors，只在工作容器中补装并锁定版本，不修改基础容器。

验证项目和设备：

```bash
docker exec "$WORK_CONTAINER" vcd-evaluator --help >/dev/null
docker exec "$WORK_CONTAINER" \
  python3 /opt/verifier-cross-device/deploy/probe_device.py \
  --backend ascend --device npu:0
```

其他设备只修改最后一条命令：

| 设备 | `--backend` | `--device` |
| --- | --- | --- |
| NVIDIA | `cuda` | `cuda:0` |
| 摩尔线程 | `musa` | `musa:0` |
| 华为 Ascend | `ascend` | `npu:0` |

## 6. 配置 KS3

仓库提供当前内部环境使用的非密钥配置：

```text
deploy/storage.ks3.internal.json
```

把它安装到评测容器：

```bash
docker exec "$WORK_CONTAINER" install -d -m 755 /etc/vcd
docker cp "$PROJECT_ROOT/deploy/storage.ks3.internal.json" \
  "$WORK_CONTAINER":/etc/vcd/storage.json
docker exec "$WORK_CONTAINER" chmod 600 /etc/vcd/storage.json
```

该文件只包含 KS3 endpoint、bucket、prefix 和环境变量名称，不包含真实 AK/SK。Controller 和所有 evaluators 必须使用相同的 bucket 与 prefix，否则会读写不同的输入输出。

## 7. 注入凭证并启动 9100 服务

评测服务从标准输入接收一次性 JSON，然后把凭证放入服务进程环境。下面命令不会把 AK/SK 写入命令行、Docker 配置或镜像层：

```bash
cd "$PROJECT_ROOT"

jq -n \
  --slurpfile ks3 .secrets/ks3_credentials.json \
  --rawfile token .secrets/service_token \
  '{
    VCD_KS3_AK: $ks3[0].ks3_ak,
    VCD_KS3_SK: $ks3[0].ks3_sk,
    VCD_SERVICE_TOKEN: ($token | gsub("[\\r\\n]+$"; ""))
  }' \
  | docker exec -i "$WORK_CONTAINER" \
      vcd-evaluator-daemon start -- \
        --backend ascend \
        --device npu:0 \
        --host 0.0.0.0 \
        --port 9100 \
        --storage-config /etc/vcd/storage.json \
        --allow-solution-code \
        --require-auth \
        --iterations 10
```

在摩尔线程节点把 `ascend/npu:0` 改为 `musa/musa:0`；在 NVIDIA Reference 节点改为 `cuda/cuda:0`。其余参数保持一致。

查看服务状态和日志：

```bash
docker exec "$WORK_CONTAINER" vcd-evaluator-daemon status
docker exec "$WORK_CONTAINER" tail -n 100 /var/log/vcd-agent.log
ss -lntp | grep ':9100 '
```

## 8. 健康检查与跨机验证

无 token 访问返回 HTTP 401 是正常鉴权行为，不代表端口不通。携带 token 检查：

```bash
TOKEN="$(tr -d '\r\n' <"$PROJECT_ROOT/.secrets/service_token")"
curl --fail --show-error \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:9100/health"
unset TOKEN
```

响应必须包含：

- `status: ok`；
- 正确的 `backend` 与 `device`；
- 厂商 PyTorch 版本和真实设备名称。

然后从 Controller 检查远端地址：

```bash
curl --fail --show-error \
  -H "Authorization: Bearer $VCD_SERVICE_TOKEN" \
  "http://<evaluation-service-ip>:9100/health"
```

`/health` 只验证 HTTP、鉴权和设备探测。KS3 读写能力必须再通过一个小型 dataset case 验证；只有 Reference 和 Target 都成功生成 `output_key`，才说明服务端口、设备执行和 KS3 链路全部正常。

## 9. Controller 凭证和任务运行

Controller 使用同一份本地 KS3 凭证和 service token：

```bash
export VCD_KS3_AK="$(jq -r '.ks3_ak' "$PROJECT_ROOT/.secrets/ks3_credentials.json")"
export VCD_KS3_SK="$(jq -r '.ks3_sk' "$PROJECT_ROOT/.secrets/ks3_credentials.json")"
export VCD_SERVICE_TOKEN="$(tr -d '\r\n' <"$PROJECT_ROOT/.secrets/service_token")"

vcd-controller dataset-run \
  --config /etc/vcd/run.json \
  --problem <problem-key> \
  --case <case-index> \
  --op <entry-function> \
  --report /var/lib/vcd/reports/result.json
```

任务配置中的 `reference.solution` 和各 `targets.<name>.solution` 只需要存在于 Controller。Controller 读取源码、计算 SHA-256，再通过 9100 控制面发送给对应 evaluator；Tensor 输入和执行输出通过 KS3 交换。

## 10. 保存、停止和再次使用

完成安装和回归测试后保存工作容器：

```bash
cd "$PROJECT_ROOT"
python3 deploy/container_clone.py save \
  --work "$WORK_CONTAINER" \
  --image vcd/huawei-work:0.5.0
```

需要同时停止时增加 `--stop`。保存镜像会保留代码、已安装依赖和 `/etc/vcd/storage.json`，但不会保存运行中的 evaluator 进程，也不会把通过标准输入注入的凭证写进镜像。

下次使用：

```bash
python3 deploy/container_clone.py resume --work "$WORK_CONTAINER"
```

`resume` 只启动容器本身。之后必须重新执行第 7 节的“注入凭证并启动 9100 服务”，再进行健康检查。

## 11. 升级与回滚

升级顺序：

1. 在发布端固定并记录新 Git commit；
2. 停止 evaluator；
3. 保存当前工作镜像作为回滚点；
4. 在所有节点部署同一新版本；
5. 重新注入凭证并启动 9100；
6. 检查 `/health`；
7. 执行一个小型跨机 dataset case；
8. 回归通过后再开放正式任务。

停止 evaluator：

```bash
docker exec "$WORK_CONTAINER" vcd-evaluator-daemon stop
```

回滚时从上一工作镜像创建新容器，或在现有干净工作容器中安装上一固定 commit。不要通过修改厂商基础容器实现回滚。

## 12. 部署验收清单

- [ ] 基础容器未被安装项目或写入配置；
- [ ] 工作容器带有 `vcd.role=work` 和正确的 `vcd.base-container` 标签；
- [ ] 所有节点使用同一 Git commit；
- [ ] 厂商 PyTorch 未被通用 PyTorch 覆盖；
- [ ] `probe_device.py` 能在真实设备完成 Tensor 运算与同步；
- [ ] `/etc/vcd/storage.json` 不包含真实 AK/SK；
- [ ] `.secrets/` 权限为 `700`，密钥文件权限为 `600`；
- [ ] evaluator 监听 `0.0.0.0:9100`；
- [ ] 携带 token 的 `/health` 返回正确设备；
- [ ] Controller 能访问远端 9100；
- [ ] 小型 dataset case 能由 Reference 和全部 Targets 读写 KS3 并完成比较；
- [ ] 工作容器已保存为带版本号的回滚镜像。
