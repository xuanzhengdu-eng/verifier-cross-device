"""本地/共享目录后端。loopback PoC 里三个 agent + controller 共用同一个 root。"""
import os
from pathlib import Path

from .base import Storage


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not key or "\x00" in key:
            raise ValueError("storage key must be a non-empty string")
        path = (self.root / key.lstrip("/")).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"storage key escapes root: {key!r}") from exc
        return path

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            f.write(data)

    def get(self, key: str) -> bytes:
        with self._path(key).open("rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix or ".")
        out = []
        scan_root = base if base.is_dir() else self.root
        for dirpath, _, files in os.walk(scan_root):
            for fn in files:
                full = Path(dirpath) / fn
                rel = str(full.relative_to(self.root))
                if rel.startswith(prefix):
                    out.append(rel)
        return sorted(out)
