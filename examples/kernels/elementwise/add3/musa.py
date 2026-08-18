import flag_gems
import torch_musa  # noqa: F401 - registers the MUSA runtime with PyTorch


def reference(a, b, c):
    return flag_gems.add(flag_gems.add(a, b), c)
