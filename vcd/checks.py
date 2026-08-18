"""Correctness strategies for comparing device output with KS3 golden output."""
from __future__ import annotations

from typing import Callable

import torch

_TOLERANCES = {
    torch.float32: {"atol": 1e-4, "rtol": 1e-4},
    torch.bfloat16: {"atol": 1.5e-2, "rtol": 1.5e-2},
    torch.float16: {"atol": 1e-2, "rtol": 1e-2},
}
_DEFAULT_TOLERANCE = {"atol": 1e-2, "rtol": 1e-2}


def _tolerance_for(dtype: torch.dtype) -> dict[str, float]:
    return dict(_TOLERANCES.get(dtype, _DEFAULT_TOLERANCE))


def _compute_errors(actual: torch.Tensor, expected: torch.Tensor) -> dict:
    if actual.shape != expected.shape:
        return {
            "max_err": float("inf"),
            "mean_err": float("inf"),
            "nan_mismatch": 0,
            "inf_mismatch": 0,
        }
    actual_float = actual.to(torch.float32)
    expected_float = expected.to(torch.float32)
    actual_nan = torch.isnan(actual_float)
    expected_nan = torch.isnan(expected_float)
    nan_mismatch = int((actual_nan != expected_nan).sum().item())
    actual_inf = torch.isinf(actual_float)
    expected_inf = torch.isinf(expected_float)
    inf_mismatch = int((actual_inf != expected_inf).sum().item())
    both_inf = actual_inf & expected_inf
    if both_inf.any():
        inf_mismatch += int(
            (actual_float[both_inf] != expected_float[both_inf]).sum().item()
        )
    diff = (actual_float - expected_float).abs()
    finite = diff[torch.isfinite(diff)]
    max_err = finite.max().item() if finite.numel() else 0.0
    mean_err = finite.mean().item() if finite.numel() else 0.0
    if inf_mismatch:
        max_err = float("inf")
    return {
        "max_err": max_err,
        "mean_err": mean_err,
        "nan_mismatch": nan_mismatch,
        "inf_mismatch": inf_mismatch,
    }


def _validate_lists(actual: list[torch.Tensor], expected: list[torch.Tensor]) -> str | None:
    if len(actual) != len(expected):
        return f"output count differs: expected={len(expected)}, actual={len(actual)}"
    for index, (actual_tensor, expected_tensor) in enumerate(zip(actual, expected)):
        if not torch.is_tensor(actual_tensor) or not torch.is_tensor(expected_tensor):
            return f"output {index} is not a tensor"
    return None


def _invalid_result(message: str) -> dict:
    return {
        "status": "FAIL",
        "max_err": float("inf"),
        "mean_err": float("inf"),
        "details": [{"status": "FAIL", "error": message}],
    }


def _check_standard(actual: list[torch.Tensor], expected: list[torch.Tensor], descriptor: dict) -> dict:
    invalid = _validate_lists(actual, expected)
    if invalid:
        return _invalid_result(invalid)
    custom_atol = descriptor.get("atol")
    custom_rtol = descriptor.get("rtol")
    details = []
    all_errors = []
    passed = True
    for index, (actual_tensor, expected_tensor) in enumerate(zip(actual, expected)):
        tolerance = (
            {"atol": float(custom_atol), "rtol": float(custom_rtol)}
            if custom_atol is not None and custom_rtol is not None
            else _tolerance_for(expected_tensor.dtype)
        )
        errors = _compute_errors(actual_tensor, expected_tensor)
        all_errors.append(errors)
        try:
            torch.testing.assert_close(
                actual_tensor.to(torch.float32),
                expected_tensor.to(torch.float32),
                atol=tolerance["atol"],
                rtol=tolerance["rtol"],
                equal_nan=True,
            )
            details.append(
                {"output_idx": index, "status": "PASS", **errors, **tolerance}
            )
        except (AssertionError, RuntimeError) as exc:
            passed = False
            details.append(
                {
                    "output_idx": index,
                    "status": "FAIL",
                    **errors,
                    **tolerance,
                    "error": str(exc)[:200],
                }
            )
    return {
        "status": "PASS" if passed else "FAIL",
        "max_err": max((item["max_err"] for item in all_errors), default=0.0),
        "mean_err": (
            sum(item["mean_err"] for item in all_errors) / len(all_errors)
            if all_errors
            else 0.0
        ),
        "nan_mismatch": sum(item["nan_mismatch"] for item in all_errors),
        "inf_mismatch": sum(item["inf_mismatch"] for item in all_errors),
        "details": details,
    }


def _check_exact(actual: list[torch.Tensor], expected: list[torch.Tensor], descriptor: dict) -> dict:
    invalid = _validate_lists(actual, expected)
    if invalid:
        return _invalid_result(invalid)
    details = []
    for index, (actual_tensor, expected_tensor) in enumerate(zip(actual, expected)):
        match = torch.equal(actual_tensor, expected_tensor)
        errors = _compute_errors(actual_tensor, expected_tensor)
        details.append(
            {"output_idx": index, "status": "PASS" if match else "FAIL", **errors}
        )
    passed = all(item["status"] == "PASS" for item in details)
    return {
        "status": "PASS" if passed else "FAIL",
        "max_err": max((item["max_err"] for item in details), default=0.0),
        "mean_err": (
            sum(item["mean_err"] for item in details) / len(details) if details else 0.0
        ),
        "details": details,
    }


