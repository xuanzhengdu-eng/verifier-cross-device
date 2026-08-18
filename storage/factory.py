from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Storage
from .ks3 import KS3Storage
from .local import LocalStorage


def make_storage(config: dict[str, Any], base_dir: str | Path = ".") -> Storage:
    kind = str(config.get("type", "local")).lower()
    if kind == "local":
        root = config.get("root")
        if not isinstance(root, str) or not root:
            raise ValueError("local storage requires a non-empty root")
        path = Path(root)
        if not path.is_absolute():
            path = Path(base_dir) / path
        return LocalStorage(str(path))
    if kind == "ks3":
        return KS3Storage.from_config(config)
    raise ValueError(f"unsupported storage type: {kind}")

