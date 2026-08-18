import sys

import pytest
import torch

from examples.kernels.testing import load_candidate, run_operator_test
from vcd.solution import get_solution

from .reference import silu_and_mul as torch_reference

PROBLEM_KEY = "activation_norm/silu_and_mul"
OP = "silu_and_mul"
COMBOS = [((8, 32), torch.float16), ((2, 5, 18), torch.float32)]
_CANDIDATE = load_candidate(__file__)


def input_build(config):
    shape, dtype = config
    generator = torch.Generator().manual_seed(101)
    return {
        "hidden_states": torch.randn(shape, dtype=dtype, generator=generator)
    }


def compute_ref(hidden_states):
    return torch_reference(hidden_states)


def compute_res(hidden_states):
    return get_solution(OP)(hidden_states)


def compare(ref_out, res_out):
    torch.testing.assert_close(res_out, ref_out, atol=2e-3, rtol=2e-3)


@pytest.mark.parametrize("config", COMBOS)
def test_silu_and_mul(config):
    run_operator_test(sys.modules[__name__], PROBLEM_KEY, OP, config, _CANDIDATE)
