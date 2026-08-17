"""agent —— 假装某个 backend 的执行 server（loopback PoC）。

启动时 import 指定 test 模块（填充 vcd.REGISTRY 的角色函数 + KGB baseline 命名空间）。
收 /execute：拉输入包 → 搬本机设备 → (res 装 solution) → 跑角色函数 → do_bench 计时 →
输出落 storage → 回 {output_key, latency_ms, device}。

loopback：所有 agent 其实跑在同一台机器（同一 CPU/GPU），只用 --backend 打标签模拟不同后端。
"""
import argparse
import importlib
import types

import torch
import triton.testing as tt
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

import kernelgenbench
import vcd
from storage import (
    LocalStorage,
    deserialize_bundle,
    serialize_output,
)


class ExecRequest(BaseModel):
    job_id: str
    problem_key: str
    op: str
    role: str  # "ref" | "res"
    input_key: str
    solution_code: str | None = None  # res 才带；.py 源码，定义 def <op>(...)


def build_app(backend: str, device: str, storage: LocalStorage) -> FastAPI:
    app = FastAPI(title=f"vcd-agent[{backend}]")

    @app.get("/health")
    def health():
        return {"status": "ok", "backend": backend, "device": device}

    @app.post("/execute")
    def execute(req: ExecRequest):
        # 1) 拉输入包 + 搬本机设备
        bundle = deserialize_bundle(storage.get(req.input_key))
        args = {
            k: (v.to(device) if torch.is_tensor(v) else v) for k, v in bundle.items()
        }

        # 2) res：把收到的 solution .py 装进 kernelgenbench.solution.<op>
        if req.role == "res":
            if not req.solution_code:
                return {"status": "error", "error": "res 缺 solution_code"}
            fn = _install_solution(req.op, req.solution_code)
            if fn is None:
                return {"status": "unsupported", "backend": backend, "op": req.op}

        # 3) 取角色函数（原始未装饰函数，agent 本地执行）
        roles = vcd.REGISTRY.get(req.problem_key, {})
        role_fn = roles.get(f"{req.role}_compute")
        if role_fn is None:
            return {"status": "error", "error": f"no {req.role}_compute for {req.problem_key}"}

        # 4) 执行一次拿输出 + do_bench 计时
        try:
            out = role_fn(**args)
            bench = tt.do_bench(lambda: role_fn(**args), quantiles=[0.5, 0.2, 0.8])
            p50 = bench[0] if isinstance(bench, (list, tuple)) else bench
            p50 = float(p50)  # type: ignore[arg-type]
        except Exception as e:  # 该后端跑不了这个算子等
            return {"status": "unsupported", "backend": backend, "op": req.op, "error": repr(e)}

        # 5) 输出落 storage
        out_key = f"{req.input_key}.out.{backend}"
        storage.put(out_key, serialize_output(out))

        return {
            "status": "success",
            "backend": backend,
            "output_key": out_key,
            "latency_ms": p50,
            "device": _device_info(backend, device),
        }

    return app


def _install_solution(op: str, code: str):
    """exec solution 源码，取 def <op>(...)，setattr 到 kernelgenbench.solution。"""
    ns: dict = {}
    exec(compile(code, f"<solution:{op}>", "exec"), ns)
    fn = ns.get(op)
    if fn is None:
        return None
    if not hasattr(kernelgenbench, "solution"):
        setattr(kernelgenbench, "solution", types.SimpleNamespace())
    setattr(kernelgenbench.solution, op, fn)
    return fn


def _device_info(backend: str, device: str) -> dict:
    info = {"backend": backend, "device": device}
    if device.startswith("cuda") and torch.cuda.is_available():
        info["name"] = torch.cuda.get_device_name(0)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, help="标签：nvidia/amd/ascend（loopback 仅打标签）")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--storage", required=True, help="共享存储根目录")
    ap.add_argument("--test-module", required=True, help="import 的 test 模块（填 REGISTRY+baseline）")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    mod = importlib.import_module(args.test_module)
    from examples.kgb_integration import autowire_module
    autowire_module(mod)  # 按约定名 + @label key 装配 4 角色 → 填充 vcd.REGISTRY
    storage = LocalStorage(args.storage)
    app = build_app(args.backend, args.device, storage)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
