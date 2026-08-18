"""Process-local registry for dynamically submitted operator solutions."""
from __future__ import annotations

from collections.abc import Callable

_SOLUTIONS: dict[str, Callable] = {}


def install_solution(op: str, function: Callable) -> None:
    if not isinstance(op, str) or not op or not callable(function):
        raise TypeError("solution requires a non-empty op and a callable")
    _SOLUTIONS[op] = function


def get_solution(op: str) -> Callable:
    try:
        return _SOLUTIONS[op]
    except KeyError as exc:
        raise RuntimeError(f"no solution is installed for operation {op!r}") from exc
