"""safetensors 打包/解包：张量存张量、非张量 kwargs 进 metadata header（JSON）。

不 pickle——agent 上要跑不可信 solution，数据层不能再引入 pickle 反序列化风险。
从 bytes 读回 metadata：safetensors 头 = 8 字节小端长度 + 该长度的 JSON header（含 __metadata__）。
"""
import json
import struct

import torch
from safetensors.torch import load as st_load
from safetensors.torch import save as st_save

_SCALAR_OK = (int, float, bool, str, type(None))


def _enc(v):
    if isinstance(v, torch.dtype):
        return {"__dtype__": str(v)}
    if isinstance(v, (list, tuple)):
        return {"__list__": [_enc(x) for x in v]}
    return v


def _dec(v):
    if isinstance(v, dict):
        if "__dtype__" in v:
            return getattr(torch, v["__dtype__"].split(".")[-1])
        if "__list__" in v:
            return [_dec(x) for x in v["__list__"]]
    return v


def _read_metadata(data: bytes) -> dict:
    n = struct.unpack("<Q", data[:8])[0]
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
    """out: Tensor 或 tuple/list[Tensor]。"""
    if isinstance(out, (tuple, list)):
        d = {f"output__{i}": t.detach().cpu().contiguous() for i, t in enumerate(out)}
        meta = {"__kind__": "tuple", "__n__": str(len(out))}
    else:
        d = {"output__0": out.detach().cpu().contiguous()}
        meta = {"__kind__": "tensor"}
    return st_save(d, metadata=meta)


def deserialize_output(data: bytes):
    d = st_load(data)
    meta = _read_metadata(data)
    if meta.get("__kind__") == "tuple":
        n = int(meta.get("__n__", "0"))
        return [d[f"output__{i}"] for i in range(n)]
    return d["output__0"]
