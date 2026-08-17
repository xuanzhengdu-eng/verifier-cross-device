"""vcd — 跨机算子验证框架（KGB-agnostic 核心）

PoC 阶段只实现 local 模式：装饰器近乎透传，按 build→ref→res→compare 顺序在本机执行，
compare 由框架统一附加标准指标并捕获 pass/fail（不中断）。cross 模式后续实现。
"""
from .decorators import input_build, ref_compute, res_compute, compare, REGISTRY
from .runner import run_local, print_report
from .cross import run_cross
from .autowire import autowire
from . import context

__all__ = [
    "input_build",
    "ref_compute",
    "res_compute",
    "compare",
    "REGISTRY",
    "run_local",
    "print_report",
    "run_cross",
    "autowire",
    "context",
]
