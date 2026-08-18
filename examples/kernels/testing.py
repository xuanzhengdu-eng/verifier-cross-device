"""Shared helpers for the example operator pytest modules."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from storage import LocalStorage
from vcd import context
from vcd.operator_test import run_local_case
from vcd.solution import install_solution


def load_candidate(test_file: str):
    """Load reference.py by default, or a selected platform implementation.

    Set ``VCD_TEST_BACKEND`` to ``musa`` or ``ascend`` on the corresponding
    machine. Keeping the default as ``reference`` lets CPU-only development test
    the complete four-role and storage protocol without vendor runtimes.
    """
    backend = os.environ.get("VCD_TEST_BACKEND", "reference").strip().lower()
    if backend not in {"reference", "musa", "ascend"}:
        raise ValueError("VCD_TEST_BACKEND must be reference, musa or ascend")
    path = Path(test_file).resolve().parent / f"{backend}.py"
    module_name = f"vcd_example_{path.parent.name}_{backend}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load candidate module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected_device() -> str:
    explicit = os.environ.get("VCD_TEST_DEVICE")
    if explicit:
        return explicit
    return {
        "reference": "cpu",
        "musa": "musa:0",
        "ascend": "npu:0",
    }[os.environ.get("VCD_TEST_BACKEND", "reference").strip().lower()]


def run_operator_test(module, problem_key: str, op: str, config, candidate) -> None:
    """Run one pytest case locally or through the autowired cross controller."""
    if context.mode() == "cross":
        inputs = module.input_build(config)
        reference_output = module.compute_ref(**inputs)
        target_outputs = module.compute_res(**inputs)
        module.compare(reference_output, target_outputs)
        return

    function = getattr(candidate, op, None) or getattr(candidate, "reference", None)
    if not callable(function):
        raise TypeError(f"candidate does not define callable {op!r}")
    install_solution(op, function)
    case_index = module.COMBOS.index(config)
    with TemporaryDirectory(prefix="vcd-local-test-") as temp:
        run_local_case(
            LocalStorage(temp),
            problem_key,
            case_index,
            config,
            module,
            device=selected_device(),
        )
