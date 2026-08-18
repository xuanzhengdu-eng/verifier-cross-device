import sys

import pytest
import torch

from examples.kernels.testing import load_candidate, run_operator_test
from vcd.solution import get_solution

from .reference import add_constant as torch_reference

PROBLEM_KEY = "elementwise/add_constant"
OP = "add_constant"
COMBOS = [((8, 16), torch.float16, 1.25), ((3, 5, 7), torch.float32, -0.5)]
_CANDIDATE = load_candidate(__file__)


def input_build(config):
    shape, dtype, constant = config
    generator = torch.Generator().manual_seed(104)
    return {
        "src": torch.randn(shape, dtype=dtype, generator=generator),
        "constant": constant,
    }


def compute_ref(src, constant):
    return torch_reference(src, constant)


def compute_res(src, constant):
    return get_solution(OP)(src, constant)


def compare(ref_out, res_out):
    torch.testing.assert_close(res_out, ref_out, atol=1e-3, rtol=1e-3)


@pytest.mark.parametrize("config", COMBOS)
def test_add_constant(config):
    run_operator_test(sys.modules[__name__], PROBLEM_KEY, OP, config, _CANDIDATE)
