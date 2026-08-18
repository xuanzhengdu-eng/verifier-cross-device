"""Controller orchestration for cross-device verification."""
from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from storage import deserialize_output, make_storage, serialize_bundle

from . import context
from .client import AgentClient
from .config import RunConfig, load_run_config
from .decorators import run_compare_body
from .errors import AgentError


def _client() -> AgentClient:
    client = context.cross_client()
    if client is None:
        raise RuntimeError("cross client is not configured")
    return client


def upload_inputs(key: str, named: dict) -> str:
    storage = context.cross_storage()
    job_id = context.job_id()
    if not job_id:
        raise RuntimeError("cross run has no job_id")
    input_key = f"jobs/{job_id}/{key}/inputs.safetensors"
    storage.put(input_key, serialize_bundle(named))
    context.set_input_key(input_key)
    return input_key


def _payload(cfg: RunConfig, key: str, role: str) -> dict[str, Any]:
    return {
        "job_id": context.job_id(),
        "problem_key": key,
        "op": cfg.operation(key),
        "role": role,
        "input_key": context.input_key(),
    }


def dispatch_ref(key: str) -> dict:
    cfg: RunConfig = context.cross_config()
    response = _client().execute(cfg.reference, _payload(cfg, key, "ref"))
    if response.get("status") != "success":
        raise AgentError(
            f"reference agent {cfg.reference.backend} failed: "
            f"{response.get('error', response)}"
        )
    return response


def _dispatch_target(
    cfg: RunConfig, key: str, name: str, base_payload: dict[str, Any]
) -> tuple[str, dict]:
    spec = cfg.targets[name]
    code = cfg.solution_path(name).read_text(encoding="utf-8")
    payload = dict(base_payload)
    payload.update(
        {
            "solution_code": code,
            "solution_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        }
    )
    try:
        return name, _client().execute(spec, payload)
    except Exception as exc:
        return name, {
            "status": "error",
            "backend": spec.backend,
            "error": f"{type(exc).__name__}: {exc}",
        }


def dispatch_res(key: str) -> dict[str, dict]:
    cfg: RunConfig = context.cross_config()
    results: dict[str, dict] = {}
    # Capture thread-local run state before entering worker threads.
    base_payload = _payload(cfg, key, "res")
    with ThreadPoolExecutor(max_workers=len(cfg.targets)) as pool:
        futures = {
            pool.submit(_dispatch_target, cfg, key, name, base_payload): name
            for name in cfg.targets
        }
        for future in as_completed(futures):
            name, response = future.result()
            results[name] = response
    return {name: results[name] for name in cfg.targets}


def _output_shape_error(ref_out, res_out) -> str | None:
    ref_sequence = isinstance(ref_out, (tuple, list))
    res_sequence = isinstance(res_out, (tuple, list))
    if ref_sequence != res_sequence:
        return "reference and result output structures differ"
    if ref_sequence and len(ref_out) != len(res_out):
        return f"output count differs: reference={len(ref_out)}, result={len(res_out)}"
    return None


def run_compare(key: str, body, ref_resp: dict, res_resps: dict, args, kwargs):
    storage = context.cross_storage()
    context.record_latency("ref", ref_resp.get("latency_ms"))
    ref_out = deserialize_output(storage.get(ref_resp["output_key"]))
    for target_name, response in res_resps.items():
        head = {
            "target": target_name,
            "backend": response.get("backend", target_name),
            "latency_ms": response.get("latency_ms"),
            "timing": response.get("timing"),
            "device": response.get("device"),
            "status": response.get("status", "error"),
        }
        if response.get("status") != "success":
            head.update({"passed": False, "error": response.get("error", "agent failed")})
            context.record_compare(head)
            continue
        try:
            res_out = deserialize_output(storage.get(response["output_key"]))
            structure_error = _output_shape_error(ref_out, res_out)
            if structure_error:
                rec = {"passed": False, "error": structure_error}
            else:
                rec = run_compare_body(body, ref_out, res_out, args, kwargs)
        except Exception as exc:
            rec = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
        rec.update(head)
        context.record_compare(rec)


def preflight(cfg: RunConfig, client: AgentClient) -> dict[str, dict]:
    agents = {"reference": cfg.reference, **cfg.targets}
    results = {}
    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        futures = {pool.submit(client.health, spec): name for name, spec in agents.items()}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()
    return {name: results[name] for name in agents}


def run_cross(test_func, combos, run_config_path: str) -> list[dict]:
    cfg = load_run_config(run_config_path)
    storage = make_storage(cfg.storage, cfg.base_dir)
    client = AgentClient(cfg.http)
    context.set_cross(cfg, storage, client)
    preflight(cfg, client)

    rows = []
    for index, combo in enumerate(combos):
        job_id = uuid.uuid4().hex
        context.new_run(job_id=job_id)
        error = None
        try:
            test_func(combo)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        run = context.run() or {}
        rows.append(
            {
                "case_index": index,
                "job_id": job_id,
                "combo": combo,
                "compares": run.get("compares", []),
                "latency": run.get("latency", {}),
                "error": error,
            }
        )
    return rows


def print_report(key: str, rows: list[dict]):
    print(f"\n=== cross report: {key} ===")
    passed = failed = errors = 0
    for row in rows:
        if row["error"]:
            errors += 1
            print(f"[ERROR] case={row['case_index']} {row['combo']}: {row['error']}")
            continue
        ref_ms = row["latency"].get("ref")
        ref_text = f" ref={ref_ms:.4f}ms" if ref_ms is not None else ""
        print(f"case={row['case_index']} {row['combo']}{ref_text}")
        for compare in row["compares"]:
            verdict = "PASS" if compare.get("passed") else "FAIL"
            passed += verdict == "PASS"
            failed += verdict == "FAIL"
            latency = compare.get("latency_ms")
            latency_text = f"{latency:.4f}ms" if latency is not None else "-"
            metrics = f" {compare['metrics']}" if compare.get("metrics") else ""
            error = compare.get("error")
            error_text = f" ({error.splitlines()[0]})" if error else ""
            print(
                f"    [{verdict}] {compare.get('target', compare.get('backend')):8} "
                f"lat={latency_text}{metrics}{error_text}"
            )
    print(f"summary: pass={passed} fail={failed} case_errors={errors}")
