"""数据面存储抽象 + 后端。

- `Storage`：极简接口（put/get/exists/list）。
- `LocalStorage`：本地/共享目录后端（loopback PoC 用；KS3 后续加）。
- 序列化：safetensors（张量存张量、非张量 kwargs 进 metadata header），**不 pickle**。
"""
from .base import Storage
from .local import LocalStorage
from .ks3 import KS3Storage
from .factory import make_storage
from .serialize import (
    serialize_bundle,
    deserialize_bundle,
    serialize_output,
    deserialize_output,
)

__all__ = [
    "Storage",
    "LocalStorage",
    "KS3Storage",
    "make_storage",
    "serialize_bundle",
    "deserialize_bundle",
    "serialize_output",
    "deserialize_output",
]
