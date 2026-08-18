import flag_gems
import torch_musa  # noqa: F401 - registers the MUSA runtime with PyTorch


def add_constant(src, constant):
    return flag_gems.add(src, constant)


reference = add_constant
