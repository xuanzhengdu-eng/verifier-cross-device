"""Small KS3 client used by verifier-cross-device.

KS3 exposes an S3-compatible API but uses the ``KSS`` V2 authorization prefix.
Keeping this client in-tree makes the verifier deployable without another source
repository or a heavyweight object-storage SDK.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import requests


class KS3Client:
    """Minimal authenticated client for the KS3 operations used by VCD."""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        ak: str,
        sk: str,
        prefix: str = "",
        scheme: str = "https",
        timeout: float = 60.0,
    ):
        if scheme not in {"http", "https"}:
            raise ValueError("scheme must be 'http' or 'https'")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not endpoint or not bucket or not ak or not sk:
            raise ValueError("endpoint, bucket, ak and sk must be non-empty")
        self.endpoint = endpoint.strip().rstrip("/")
        self.bucket = bucket.strip()
        self.ak = ak
        self.sk = sk
        self.prefix = prefix.strip("/")
        self.scheme = scheme
        self.timeout = timeout
        self.session = requests.Session()

    @staticmethod
    def _date() -> str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def _sign(self, method: str, resource: str, headers: dict, content_type: str = "") -> str:
        string_to_sign = (
            f"{method}\n\n{content_type}\n{headers.get('Date', '')}\n{resource}"
        )
        signature = base64.b64encode(
            hmac.new(self.sk.encode(), string_to_sign.encode(), hashlib.sha1).digest()
        ).decode()
        return f"KSS {self.ak}:{signature}"

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        if not key:
            raise ValueError("KS3 object key must be non-empty")
        return f"{self.prefix}/{key}" if self.prefix else key

    def _url(self, key: str) -> str:
        encoded = quote(key, safe="/-_.~")
        return f"{self.scheme}://{self.bucket}.{self.endpoint}/{encoded}"

    def _resource(self, key: str) -> str:
        return f"/{self.bucket}/{key}"

    @staticmethod
    def _raise(operation: str, response: requests.Response) -> None:
        body = response.text[:500]
        raise RuntimeError(f"KS3 {operation} failed [{response.status_code}]: {body}")

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        full_key = self._full_key(key)
        headers = {"Date": self._date(), "Content-Type": content_type}
        headers["Authorization"] = self._sign(
            "PUT", self._resource(full_key), headers, content_type
        )
        response = self.session.put(
            self._url(full_key), data=data, headers=headers, timeout=self.timeout
        )
        if response.status_code not in {200, 201}:
            self._raise("upload", response)

    def download(self, key: str) -> bytes:
        full_key = self._full_key(key)
        headers = {"Date": self._date()}
        headers["Authorization"] = self._sign("GET", self._resource(full_key), headers)
        response = self.session.get(
            self._url(full_key), headers=headers, timeout=self.timeout
        )
        if response.status_code != 200:
            self._raise("download", response)
        return response.content

    def exists(self, key: str) -> bool:
        full_key = self._full_key(key)
        headers = {"Date": self._date()}
        headers["Authorization"] = self._sign("HEAD", self._resource(full_key), headers)
        response = self.session.head(
            self._url(full_key), headers=headers, timeout=self.timeout
        )
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        self._raise("exists", response)

    def list_prefix(self, prefix: str, max_keys: int = 1000) -> list[str]:
        """List all keys under *prefix*, following KS3 marker pagination."""
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")
        full_prefix = f"{self.prefix}/{prefix.lstrip('/')}" if self.prefix else prefix.lstrip("/")
        resource = f"/{self.bucket}/"
        url = f"{self.scheme}://{self.bucket}.{self.endpoint}/"
        marker: str | None = None
        keys: list[str] = []
        while True:
            headers = {"Date": self._date()}
            headers["Authorization"] = self._sign("GET", resource, headers)
            params = {"prefix": full_prefix, "max-keys": str(max_keys)}
            if marker:
                params["marker"] = marker
            response = self.session.get(
                url, headers=headers, params=params, timeout=self.timeout
            )
            if response.status_code != 200:
                self._raise("list", response)
            try:
                root = ElementTree.fromstring(response.content)
            except ElementTree.ParseError as exc:
                raise RuntimeError("KS3 list returned invalid XML") from exc
            page = [
                element.text or ""
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "Key"
            ]
            keys.extend(page)
            values = {
                element.tag.rsplit("}", 1)[-1]: element.text or ""
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] in {"IsTruncated", "NextMarker"}
            }
            if values.get("IsTruncated", "false").lower() != "true":
                return keys
            next_marker = values.get("NextMarker") or (page[-1] if page else "")
            if not next_marker or next_marker == marker:
                raise RuntimeError("KS3 list pagination did not provide a new marker")
            marker = next_marker

    def download_to_file(self, key: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(self.download(key))

    def upload_from_file(
        self,
        key: str,
        local_path: Path,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.upload(key, local_path.read_bytes(), content_type)
