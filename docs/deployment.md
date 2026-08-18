# 两台国产服务器部署

## 安全规则

1. 不在 `gosim_server` 执行 `pip install`、`docker cp`、代码编辑或启动 VCD Agent。
2. 只对基础容器执行 `docker inspect` 和 `docker commit --pause=true`。
3. 开发和运行只使用 `vcd-moer-work`、`vcd-huawei-work`。
4. `/data`、`/home`、`/root` 共享挂载默认不复制，防止工作容器修改基础容器正在使用的数据。
5. 不删除基础容器或基础镜像。

## 首次克隆

把仓库的 `deploy/container_clone.py` 复制到两台宿主机后分别执行。

摩尔线程：

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

工具会拒绝基础容器名和工作容器名相同的操作，也会拒绝覆盖已存在的工作容器。华为基础容器使用 host network，因此不会额外创建 Docker 端口映射；摩尔默认 bridge network，会创建 `9100:9100`。

## 部署代码

只把代码复制进工作容器：

```bash
docker cp verifier-cross-device vcd-DEVICE-work:/opt/verifier-cross-device
docker cp op-verify vcd-DEVICE-work:/opt/op-verify
docker exec vcd-DEVICE-work python3 -m pip install -e /opt/op-verify --no-deps
docker exec vcd-DEVICE-work python3 -m pip install -e /opt/verifier-cross-device --no-deps
```

使用 `deploy/agent_daemon.py` 从标准输入接收 `OP_VERIFY_KS3_AK`、`OP_VERIFY_KS3_SK`、`VCD_AGENT_TOKEN`。不要把值写进命令参数、配置文件或镜像层。启动器在容器内将 Agent 后台化，PID 和日志分别位于 `/run/vcd-agent.pid`、`/var/log/vcd-agent.log`。

切换正式 Agent 前，停止之前由我们创建的宿主机 HTTP 测试监听：

```bash
systemctl stop cross-device-listener-9100.service
```

确认 `9100` 空闲后，再在工作容器中启动 Agent。

## 保存与下次使用

完成一个阶段后，先在工作容器运行 `python3 /opt/verifier-cross-device/deploy/agent_daemon.py stop`，再保存并停止工作容器：

```bash
python3 container_clone.py save \
  --work vcd-DEVICE-work \
  --image vcd/DEVICE-work:20260818-v1 \
  --stop
```

下次继续使用同一个工作容器：

```bash
python3 container_clone.py resume --work vcd-DEVICE-work
```

容器文件系统在 stop/start 之间会保留；版本镜像用于回滚或重新创建工作容器。环境变量中的密钥不会被 commit 保存，需要每次启动 Agent 时重新注入。
