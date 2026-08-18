"""Storage adapter backed by the KS3 client from the sibling op-verify project."""
from __future__ import annotations

import os
from typing import Any

from .base import Storage


class KS3Storage(Storage):
    def __init__(self, client: Any):
        self.client = client

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        try:
            from op_verify.storage import KS3Client
        except ImportError as exc:
            raise RuntimeError(
                "KS3 storage requires op-verify; install the sibling repository with "
                "`python -m pip install -e ../op-verify --no-deps`"
            ) from exc

        ak_env = str(config.get("ak_env", "OP_VERIFY_KS3_AK"))
        sk_env = str(config.get("sk_env", "OP_VERIFY_KS3_SK"))
        ak = os.environ.get(ak_env)
        sk = os.environ.get(sk_env)
        if not ak or not sk:
            raise RuntimeError(f"KS3 credentials must be set in {ak_env} and {sk_env}")
        kwargs = {
            "endpoint": config.get("endpoint", "ks3-cn-beijing.ksyuncs.com"),
            "bucket": config.get("bucket", "baai-sailing"),
            "ak": ak,
            "sk": sk,
            "prefix": config.get("prefix", "cross-device-kernel-verification"),
        }
        # The hardened op-verify client accepts scheme/timeout. Keep compatibility
        # with older checkouts while preferring HTTPS whenever available.
        try:
            client = KS3Client(
                **kwargs,
                scheme=config.get("scheme", "https"),
                timeout=float(config.get("timeout", 60.0)),
            )
        except TypeError:
            client = KS3Client(**kwargs)
        return cls(client)

    def put(self, key: str, data: bytes) -> None:
        self.client.upload(key, data)

    def get(self, key: str) -> bytes:
        return self.client.download(key)

    def exists(self, key: str) -> bool:
        return self.client.exists(key)

    def list(self, prefix: str) -> list[str]:
        keys = self.client.list_prefix(prefix)
        client_prefix = getattr(self.client, "prefix", "").strip("/")
        marker = client_prefix + "/" if client_prefix else ""
        return [key[len(marker):] if marker and key.startswith(marker) else key for key in keys]

