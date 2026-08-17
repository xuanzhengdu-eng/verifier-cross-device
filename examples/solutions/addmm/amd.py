import torch


def addmm(input, mat1, mat2, beta=1.0, alpha=1.0):
    # 正确实现
    return torch.addmm(input, mat1, mat2, beta=beta, alpha=alpha)
