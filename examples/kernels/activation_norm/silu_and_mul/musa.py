import flag_gems
import torch_musa  # noqa: F401 - registers the MUSA runtime with PyTorch


def silu_and_mul(hidden_states):
    width = hidden_states.shape[-1] // 2
    x1, x3 = hidden_states[..., :width], hidden_states[..., width:]
    output = flag_gems.mul(flag_gems.silu(x1.float()), x3.float())
    return output.to(hidden_states.dtype)


reference = silu_and_mul
