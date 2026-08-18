import flag_gems
import torch_musa  # noqa: F401 - registers the MUSA runtime with PyTorch


def reference(x, eps=1e-6):
    x_float = x.float()
    squared_sum = flag_gems.sum_dim(
        flag_gems.square(x_float), dim=(-1,), keepdim=True
    )
    inverse_norm = flag_gems.rsqrt(flag_gems.add(squared_sum, eps))
    return flag_gems.mul(x_float, inverse_norm).to(x.dtype)
