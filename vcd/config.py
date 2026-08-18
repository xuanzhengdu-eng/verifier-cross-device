"""Validated run configuration shared by the controller and CLI."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ConfigError


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class AgentSpec:
    backend: str
    url: str
    solution: str | None = None
    token_env: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], where: str, default_backend: str | None = None):
        if not isinstance(raw, dict):
            raise ConfigError(f"{where} must be an object")
        backend = _require_string(raw.get("backend", default_backend), f"{where}.backend")
        url = _require_string(
            raw.get("service", raw.get("agent", raw.get("url"))), f"{where}.service"
        )
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"{where}.service must be an http(s) URL")
        if parsed.username or parsed.password:
            raise ConfigError(f"{where}.service must not contain credentials")
        solution = raw.get("solution")
        if solution is not None:
            solution = _require_string(solution, f"{where}.solution")
        token_env = raw.get("token_env")
        if token_env is not None:
            token_env = _require_string(token_env, f"{where}.token_env")
        return cls(backend=backend, url=url.rstrip("/"), solution=solution, token_env=token_env)

    def token(self) -> str | None:
        if not self.token_env:
            return None
        value = os.environ.get(self.token_env)
        if not value:
            raise ConfigError(
                f"required service token environment variable is unset: {self.token_env}"
            )
        return value


@dataclass(frozen=True)
class HttpConfig:
    connect_timeout: float = 10.0
    read_timeout: float = 600.0
    retries: int = 2

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None):
        raw = raw or {}
        try:
            cfg = cls(
                connect_timeout=float(raw.get("connect_timeout", 10.0)),
                read_timeout=float(raw.get("read_timeout", 600.0)),
                retries=int(raw.get("retries", 2)),
            )
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"invalid http configuration: {exc}") from exc
        if cfg.connect_timeout <= 0 or cfg.read_timeout <= 0 or cfg.retries < 0:
            raise ConfigError("http timeouts must be positive and retries must be non-negative")
        return cfg


@dataclass(frozen=True)
class RunConfig:
    reference: AgentSpec
    targets: dict[str, AgentSpec]
    storage: dict[str, Any]
    problem_key: str | None = None
    op: str | None = None
    http: HttpConfig = field(default_factory=HttpConfig)
    base_dir: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def from_dict(cls, raw: dict[str, Any], base_dir: str | Path = "."):
        if not isinstance(raw, dict):
            raise ConfigError("run configuration must be a JSON object")
        reference = AgentSpec.from_dict(raw.get("reference"), "reference")
        raw_targets = raw.get("targets")
        if not isinstance(raw_targets, dict) or not raw_targets:
            raise ConfigError("targets must be a non-empty object")
        targets = {
            name: AgentSpec.from_dict(spec, f"targets.{name}", default_backend=name)
            for name, spec in raw_targets.items()
        }
        storage = raw.get("storage")
        if isinstance(storage, str):
            storage = {"type": "local", "root": storage}
        if not isinstance(storage, dict):
            raise ConfigError("storage must be a path string or an object")
        problem_key = raw.get("problem_key")
        if problem_key is not None:
            problem_key = _require_string(problem_key, "problem_key")
        op = raw.get("op")
        if op is not None:
            op = _require_string(op, "op")
        return cls(
            reference=reference,
            targets=targets,
            storage=dict(storage),
            problem_key=problem_key,
            op=op,
            http=HttpConfig.from_dict(raw.get("http")),
            base_dir=Path(base_dir).resolve(),
        )

    def operation(self, problem_key: str) -> str:
        return self.op or problem_key.rsplit("/", 1)[-1]

    def solution_path(self, target_name: str) -> Path:
        spec = self.targets[target_name]
        if not spec.solution:
            raise ConfigError(f"targets.{target_name}.solution is required")
        path = Path(spec.solution)
        if not path.is_absolute():
            path = self.base_dir / path
        path = path.resolve()
        if not path.is_file():
            raise ConfigError(f"solution file does not exist: {path}")
        return path


def load_run_config(path: str | Path) -> RunConfig:
    config_path = Path(path).resolve()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read run configuration {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {config_path}: {exc}") from exc
    return RunConfig.from_dict(raw, config_path.parent)
