import flag_gems
import torch_musa  # noqa: F401 - registers the MUSA runtime with PyTorch


def reference(input):
    x = flag_gems.relu(input.float())
    return flag_gems.mul(x, x).to(input.dtype)
