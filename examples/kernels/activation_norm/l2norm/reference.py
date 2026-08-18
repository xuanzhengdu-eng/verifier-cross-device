def l2norm(x, eps=1e-6):
    x_float = x.float()
    inverse_norm = (x_float.pow(2).sum(dim=-1, keepdim=True) + eps).rsqrt()
    return (x_float * inverse_norm).to(x.dtype)


reference = l2norm
