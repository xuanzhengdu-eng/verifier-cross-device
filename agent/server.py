"""Cross-device evaluation service.

The service receives only artifact references and small control messages. Inputs and
outputs travel through the configured Storage backend. Submitted solution source
is intentionally disabled unless the process is started with
``--allow-solution-code``; run the service only inside an isolated work container.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import threading
import types
from typing import Literal

import torch
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import vcd
from storage import Storage, deserialize_bundle, make_storage, serialize_output
from vcd.runtime import benchmark, detect_device, device_info, move_to_device

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,199}$")


class ExecRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=128)
    problem_key: str = Field(min_length=1, max_length=200)
    op: str = Field(min_length=1, max_length=200)
    role: Literal["ref", "res", "reference", "target"]
    input_format: Literal["vcd", "dataset", "op_verify"] = "vcd"
    input_key: str = Field(min_length=1, max_length=1024)
    executor_id: str | None = Field(default=None, min_length=1, max_length=200)
    solution_code: str | None = None
    solution_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def _safe_component(value: str, name: str) -> str:
    if not _SAFE_NAME.fullmatch(value) or ".." in value.split("/"):
        raise ValueError(f"invalid {name}: {value!r}")
    return value


def _verify_bearer(expected: str | None, authorization: str | None) -> None:
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid bearer token")


def build_app(
    backend: str,
    device: str,
    storage: Storage,
    *,
    auth_token: str | None = None,
    allow_solution_code: bool = True,
    warmup: int = 3,
    iterations: int = 10,
    max_solution_bytes: int = 1_000_000,
) -> FastAPI:
    runtime_device = detect_device(device)
    execute_lock = threading.Lock()
    app = FastAPI(title=f"vcd-evaluator[{backend}]", version=vcd.__version__)

    @app.get("/health")
    def health(authorization: str | None = Header(default=None)):
        _verify_bearer(auth_token, authorization)
        return {
            "status": "ok",
            "service": "vcd-evaluator",
            "version": vcd.__version__,
            "device": device_info(backend, runtime_device),
            "registered_problems": sorted(vcd.REGISTRY),
        }

    @app.post("/execute")
    def execute(req: ExecRequest, authorization: str | None = Header(default=None)):
        _verify_bearer(auth_token, authorization)
        try:
            job_id = _safe_component(req.job_id, "job_id")
            problem_key = _safe_component(req.problem_key, "problem_key")
            op = _safe_component(req.op, "op")
            executor_id = _safe_component(req.executor_id or backend, "executor_id")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with execute_lock:
            try:
                input_data = storage.get(req.input_key)
                if req.input_format in {"dataset", "op_verify"}:
                    from vcd.dataset_format import unpack_inputs

                    tensor_args, scalar_args = unpack_inputs(input_data, device=runtime_device)
                    call_args = {**tensor_args, **scalar_args}
                else:
                    bundle = deserialize_bundle(input_data)
                    call_args = move_to_device(bundle, runtime_device)
            except Exception as exc:
                return _error("input_error", backend, op, exc)

            registry_role = {"reference": "ref", "target": "res"}.get(req.role, req.role)
            solution_fn = None
            solution_required = (
                req.input_format in {"dataset", "op_verify"} or registry_role == "res"
            )
            if req.solution_code:
                if not allow_solution_code:
                    return {
                        "status": "error",
                        "backend": backend,
                        "op": op,
                        "error": "solution source execution is disabled on this service",
                    }
                code_bytes = req.solution_code.encode("utf-8")
                if len(code_bytes) > max_solution_bytes:
                    return {
                        "status": "error",
                        "backend": backend,
                        "op": op,
                        "error": f"solution exceeds {max_solution_bytes} bytes",
                    }
                digest = hashlib.sha256(code_bytes).hexdigest()
                if req.solution_sha256 and digest != req.solution_sha256:
                    return {
                        "status": "error",
                        "backend": backend,
                        "op": op,
                        "error": "solution_sha256 does not match solution_code",
                    }
                try:
                    solution_fn = _install_solution(op, req.solution_code)
                    if solution_fn is None:
                        return {
                            "status": "unsupported",
                            "backend": backend,
                            "op": op,
                            "error": f"solution does not define callable {op!r}",
                        }
                except Exception as exc:
                    return _error("solution_error", backend, op, exc)
            elif solution_required:
                return {
                    "status": "error",
                    "backend": backend,
                    "op": op,
                    "error": f"{req.role} request is missing solution_code",
                }

            roles = vcd.REGISTRY.get(problem_key, {})
            role_fn = solution_fn or roles.get(f"{registry_role}_compute")
            if role_fn is None:
                return {
                    "status": "error",
                    "backend": backend,
                    "op": op,
                    "error": f"no {registry_role}_compute role registered for {problem_key}",
                }

            try:
                out = role_fn(**call_args)
                timing = benchmark(
                    lambda: role_fn(**call_args),
                    runtime_device,
                    warmup=warmup,
                    iterations=iterations,
                )
                output_key = (
                    f"jobs/{job_id}/{problem_key}/{req.role}/{executor_id}/output.safetensors"
                )
                storage.put(output_key, serialize_output(out))
            except Exception as exc:
                return _error("execution_error", backend, op, exc, status="unsupported")

            return {
                "status": "success",
                "backend": backend,
                "role": req.role,
                "executor_id": executor_id,
                "output_key": output_key,
                "latency_ms": timing.p50_ms,
                "timing": timing.as_dict(),
                "device": device_info(backend, runtime_device),
            }

    return app


def _error(kind: str, backend: str, op: str, exc: Exception, status: str = "error") -> dict:
    return {
        "status": status,
        "backend": backend,
        "op": op,
        "error_kind": kind,
        "error": f"{type(exc).__name__}: {exc}",
    }


def _install_solution(op: str, code: str):
    """Compile trusted solution source and expose it to KGB when KGB is present."""
    namespace: dict = {"__name__": f"vcd_solution_{op}"}
    exec(compile(code, f"<solution:{op}>", "exec"), namespace)
    fn = namespace.get(op)
    if not callable(fn):
        return None
    from vcd.solution import install_solution

    install_solution(op, fn)
    try:
        kernelgenbench = importlib.import_module("kernelgenbench")
    except ImportError:
        kernelgenbench = None
    if kernelgenbench is not None:
        if not hasattr(kernelgenbench, "solution"):
            kernelgenbench.solution = types.SimpleNamespace()
        setattr(kernelgenbench.solution, op, fn)
    return fn


def _load_storage(args) -> Storage:
    if args.storage_config:
        with open(args.storage_config, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        spec = raw.get("storage", raw)
        return make_storage(spec, os.path.dirname(os.path.abspath(args.storage_config)))
    if not args.storage:
        raise SystemExit("either --storage or --storage-config is required")
    return make_storage({"type": "local", "root": args.storage})


def _register_test_module(module_name: str, problem_key: str | None) -> None:
    module = importlib.import_module(module_name)
    if problem_key:
        vcd.autowire(module, problem_key)
        return
    if vcd.REGISTRY:
        return
    try:
        from examples.kgb_integration import autowire_module

        autowire_module(module)
    except Exception as exc:
        raise SystemExit(
            "cannot derive problem key; pass --problem-key or decorate the module roles explicitly"
        ) from exc


def main():
    parser = argparse.ArgumentParser(description="Run a cross-device evaluation service")
    parser.add_argument("--backend", required=True, help="backend label, e.g. musa or ascend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--storage", help="legacy local/shared storage root")
    parser.add_argument("--storage-config", help="JSON file containing a storage object")
    parser.add_argument(
        "--test-module", help="importable problem module (not needed for dataset-only services)"
    )
    parser.add_argument("--problem-key", help="registry key; recommended for production")
    parser.add_argument("--device", default="auto", help="auto/cpu/cuda:0/musa:0/npu:0")
    parser.add_argument("--auth-token-env", default="VCD_SERVICE_TOKEN")
    parser.add_argument("--require-auth", action="store_true")
    parser.add_argument("--allow-solution-code", action="store_true")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--max-solution-bytes", type=int, default=1_000_000)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    token = os.environ.get(args.auth_token_env)
    if args.require_auth and not token:
        raise SystemExit(f"required auth token environment variable is unset: {args.auth_token_env}")
    if args.test_module:
        _register_test_module(args.test_module, args.problem_key)
    app = build_app(
        args.backend,
        args.device,
        _load_storage(args),
        auth_token=token,
        allow_solution_code=args.allow_solution_code,
        warmup=args.warmup,
        iterations=args.iterations,
        max_solution_bytes=args.max_solution_bytes,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
