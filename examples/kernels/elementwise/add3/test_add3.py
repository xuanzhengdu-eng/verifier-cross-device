import sys

import pytest
import torch

from examples.kernels.testing import load_candidate, run_operator_test
from vcd.solution import get_solution

from .reference import add3 as torch_reference

PROBLEM_KEY = "elementwise/add3"
OP = "add3"
COMBOS = [((8, 16), torch.float16), ((3, 5, 7), torch.float32)]
_CANDIDATE = load_candidate(__file__)


def input_build(config):
    shape, dtype = config
    generator = torch.Generator().manual_seed(103)
    return {
        name: torch.randn(shape, dtype=dtype, generator=generator)
        for name in ("a", "b", "c")
    }


def compute_ref(a, b, c):
    return torch_reference(a, b, c)


def compute_res(a, b, c):
    return get_solution(OP)(a, b, c)


def compare(ref_out, res_out):
    torch.testing.assert_close(res_out, ref_out, atol=1e-3, rtol=1e-3)


@pytest.mark.parametrize("config", COMBOS)
def test_add3(config):
    run_operator_test(sys.modules[__name__], PROBLEM_KEY, OP, config, _CANDIDATE)
