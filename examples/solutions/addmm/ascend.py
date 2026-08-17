import torch


def addmm(input, mat1, mat2, beta=1.0, alpha=1.0):
    # 故意放大 10% —— 演示 cross 能抓出某个 backend 的 solution 数值不对
    return (beta * input + alpha * (mat1 @ mat2)) * 1.1
