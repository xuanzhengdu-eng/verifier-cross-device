"""Resilient HTTP client for VCD evaluation services."""
from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import AgentSpec, HttpConfig
from .errors import AgentError


class AgentClient:
    def __init__(self, http: HttpConfig):
        retry = Retry(
            total=http.retries,
            connect=http.retries,
            read=0,
            status=http.retries,
            allowed_methods=frozenset({"GET", "HEAD"}),
            status_forcelist=(502, 503, 504),
            backoff_factor=0.25,
            raise_on_status=False,
        )
        self.session = requests.Session()
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.timeout = (http.connect_timeout, http.read_timeout)

    @staticmethod
    def _headers(spec: AgentSpec) -> dict[str, str]:
        token = spec.token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def health(self, spec: AgentSpec) -> dict[str, Any]:
        try:
            response = self.session.get(
                spec.url + "/health", headers=self._headers(spec), timeout=self.timeout
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AgentError(
                f"evaluation service {spec.backend} health check failed at {spec.url}: {exc}"
            ) from exc
        if body.get("status") != "ok":
            raise AgentError(f"evaluation service {spec.backend} is not healthy: {body}")
        return body

    def execute(self, spec: AgentSpec, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(
                spec.url + "/execute",
                json=payload,
                headers=self._headers(spec),
                timeout=self.timeout,
            )
            if not response.ok:
                detail = response.text[:1000]
                raise AgentError(
                    f"evaluation service {spec.backend} returned HTTP "
                    f"{response.status_code}: {detail}"
                )
            body = response.json()
        except AgentError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise AgentError(
                f"evaluation service {spec.backend} execute failed at {spec.url}: {exc}"
            ) from exc
        if not isinstance(body, dict):
            raise AgentError(
                f"evaluation service {spec.backend} returned a non-object response"
            )
        return body
