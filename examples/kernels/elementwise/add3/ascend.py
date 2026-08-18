import flag_gems
import torch_npu  # noqa: F401 - registers the Ascend runtime with PyTorch


def reference(a, b, c):
    return flag_gems.add(flag_gems.add(a, b), c)
