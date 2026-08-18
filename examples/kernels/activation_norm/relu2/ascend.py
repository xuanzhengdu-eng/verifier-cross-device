import flag_gems
import torch_npu  # noqa: F401 - registers the Ascend runtime with PyTorch


def reference(input):
    x = flag_gems.relu(input.float())
    return flag_gems.mul(x, x).to(input.dtype)
