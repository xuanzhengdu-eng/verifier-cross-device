"""Local execution helper for four-role operator pytest modules."""
from __future__ import annotations

from types import ModuleType
from typing import Any

import torch

from storage import Storage, deserialize_output, serialize_output

from .dataset_format import pack_inputs, unpack_inputs

ROLE_NAMES = ("input_build", "compute_ref", "compute_res", "compare")


def run_local_case(
    storage: Storage,
    problem_key: str,
    case_index: int,
    config: Any,
    roles: ModuleType,
    *,
    device: str | torch.device = "cpu",
) -> dict[str, Any]:
    """Run one four-role case through the production storage/data protocol.

    A problem module only needs ``input_build``, ``compute_ref``, ``compute_res``
    and ``compare``. The helper deliberately uses the abstract ``Storage`` API,
    so the same protocol is exercised with LocalStorage during development and
    KS3Storage during distributed evaluation.
    """
    missing = [name for name in ROLE_NAMES if not callable(getattr(roles, name, None))]
    if missing:
        raise TypeError(f"operator test module is missing roles: {missing}")

    inputs = roles.input_build(config)
    if not isinstance(inputs, dict):
        raise TypeError("input_build must return a dict of keyword arguments")

    prefix = f"local-tests/{problem_key}/case_{case_index}"
    input_key = f"{prefix}/inputs.safetensors"
    storage.put(input_key, pack_inputs(inputs))
    if not storage.exists(input_key) or input_key not in storage.list(prefix):
        raise RuntimeError("storage backend did not persist the test input")

    tensors, scalars = unpack_inputs(storage.get(input_key), device=device)
    kwargs = {**tensors, **scalars}
    with torch.no_grad():
        reference_output = roles.compute_ref(**kwargs)
        target_output = roles.compute_res(**kwargs)

    reference_key = f"{prefix}/reference.safetensors"
    target_key = f"{prefix}/target.safetensors"
    storage.put(reference_key, serialize_output(reference_output))
    storage.put(target_key, serialize_output(target_output))
    restored_reference = deserialize_output(storage.get(reference_key))
    restored_target = deserialize_output(storage.get(target_key))
    metrics = roles.compare(restored_reference, restored_target)
    if metrics is not None and not isinstance(metrics, dict):
        raise TypeError("compare must return a dict or None")

    return {
        "problem": problem_key,
        "case_index": case_index,
        "input_key": input_key,
        "reference_key": reference_key,
        "target_key": target_key,
        "metrics": metrics or {},
    }
