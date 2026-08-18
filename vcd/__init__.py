"""VCD cross-device kernel verification core."""

__version__ = "0.5.0"
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
    "__version__",
]
