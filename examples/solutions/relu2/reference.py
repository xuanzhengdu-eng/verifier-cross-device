import torch


def reference(input):
    x = torch.relu(input.float())
    return (x * x).to(input.dtype)

