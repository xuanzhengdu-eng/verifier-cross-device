import torch.nn.functional as F


def reference(hidden_states):
    width = hidden_states.shape[-1] // 2
    x1, x3 = hidden_states[..., :width], hidden_states[..., width:]
    output = F.silu(x1.float()) * x3.float()
    return output.to(hidden_states.dtype)
