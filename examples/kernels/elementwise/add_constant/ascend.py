import flag_gems
import torch_npu  # noqa: F401 - registers the Ascend runtime with PyTorch


def reference(src, constant):
    return flag_gems.add(src, constant)
