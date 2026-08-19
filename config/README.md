# 配置文件

本目录保存可以随源码发布的配置模板，以及不包含真实凭证的内部 Storage 配置。

## Controller 任务配置

首次使用时复制模板：

```bash
cp config/run.example.json config/run.internal.json
```

在 `run.internal.json` 中填写：

- NVIDIA Reference evaluator 的地址和 `reference.py` 路径；
- 每个 Target evaluator 的地址和对应平台 solution 路径；
- KS3 endpoint、bucket、prefix；
- 每个服务在 Controller 上读取 token 的环境变量名称；
- HTTP 连接、读取超时和重试次数。

`config/run.internal.json` 默认被 Git 忽略。需要在内部仓库共享时，应先确认其中没有
AK、SK 或 Bearer token，再显式调整跟踪策略。

## Evaluator Storage 配置

- `storage.example.json`：通用占位模板；
- `storage.internal.json`：当前内部 KS3 的非密钥配置，可直接复制为容器内
  `/etc/vcd/storage.json`。

配置文件只写 `ak_env` 和 `sk_env`，真实凭证保存在项目根目录的 `.secrets/`，并在
启动 evaluator 时通过标准输入注入。
