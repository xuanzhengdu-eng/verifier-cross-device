"""Storage 抽象接口。加后端 = 实现一个子类。"""
from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list(self, prefix: str) -> list[str]: ...
