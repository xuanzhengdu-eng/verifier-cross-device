"""Execute a runtime reference and target kernels against manifest-based inputs."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from storage import deserialize_output, make_storage

from .checks import make_check_fn
from .client import AgentClient
from .config import AgentSpec, HttpConfig
from .errors import ConfigError

_NODE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class DatasetConfig:
    reference: AgentSpec
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
        if not isinstance(raw, dict):
            raise ConfigError("dataset configuration must be a JSON object")
        reference = AgentSpec.from_dict(raw.get("reference"), "reference")
        if not reference.solution:
            raise ConfigError("reference.solution is required")
        raw_targets = raw.get("targets")
        if not isinstance(raw_targets, dict) or not raw_targets:
            raise ConfigError("dataset targets must be a non-empty object")
        invalid_names = [
            name
            for name in raw_targets
            if not isinstance(name, str)
            or not _NODE_NAME.fullmatch(name)
            or name == "reference"
        ]
        if invalid_names:
            raise ConfigError(f"invalid or reserved target names: {invalid_names}")
        targets = {
            name: AgentSpec.from_dict(spec, f"targets.{name}", default_backend=name)
            for name, spec in raw_targets.items()
        }
        missing_solutions = [name for name, spec in targets.items() if not spec.solution]
        if missing_solutions:
            raise ConfigError(f"target solution is required: {missing_solutions}")
        storage = raw.get("storage")
        if not isinstance(storage, dict) or storage.get("type") != "ks3":
            raise ConfigError("dataset mode requires a KS3 storage object")
        return cls(
            reference=reference,
            targets=targets,
            storage=dict(storage),
            http=HttpConfig.from_dict(raw.get("http")),
            base_dir=config_path.parent,
        )

    def services(self) -> dict[str, AgentSpec]:
        return {"reference": self.reference, **self.targets}

    def solution_path(self, name: str) -> Path:
        spec = self.reference if name == "reference" else self.targets[name]
        if not spec.solution:
            raise ConfigError(f"{name}.solution is required")
        path = Path(spec.solution)
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


def _payload(
    cfg: DatasetConfig,
    name: str,
    job_id: str,
    problem: str,
    operation: str,
    input_key: str,
) -> dict[str, Any]:
    code = cfg.solution_path(name).read_text(encoding="utf-8")
    return {
        "job_id": job_id,
        "problem_key": problem,
        "op": operation,
        "role": "reference" if name == "reference" else "target",
        "executor_id": name,
        "input_format": "dataset",
        "input_key": input_key,
        "solution_code": code,
        "solution_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
    }


def _execution_record(name: str, spec: AgentSpec, response: dict[str, Any]) -> dict[str, Any]:
    record = {
        "name": name,
        "backend": response.get("backend", spec.backend),
        "status": response.get("status", "error"),
        "latency_ms": response.get("latency_ms"),
        "timing": response.get("timing"),
        "device": response.get("device"),
        "output_key": response.get("output_key"),
    }
    if response.get("status") != "success":
        record["error"] = response.get("error", "evaluation service failed")
    return record


def _comparable_outputs(actual: list, expected: list) -> tuple[list, list]:
    if len(actual) != len(expected):
        raise ValueError(
            f"output count differs: expected={len(expected)}, actual={len(actual)}"
        )
    if any(item is None for item in actual + expected):
        if any(
            actual_item is not expected_item
            for actual_item, expected_item in zip(actual, expected)
        ):
            raise ValueError("None output positions differ")
        pairs = [
            (actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
            if actual_item is not None
        ]
        return [pair[0] for pair in pairs], [pair[1] for pair in pairs]
    return actual, expected


def _speedup(reference_latency: Any, target_latency: Any) -> float | None:
    if not isinstance(reference_latency, (int, float)):
        return None
    if not isinstance(target_latency, (int, float)) or target_latency <= 0:
        return None
    return float(reference_latency) / float(target_latency)


def run_dataset(
    config_path: str,
    problem: str,
    cases: list[int] | None = None,
    op: str | None = None,
) -> list[dict[str, Any]]:
    cfg = DatasetConfig.load(config_path)
    storage = make_storage(cfg.storage, cfg.base_dir)
    client = AgentClient(cfg.http)
    services = cfg.services()

    with ThreadPoolExecutor(max_workers=len(services)) as pool:
        health_futures = {
            pool.submit(client.health, spec): name for name, spec in services.items()
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
        input_key = case.get(
            "inputs_key", f"{problem}/case_{case_index}/inputs.safetensors"
        )
        payloads = {
            name: _payload(cfg, name, job_id, problem, operation, input_key)
            for name in services
        }
        responses: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(services)) as pool:
            futures = {
                pool.submit(_dispatch, client, services[name], payload): name
                for name, payload in payloads.items()
            }
            for future in as_completed(futures):
                responses[futures[future]] = future.result()

        reference = _execution_record("reference", cfg.reference, responses["reference"])
        expected = None
        if reference["status"] == "success":
            try:
                expected = _as_output_list(
                    deserialize_output(storage.get(reference["output_key"]))
                )
            except Exception as exc:
                reference.update(
                    {
                        "status": "error",
                        "error": f"cannot read reference output: {type(exc).__name__}: {exc}",
                    }
                )

        results = []
        for name, spec in cfg.targets.items():
            response = responses[name]
            record = _execution_record(name, spec, response)
            record["target"] = name
            record["speedup_vs_reference"] = (
                _speedup(reference.get("latency_ms"), record.get("latency_ms"))
                if reference["status"] == "success"
                and response.get("status") == "success"
                else None
            )
            if reference["status"] != "success":
                record.update(
                    {
                        "status": "FAIL",
                        "passed": False,
                        "error": "reference execution failed; correctness cannot be evaluated",
                    }
                )
            elif response.get("status") != "success":
                record["passed"] = False
            else:
                try:
                    actual = _as_output_list(
                        deserialize_output(storage.get(response["output_key"]))
                    )
                    actual_check, expected_check = _comparable_outputs(actual, expected)
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
                "check_descriptor": check_descriptor,
                "reference": reference,
                "results": results,
            }
        )
    return rows


def print_dataset_report(problem: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n=== cross-device dataset report: {problem} ===")
    passed = failed = reference_failed = 0
    for row in rows:
        print(f"case={row['case_index']} job={row['job_id'][:8]}")
        reference = row["reference"]
        reference_latency = reference.get("latency_ms")
        reference_latency_text = (
            f"{reference_latency:.4f}ms" if reference_latency is not None else "-"
        )
        reference_error = reference.get("error")
        reference_error_text = (
            f" ({reference_error.splitlines()[0]})" if reference_error else ""
        )
        if reference.get("status") != "success":
            reference_failed += 1
        print(
            f"    [REFERENCE] {reference['backend']:12} "
            f"lat={reference_latency_text}{reference_error_text}"
        )
        for result in row["results"]:
            verdict = "PASS" if result.get("passed") else "FAIL"
            passed += verdict == "PASS"
            failed += verdict == "FAIL"
            latency = result.get("latency_ms")
            latency_text = f"{latency:.4f}ms" if latency is not None else "-"
            speedup = result.get("speedup_vs_reference")
            speedup_text = f" speedup={speedup:.4f}x" if speedup is not None else ""
            error = result.get("error")
            error_text = f" ({error.splitlines()[0]})" if error else ""
            print(
                f"    [{verdict}] {result['target']:12} "
                f"lat={latency_text}{speedup_text}{error_text}"
            )
    print(
        f"summary: pass={passed} fail={failed} reference_fail={reference_failed}"
    )
