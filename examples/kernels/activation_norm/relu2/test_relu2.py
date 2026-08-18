import sys

import pytest
import torch

from examples.kernels.testing import load_candidate, run_operator_test
from vcd.solution import get_solution

from .reference import relu2 as torch_reference

PROBLEM_KEY = "activation_norm/relu2"
OP = "relu2"
COMBOS = [((8, 16), torch.float16), ((4, 7, 13), torch.float32)]
_CANDIDATE = load_candidate(__file__)


def input_build(config):
    shape, dtype = config
    generator = torch.Generator().manual_seed(100)
    return {"input": torch.randn(shape, dtype=dtype, generator=generator)}


def compute_ref(input):
    return torch_reference(input)


def compute_res(input):
    return get_solution(OP)(input)


def compare(ref_out, res_out):
    torch.testing.assert_close(res_out, ref_out, atol=1e-3, rtol=1e-3)


@pytest.mark.parametrize("config", COMBOS)
def test_relu2(config):
    run_operator_test(sys.modules[__name__], PROBLEM_KEY, OP, config, _CANDIDATE)
