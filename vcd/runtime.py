"""Vendor-neutral device selection, synchronization, and timing."""
from __future__ import annotations

import importlib
import math
import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable

import torch


def _load_extension(name: str) -> None:
    try:
        importlib.import_module(name)
    except ImportError:
        pass


def detect_device(requested: str = "auto") -> str:
    if requested != "auto":
        if requested.startswith("musa"):
            _load_extension("torch_musa")
        elif requested.startswith("npu"):
            _load_extension("torch_npu")
        return requested

    _load_extension("torch_musa")
    musa = getattr(torch, "musa", None)
    if musa is not None and getattr(musa, "is_available", lambda: False)():
        return "musa:0"

    _load_extension("torch_npu")
    npu = getattr(torch, "npu", None)
    if npu is not None and getattr(npu, "is_available", lambda: False)():
        return "npu:0"

    if torch.cuda.is_available():
        return "cuda:0"
    return "cpu"


def _module_for(device: str):
    kind = device.split(":", 1)[0]
    if kind == "musa":
        _load_extension("torch_musa")
        return getattr(torch, "musa", None)
    if kind == "npu":
        _load_extension("torch_npu")
        return getattr(torch, "npu", None)
    if kind == "cuda":
        return torch.cuda
    return None


def synchronize(device: str) -> None:
    module = _module_for(device)
    if module is not None and hasattr(module, "synchronize"):
        module.synchronize()


def move_to_device(value: Any, device: str) -> Any:
    if torch.is_tensor(value):
        return value.to(device)
    if isinstance(value, tuple):
        return tuple(move_to_device(v, device) for v in value)
    if isinstance(value, list):
        return [move_to_device(v, device) for v in value]
    if isinstance(value, dict):
        return {k: move_to_device(v, device) for k, v in value.items()}
    return value


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of an empty sample")
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


@dataclass(frozen=True)
class BenchmarkResult:
    p20_ms: float
    p50_ms: float
    p80_ms: float
    mean_ms: float
    iterations: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "p20_ms": self.p20_ms,
            "p50_ms": self.p50_ms,
            "p80_ms": self.p80_ms,
            "mean_ms": self.mean_ms,
            "iterations": self.iterations,
        }


def benchmark(
    func: Callable[[], Any],
    device: str,
    warmup: int = 3,
    iterations: int = 10,
) -> BenchmarkResult:
    if warmup < 0 or iterations <= 0:
        raise ValueError("warmup must be non-negative and iterations must be positive")
    for _ in range(warmup):
        func()
    synchronize(device)

    samples = []
    for _ in range(iterations):
        synchronize(device)
        started = time.perf_counter_ns()
        func()
        synchronize(device)
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return BenchmarkResult(
        p20_ms=_percentile(samples, 0.2),
        p50_ms=_percentile(samples, 0.5),
        p80_ms=_percentile(samples, 0.8),
        mean_ms=statistics.fmean(samples),
        iterations=iterations,
    )


def device_info(backend: str, device: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "backend": backend,
        "device": device,
        "torch_version": torch.__version__,
    }
    module = _module_for(device)
    if module is not None and hasattr(module, "get_device_name"):
        try:
            index = int(device.split(":", 1)[1]) if ":" in device else 0
            info["name"] = module.get_device_name(index)
        except Exception:
            pass
    return info

