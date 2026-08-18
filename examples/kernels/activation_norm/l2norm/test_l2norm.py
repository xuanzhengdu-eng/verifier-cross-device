import sys

import pytest
import torch

from examples.kernels.testing import load_candidate, run_operator_test
from vcd.solution import get_solution

from .reference import l2norm as torch_reference

PROBLEM_KEY = "activation_norm/l2norm"
OP = "l2norm"
COMBOS = [((8, 32), torch.float16, 1e-6), ((2, 5, 17), torch.float32, 1e-5)]
_CANDIDATE = load_candidate(__file__)


def input_build(config):
    shape, dtype, eps = config
    generator = torch.Generator().manual_seed(102)
    return {"x": torch.randn(shape, dtype=dtype, generator=generator), "eps": eps}


def compute_ref(x, eps):
    return torch_reference(x, eps)


def compute_res(x, eps):
    return get_solution(OP)(x, eps)


def compare(ref_out, res_out):
    torch.testing.assert_close(res_out, ref_out, atol=2e-3, rtol=2e-3)


@pytest.mark.parametrize("config", COMBOS)
def test_l2norm(config):
    run_operator_test(sys.modules[__name__], PROBLEM_KEY, OP, config, _CANDIDATE)
