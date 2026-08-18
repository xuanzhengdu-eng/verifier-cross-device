"""safetensors 打包/解包：张量存张量、非张量 kwargs 进 metadata header（JSON）。

不 pickle——agent 上要跑不可信 solution，数据层不能再引入 pickle 反序列化风险。
从 bytes 读回 metadata：safetensors 头 = 8 字节小端长度 + 该长度的 JSON header（含 __metadata__）。
"""
import json
import struct

import torch
from safetensors.torch import load as st_load
from safetensors.torch import save as st_save

def _enc(v):
    if isinstance(v, torch.dtype):
        return {"__dtype__": str(v)}
    if isinstance(v, tuple):
        return {"__tuple__": [_enc(x) for x in v]}
    if isinstance(v, list):
        return {"__list__": [_enc(x) for x in v]}
    if isinstance(v, dict):
        return {"__dict__": {str(k): _enc(x) for k, x in v.items()}}
    if isinstance(v, (int, float, bool, str, type(None))):
        return v
    raise TypeError(f"unsupported scalar metadata type: {type(v).__name__}")


def _dec(v):
    if isinstance(v, dict):
        if "__dtype__" in v:
            return getattr(torch, v["__dtype__"].split(".")[-1])
        if "__list__" in v:
            return [_dec(x) for x in v["__list__"]]
        if "__tuple__" in v:
            return tuple(_dec(x) for x in v["__tuple__"])
        if "__dict__" in v:
            return {k: _dec(x) for k, x in v["__dict__"].items()}
    return v


def _read_metadata(data: bytes) -> dict:
    if len(data) < 8:
        raise ValueError("invalid safetensors payload: missing header length")
    n = struct.unpack("<Q", data[:8])[0]
    if n <= 0 or 8 + n > len(data):
        raise ValueError("invalid safetensors payload: truncated header")
    header = json.loads(data[8 : 8 + n])
    return header.get("__metadata__", {}) or {}


def serialize_bundle(named: dict) -> bytes:
    """named: {name -> Tensor | 标量}。"""
    tensors, scalars = {}, {}
    for k, v in named.items():
        if torch.is_tensor(v):
            tensors[k] = v.detach().cpu().contiguous()
        else:
            scalars[k] = _enc(v)
    meta = {"__scalars__": json.dumps(scalars)}
    if not tensors:
        # safetensors 不能存空 tensor dict；塞一个占位
        tensors["__empty__"] = torch.zeros(0)
    return st_save(tensors, metadata=meta)


def deserialize_bundle(data: bytes) -> dict:
    tensors = st_load(data)
    tensors.pop("__empty__", None)
    meta = _read_metadata(data)
    scalars = json.loads(meta.get("__scalars__", "{}"))
    out = {k: _dec(v) for k, v in scalars.items()}
    out.update(tensors)
    return out


def serialize_output(out) -> bytes:
    """Serialize a Tensor or tuple/list containing Tensor/None values."""
    if isinstance(out, (tuple, list)):
        d = {}
        none_indices = []
        for i, value in enumerate(out):
            if value is None:
                none_indices.append(i)
            elif torch.is_tensor(value):
                d[f"output__{i}"] = value.detach().cpu().contiguous()
            else:
                raise TypeError(f"unsupported output element {i}: {type(value).__name__}")
        meta = {
            "__kind__": "tuple" if isinstance(out, tuple) else "list",
            "__n__": str(len(out)),
            "__none__": json.dumps(none_indices),
        }
    else:
        if not torch.is_tensor(out):
            raise TypeError(f"unsupported output type: {type(out).__name__}")
        d = {"output__0": out.detach().cpu().contiguous()}
        meta = {"__kind__": "tensor"}
    if not d:
        d["__empty__"] = torch.zeros(0)
    return st_save(d, metadata=meta)


def deserialize_output(data: bytes):
    d = st_load(data)
    meta = _read_metadata(data)
    d.pop("__empty__", None)
    kind = meta.get("__kind__")
    if kind in {"tuple", "list"}:
        n = int(meta.get("__n__", "0"))
        none_indices = set(json.loads(meta.get("__none__", "[]")))
        values = [None if i in none_indices else d[f"output__{i}"] for i in range(n)]
        return tuple(values) if kind == "tuple" else values
    if kind != "tensor":
        raise ValueError(f"invalid output kind: {kind!r}")
    return d["output__0"]
