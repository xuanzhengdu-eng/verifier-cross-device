"""cross 模式：controller 编排 + agent HTTP 客户端（KGB-agnostic）。

controller 自己不碰 GPU：input_build 在本机 CPU 生成 → 序列化上传数据层；
ref/res 转成对各 agent 的 /execute 请求；compare 下载 output 在 CPU 上逐 backend 比较。

run.json（见设计文档 §8.1）：
  {"reference": {"backend","agent"},
   "targets": {"<backend>": {"agent","solution"}},
   "storage": "<local path>"}
"""
import json
import os
import uuid

import requests

from . import context
from storage import (
    LocalStorage,
    deserialize_output,
    serialize_bundle,
)


def _post(agent_url: str, payload: dict) -> dict:
    r = requests.post(agent_url.rstrip("/") + "/execute", json=payload, timeout=300)
    r.raise_for_status()
    return r.json()


# ---- 被装饰器 cross 分支调用 ----
def upload_inputs(key: str, named: dict) -> str:
    """input_build 产出 → 序列化上传数据层，返回 input_key（并写进 run 上下文）。"""
    storage = context.cross_storage()
    run_id = uuid.uuid4().hex[:8]
    input_key = f"{key}/{run_id}/inputs.safetensors"
    storage.put(input_key, serialize_bundle(named))
    context.set_input_key(input_key)
    return input_key


def dispatch_ref(key: str) -> dict:
    cfg = context.cross_config()
    ref = cfg["reference"]
    payload = {
        "job_id": uuid.uuid4().hex[:8],
        "problem_key": key,
        "op": key,
        "role": "ref",
        "input_key": context.input_key(),
    }
    return _post(ref["agent"], payload)


def dispatch_res(key: str) -> dict:
    cfg = context.cross_config()
    base = cfg.get("_base", ".")
    out = {}
    for backend, spec in cfg["targets"].items():
        sol_path = os.path.join(base, spec["solution"])
        with open(sol_path, "r", encoding="utf-8") as f:
            solution_code = f.read()
        payload = {
            "job_id": uuid.uuid4().hex[:8],
            "problem_key": key,
            "op": key,
            "role": "res",
            "input_key": context.input_key(),
            "solution_code": solution_code,
        }
        out[backend] = _post(spec["agent"], payload)
    return out


def run_compare(key: str, body, ref_resp: dict, res_resps: dict, args, kwargs):
    """下载 ref/res output，逐 backend 跑作者 compare（同 local 契约）+ 记 latency/device。"""
    from .decorators import run_compare_body

    storage = context.cross_storage()
    context.record_latency("ref", ref_resp.get("latency_ms"))
    ref_out = deserialize_output(storage.get(ref_resp["output_key"]))
    for backend, resp in res_resps.items():
        head = {"backend": backend, "latency_ms": resp.get("latency_ms"),
                "device": resp.get("device")}
        if resp.get("status") != "success":
            head.update({"passed": False, "status": resp.get("status", "error"),
                         "error": resp.get("error")})
            context.record_compare(head)
            continue
        res_out = deserialize_output(storage.get(resp["output_key"]))
        rec = run_compare_body(body, ref_out, res_out, args, kwargs)  # 作者比较逻辑
        rec.update(head)  # 叠加 backend/latency/device
        context.record_compare(rec)


# ---- controller 驱动 ----
def _make_storage(spec: str, base: str):
    if spec.startswith("file://"):
        spec = spec[len("file://"):]
    if not os.path.isabs(spec):
        spec = os.path.join(base, spec)  # 相对 run.json 目录解析
    return LocalStorage(spec)


def load_run_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_base"] = os.path.dirname(os.path.abspath(path))
    return cfg


def run_cross(test_func, combos, run_config_path: str) -> list[dict]:
    cfg = load_run_config(run_config_path)
    storage = _make_storage(cfg["storage"], cfg["_base"])
    context.set_cross(cfg, storage)

    rows = []
    for combo in combos:
        context.new_run()
        error = None
        try:
            test_func(combo)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        run = context.run() or {}
        rows.append(
            {
                "combo": combo,
                "compares": run.get("compares", []),
                "latency": run.get("latency", {}),
                "error": error,
            }
        )
    return rows


def print_report(key: str, rows: list[dict]):
    print(f"\n=== cross report: {key} ===")
    for r in rows:
        if r["error"]:
            print(f"[ERROR] {r['combo']}: {r['error']}")
            continue
        ref_ms = r["latency"].get("ref")
        head = f"{r['combo']}" + (f"   ref={ref_ms:.4f}ms" if ref_ms else "")
        print(head)
        for c in r["compares"]:
            be = c["backend"]
            if not c.get("passed") and c.get("status") not in (None, "error"):
                print(f"    [{c['status'].upper()}] {be}")
                continue
            verdict = "PASS" if c.get("passed") else "FAIL"
            lat = c.get("latency_ms")
            lat_s = f"{lat:.4f}ms" if lat is not None else "-"
            metrics = f"  {c['metrics']}" if c.get("metrics") else ""
            err = c.get("error")
            err_s = f"  ({err.splitlines()[0]})" if err else ""  # 完整消息在 record 里，行内只显首行
            print(f"    [{verdict}] {be:8} lat={lat_s}{metrics}{err_s}")
