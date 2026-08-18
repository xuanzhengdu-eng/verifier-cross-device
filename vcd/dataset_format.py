"""Read and write the KS3 dataset safetensors protocol used by VCD.

The wire format intentionally remains compatible with datasets already stored
under ``op-verify/v2``.  The implementation lives here so every VCD node needs
only this repository at runtime.
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import struct
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import torch
from safetensors.torch import load as st_load, save as st_save

_SCALAR_TYPES = (int, float, bool, str)


def _serialize_scalar(value: Any) -> str:
    if value is None:
        return json.dumps({"__none__": True})
    if isinstance(value, torch.dtype):
        return json.dumps({"__torch_dtype__": str(value)})
    if isinstance(value, bool):
        return json.dumps({"__bool__": value})
    if isinstance(value, (int, float, str)):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return json.dumps({"__list__": list(value)})
    raise TypeError(f"cannot serialize dataset scalar {type(value).__name__}: {value!r}")


def _deserialize_scalar(value: str) -> Any:
    parsed = json.loads(value)
    if isinstance(parsed, dict):
        if "__none__" in parsed:
            return None
        if "__torch_dtype__" in parsed:
            name = parsed["__torch_dtype__"].split(".")[-1]
            dtype = getattr(torch, name, None)
            if not isinstance(dtype, torch.dtype):
                raise ValueError(f"unknown torch dtype in dataset metadata: {name}")
            return dtype
        if "__bool__" in parsed:
            return parsed["__bool__"]
        if "__list__" in parsed:
            return parsed["__list__"]
    return parsed


def _extract_metadata(data: bytes) -> dict[str, str]:
    if len(data) < 8:
        raise ValueError("invalid safetensors dataset payload: missing header length")
    header_len = struct.unpack("<Q", data[:8])[0]
    if header_len <= 0 or 8 + header_len > len(data):
        raise ValueError("invalid safetensors dataset payload: truncated header")
    try:
        header = json.loads(data[8 : 8 + header_len].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid safetensors dataset metadata") from exc
    metadata = header.get("__metadata__", {}) or {}
    if not isinstance(metadata, dict):
        raise ValueError("invalid safetensors dataset metadata object")
    return metadata


def _split_inputs(inputs: dict[str, Any]) -> tuple[dict[str, torch.Tensor], dict[str, Any]]:
    tensors: dict[str, torch.Tensor] = {}
    scalars: dict[str, Any] = {}
    for name, value in inputs.items():
        if name == "check":
            continue
        if torch.is_tensor(value):
            tensors[name] = value
        elif value is None or isinstance(value, (*_SCALAR_TYPES, torch.dtype)):
            scalars[name] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (int, float)) for item in value
        ):
            scalars[name] = value
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            fields = dataclasses.fields(value)
            for field in fields:
                field_value = getattr(value, field.name)
                field_key = f"{name}.{field.name}"
                if torch.is_tensor(field_value):
                    tensors[field_key] = field_value
                elif field_value is None or isinstance(
                    field_value, (*_SCALAR_TYPES, torch.dtype)
                ):
                    scalars[field_key] = field_value
                elif isinstance(field_value, (list, tuple)):
                    scalars[field_key] = field_value
            scalars[f"__dataclass__{name}"] = (
                f"{type(value).__module__}.{type(value).__qualname__}"
            )
            scalars[f"__dataclass_fields__{name}"] = [field.name for field in fields]
        else:
            raise TypeError(f"cannot serialize dataset input {type(value).__name__}: {value!r}")
    return tensors, scalars


def pack_inputs(inputs: dict[str, Any]) -> bytes:
    """Pack named tensor/scalar inputs using the established dataset protocol."""
    tensors, scalars = _split_inputs(inputs)
    tensor_data = OrderedDict(
        (f"input__{name}", tensor.detach().contiguous().cpu())
        for name, tensor in tensors.items()
    )
    metadata = {
        f"scalar__{name}": _serialize_scalar(value) for name, value in scalars.items()
    }
    return st_save(tensor_data, metadata=metadata or None)


def _resolve_qualified_type(qualified_name: str):
    """Resolve nested class names by trying the longest importable module prefix."""
    parts = qualified_name.split(".")
    for split_at in range(len(parts) - 1, 0, -1):
        try:
            value = importlib.import_module(".".join(parts[:split_at]))
        except ImportError:
            continue
        try:
            for part in parts[split_at:]:
                value = getattr(value, part)
            return value
        except AttributeError:
            continue
    raise ImportError(f"cannot resolve dataclass type {qualified_name}")


def unpack_inputs(data: bytes, device: str | torch.device = "cpu") -> tuple[dict, dict]:
    """Unpack dataset bytes into tensor kwargs and scalar/object kwargs."""
    metadata = _extract_metadata(data)
    loaded = st_load(data)
    tensors = {
        key[len("input__") :]: tensor.to(device)
        for key, tensor in loaded.items()
        if key.startswith("input__")
    }
    scalars = {
        key[len("scalar__") :]: _deserialize_scalar(value)
        for key, value in metadata.items()
        if key.startswith("scalar__")
    }

    dataclass_names = {
        key[len("__dataclass__") :]
        for key in scalars
        if key.startswith("__dataclass__")
    }
    for name in dataclass_names:
        type_name = scalars.pop(f"__dataclass__{name}")
        fields = scalars.pop(f"__dataclass_fields__{name}")
        kwargs = {}
        for field in fields:
            field_key = f"{name}.{field}"
            if field_key in tensors:
                kwargs[field] = tensors.pop(field_key)
            elif field_key in scalars:
                kwargs[field] = scalars.pop(field_key)
        try:
            scalars[name] = _resolve_qualified_type(type_name)(**kwargs)
        except Exception:
            scalars[name] = SimpleNamespace(**kwargs)
    return tensors, scalars


def pack_outputs(outputs: Any, check_descriptor: dict[str, Any]) -> bytes:
    """Pack golden outputs and their comparison descriptor."""
    if torch.is_tensor(outputs):
        output_list = [outputs]
    elif isinstance(outputs, (tuple, list)):
        output_list = list(outputs)
    else:
        raise TypeError(f"unsupported dataset output type: {type(outputs).__name__}")
    tensors = OrderedDict()
    none_indices = []
    for index, output in enumerate(output_list):
        if output is None:
            none_indices.append(index)
        elif torch.is_tensor(output):
            tensors[f"output__{index}"] = output.detach().contiguous().cpu()
        else:
            raise TypeError(
                f"unsupported dataset output element {index}: {type(output).__name__}"
            )
    metadata = {
        "__check_descriptor__": json.dumps(check_descriptor),
        "__num_outputs__": str(len(output_list)),
    }
    if none_indices:
        metadata["__none_outputs__"] = json.dumps(none_indices)
    return st_save(tensors, metadata=metadata)


def unpack_outputs(
    data: bytes, device: str | torch.device = "cpu"
) -> tuple[list[torch.Tensor | None], dict[str, Any]]:
    """Unpack golden output tensors and their comparison descriptor."""
    metadata = _extract_metadata(data)
    loaded = st_load(data)
    try:
        descriptor = json.loads(metadata.get("__check_descriptor__", "{}"))
        output_count = int(metadata.get("__num_outputs__", "1"))
        none_indices = set(json.loads(metadata.get("__none_outputs__", "[]")))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid dataset output metadata") from exc
    if output_count < 0:
        raise ValueError("dataset output count must be non-negative")
    outputs: list[torch.Tensor | None] = []
    for index in range(output_count):
        if index in none_indices:
            outputs.append(None)
            continue
        key = f"output__{index}"
        if key not in loaded:
            raise ValueError(f"dataset output payload is missing {key}")
        outputs.append(loaded[key].to(device))
    return outputs, descriptor
