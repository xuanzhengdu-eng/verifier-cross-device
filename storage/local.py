"""本地/共享目录后端。loopback PoC 里三个 agent + controller 共用同一个 root。"""
import os

from .base import Storage


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        return os.path.join(self.root, key)

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def get(self, key: str) -> bytes:
        with open(self._path(key), "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        out = []
        for dirpath, _, files in os.walk(base if os.path.isdir(base) else self.root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root)
                if rel.startswith(prefix):
                    out.append(rel)
        return sorted(out)