def _check_mismatch_fraction(
    actual: list[torch.Tensor], expected: list[torch.Tensor], descriptor: dict
) -> dict:
    invalid = _validate_lists(actual, expected)
    if invalid:
        return _invalid_result(invalid)
    atol = float(descriptor.get("atol", 2e-2))
    rtol = float(descriptor.get("rtol", 2e-2))
    max_fraction = float(descriptor.get("max_fraction", 1e-2))
    multi_output = descriptor.get("multi_output", True)
    details = []

    if multi_output and len(actual) == len(expected) == 2:
        actual_quantized, actual_scale = actual
        expected_quantized, expected_scale = expected
        scale_result = _check_standard(
            [actual_scale], [expected_scale], {"type": "standard"}
        )
        scale_detail = scale_result["details"][0]
        scale_detail.update({"output_idx": 1, "name": "scale"})
        details.append(scale_detail)
        try:
            if actual_quantized.shape != expected_quantized.shape:
                raise ValueError(
                    "quantized output shape differs: "
                    f"expected={tuple(expected_quantized.shape)}, "
                    f"actual={tuple(actual_quantized.shape)}"
                )
            if actual_scale.shape != expected_scale.shape:
                raise ValueError(
                    "scale output shape differs: "
                    f"expected={tuple(expected_scale.shape)}, "
                    f"actual={tuple(actual_scale.shape)}"
                )
            if actual_quantized.shape[-1] > 0 and actual_scale.shape[-1] > 0:
                if actual_quantized.shape[-1] % actual_scale.shape[-1]:
                    raise ValueError("quantized width is not divisible by scale width")
                group_size = actual_quantized.shape[-1] // actual_scale.shape[-1]
                actual_dequantized = actual_quantized.to(torch.float32) * actual_scale.to(
                    torch.float32
                ).repeat_interleave(group_size, dim=-1)
                expected_dequantized = expected_quantized.to(
                    torch.float32
                ) * expected_scale.to(torch.float32).repeat_interleave(group_size, dim=-1)
            else:
                actual_dequantized = actual_quantized.to(torch.float32)
                expected_dequantized = expected_quantized.to(torch.float32)
            mismatch = (actual_dequantized - expected_dequantized).abs() > (
                atol + rtol * expected_dequantized.abs()
            )
            fraction = mismatch.float().mean().item() if mismatch.numel() else 0.0
            errors = _compute_errors(actual_dequantized, expected_dequantized)
            details.append(
                {
                    "output_idx": 0,
                    "name": "quantized (dequantized)",
                    "status": "PASS" if fraction < max_fraction else "FAIL",
                    "mismatch_fraction": fraction,
                    "max_fraction": max_fraction,
                    **errors,
                }
            )
        except (RuntimeError, ValueError) as exc:
            details.append(
                {
                    "output_idx": 0,
                    "name": "quantized (dequantized)",
                    "status": "FAIL",
                    "max_err": float("inf"),
                    "mean_err": float("inf"),
                    "error": str(exc),
                }
            )
    else:
        for index, (actual_tensor, expected_tensor) in enumerate(zip(actual, expected)):
            if actual_tensor.shape != expected_tensor.shape:
                details.append(
                    {
                        "output_idx": index,
                        "status": "FAIL",
                        "max_err": float("inf"),
                        "mean_err": float("inf"),
                        "error": (
                            f"shape differs: expected={tuple(expected_tensor.shape)}, "
                            f"actual={tuple(actual_tensor.shape)}"
                        ),
                    }
                )
                continue
            actual_float = actual_tensor.to(torch.float32)
            expected_float = expected_tensor.to(torch.float32)
            mismatch = (actual_float - expected_float).abs() > (
                atol + rtol * expected_float.abs()
            )
            fraction = mismatch.float().mean().item() if mismatch.numel() else 0.0
            details.append(
                {
                    "output_idx": index,
                    "status": "PASS" if fraction < max_fraction else "FAIL",
                    "mismatch_fraction": fraction,
                    "max_fraction": max_fraction,
                    **_compute_errors(actual_float, expected_float),
                }
            )
    passed = all(item["status"] == "PASS" for item in details)
    return {
        "status": "PASS" if passed else "FAIL",
        "max_err": max((item.get("max_err", 0.0) for item in details), default=0.0),
        "mean_err": (
            sum(item.get("mean_err", 0.0) for item in details) / len(details)
            if details
            else 0.0
        ),
        "details": details,
    }


def make_check_fn(descriptor: dict) -> Callable[[list[torch.Tensor], list[torch.Tensor]], dict]:
    """Build the comparison function described by a manifest check descriptor."""
    check_type = descriptor.get("type", "standard")
    strategies = {
        "standard": _check_standard,
        "exact": _check_exact,
        "mismatch_fraction": _check_mismatch_fraction,
    }
    if check_type not in strategies:
        raise ValueError(f"unsupported check strategy: {check_type}")
    strategy = strategies[check_type]

    def check(actual: list[torch.Tensor], expected: list[torch.Tensor]) -> dict:
        return strategy(actual, expected, descriptor)

    return check
