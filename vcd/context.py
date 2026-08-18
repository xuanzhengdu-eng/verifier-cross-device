"""执行上下文：模式开关 + 每次 run 的收集器 + cross 全局配置。

- VCD_MODE=local（默认）：装饰器就地执行，还原 KGB 单机行为。
- VCD_MODE=cross：装饰器把角色调用转成对各 agent 的 HTTP 请求（由 controller 驱动）。

run-scoped 状态（一个 test_ 组合体对一个 combo 的执行）：
  build 把 input_key 写进来，供同一个 run 里的 ref/res 读取；compare 记录每 res 结果。
"""
import os
import threading

_local = threading.local()

# cross 全局：run.json 解析后的配置 + storage 客户端（进程级，不随 run 变）
_CROSS = {"config": None, "storage": None, "client": None}


def mode() -> str:
    return os.environ.get("VCD_MODE", "local").lower()


# ---- cross 全局配置 ----
def set_cross(config, storage, client=None):
    _CROSS["config"] = config
    _CROSS["storage"] = storage
    _CROSS["client"] = client


def cross_config() -> dict:
    return _CROSS["config"]


def cross_storage():
    return _CROSS["storage"]


def cross_client():
    return _CROSS["client"]


# ---- run-scoped ----
def new_run(job_id: str | None = None):
    _local.run = {
        "job_id": job_id,
        "input_key": None,
        "compares": [],
        "latency": {},
    }
    return _local.run


def run():
    return getattr(_local, "run", None)


def set_input_key(key: str):
    r = run()
    if r is not None:
        r["input_key"] = key


def input_key():
    r = run()
    return r["input_key"] if r else None


def job_id():
    r = run()
    return r["job_id"] if r else None


def record_latency(role: str, ms: float):
    r = run()
    if r is not None:
        r["latency"][role] = ms


def record_compare(rec: dict):
    r = run()
    if r is not None:
        r["compares"].append(rec)
