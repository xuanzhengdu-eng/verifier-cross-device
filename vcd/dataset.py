"""Run submitted kernels against op-verify datasets stored in KS3."""
from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from storage import deserialize_output, make_storage

from .client import AgentClient
from .config import AgentSpec, HttpConfig
from .errors import ConfigError


@dataclass(frozen=True)
class DatasetConfig:
    targets: dict[str, AgentSpec]
    storage: dict[str, Any]
    http: HttpConfig
    base_dir: Path

    @classmethod
    def load(cls, path: str | Path):
        config_path = Path(path).resolve()
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot load dataset configuration {config_path}: {exc}") from exc
        raw_targets = raw.get("targets")
        if not isinstance(raw_targets, dict) or not raw_targets:
            raise ConfigError("dataset targets must be a non-empty object")
        targets = {
            name: AgentSpec.from_dict(spec, f"targets.{name}", default_backend=name)
            for name, spec in raw_targets.items()
        }
        storage = raw.get("storage")
        if not isinstance(storage, dict) or storage.get("type") != "ks3":
            raise ConfigError("dataset mode requires a KS3 storage object")
        return cls(
            targets=targets,
            storage=dict(storage),
            http=HttpConfig.from_dict(raw.get("http")),
            base_dir=config_path.parent,
        )

    def solution_path(self, name: str) -> Path:
        solution = self.targets[name].solution
        if not solution:
            raise ConfigError(f"targets.{name}.solution is required")
        path = Path(solution)
        if not path.is_absolute():
            path = self.base_dir / path
        path = path.resolve()
        if not path.is_file():
            raise ConfigError(f"solution file does not exist: {path}")
        return path


def _as_output_list(output) -> list:
    if torch.is_tensor(output):
        return [output]
    if isinstance(output, (tuple, list)):
        return list(output)
    raise TypeError(f"unsupported output type: {type(output).__name__}")


def _dispatch(
    client: AgentClient,
    spec: AgentSpec,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        return client.execute(spec, payload)
    except Exception as exc:
        return {
            "status": "error",
            "backend": spec.backend,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_dataset(
    config_path: str,
    problem: str,
    cases: list[int] | None = None,
    op: str | None = None,
) -> list[dict[str, Any]]:
    try:
        from op_verify.check_strategies import make_check_fn
        from op_verify.serialization import unpack_outputs
    except ImportError as exc:
        raise RuntimeError("dataset mode requires the sibling op-verify package") from exc

    cfg = DatasetConfig.load(config_path)
    storage = make_storage(cfg.storage, cfg.base_dir)
    client = AgentClient(cfg.http)

    with ThreadPoolExecutor(max_workers=len(cfg.targets)) as pool:
        health_futures = {
            pool.submit(client.health, spec): name for name, spec in cfg.targets.items()
        }
        for future in as_completed(health_futures):
            future.result()

    manifest = json.loads(storage.get("manifest.json"))
    problem_data = manifest.get("problems", {}).get(problem)
    if not problem_data:
        raise ConfigError(f"problem is not present in KS3 manifest: {problem}")
    manifest_cases = {int(item["idx"]): item for item in problem_data.get("cases", [])}
    selected = sorted(manifest_cases) if cases is None else cases
    missing = [case for case in selected if case not in manifest_cases]
    if missing:
        raise ConfigError(f"problem {problem} has no cases: {missing}")

    operation = op or problem.rsplit("/", 1)[-1]
    check_descriptor = problem_data.get("check_descriptor", {"type": "standard"})
    check_fn = make_check_fn(check_descriptor)
    rows = []

    for case_index in selected:
        case = manifest_cases[case_index]
        job_id = uuid.uuid4().hex
        input_key = case.get("inputs_key", f"{problem}/case_{case_index}/inputs.safetensors")
        ref_key = case.get("outputs_key", f"{problem}/case_{case_index}/ref_output.safetensors")
        expected, embedded_descriptor = unpack_outputs(storage.get(ref_key), device="cpu")
        effective_descriptor = embedded_descriptor or check_descriptor
        if effective_descriptor != check_descriptor:
            check_fn = make_check_fn(effective_descriptor)

        payloads = {}
        for name, spec in cfg.targets.items():
            code = cfg.solution_path(name).read_text(encoding="utf-8")
            payloads[name] = {
                "job_id": job_id,
                "problem_key": problem,
                "op": operation,
                "role": "res",
                "input_format": "op_verify",
                "input_key": input_key,
                "solution_code": code,
                "solution_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            }

        responses = {}
        with ThreadPoolExecutor(max_workers=len(cfg.targets)) as pool:
            futures = {
                pool.submit(_dispatch, client, cfg.targets[name], payload): name
                for name, payload in payloads.items()
            }
            for future in as_completed(futures):
                responses[futures[future]] = future.result()

        results = []
        for name in cfg.targets:
            response = responses[name]
            record = {
                "target": name,
                "backend": response.get("backend", cfg.targets[name].backend),
                "status": response.get("status", "error"),
                "latency_ms": response.get("latency_ms"),
                "timing": response.get("timing"),
                "device": response.get("device"),
            }
            if response.get("status") != "success":
                record.update({"passed": False, "error": response.get("error", "agent failed")})
            else:
                try:
                    actual = _as_output_list(
                        deserialize_output(storage.get(response["output_key"]))
                    )
                    if len(actual) != len(expected):
                        raise ValueError(
                            f"output count differs: expected={len(expected)}, actual={len(actual)}"
                        )
                    if any(item is None for item in actual + expected):
                        if any(a is not e for a, e in zip(actual, expected)):
                            raise ValueError("None output positions differ")
                        tensor_pairs = [(a, e) for a, e in zip(actual, expected) if a is not None]
                        actual_check = [pair[0] for pair in tensor_pairs]
                        expected_check = [pair[1] for pair in tensor_pairs]
                    else:
                        actual_check, expected_check = actual, expected
                    check = check_fn(actual_check, expected_check)
                    record.update(check)
                    record["passed"] = check.get("status") == "PASS"
                except Exception as exc:
                    record.update(
                        {
                            "status": "FAIL",
                            "passed": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            results.append(record)

        rows.append(
            {
                "job_id": job_id,
                "problem": problem,
                "case_index": case_index,
                "inputs_key": input_key,
                "reference_key": ref_key,
                "results": results,
            }
        )
    return rows


def print_dataset_report(problem: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n=== KS3 dataset report: {problem} ===")
    passed = failed = 0
    for row in rows:
        print(f"case={row['case_index']} job={row['job_id'][:8]}")
        for result in row["results"]:
            verdict = "PASS" if result.get("passed") else "FAIL"
            passed += verdict == "PASS"
            failed += verdict == "FAIL"
            latency = result.get("latency_ms")
            latency_text = f"{latency:.4f}ms" if latency is not None else "-"
            error = result.get("error")
            error_text = f" ({error.splitlines()[0]})" if error else ""
            print(f"    [{verdict}] {result['target']:8} lat={latency_text}{error_text}")
    print(f"summary: pass={passed} fail={failed}")

