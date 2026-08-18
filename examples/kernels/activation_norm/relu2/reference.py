import torch


def relu2(input):
    x = torch.relu(input.float())
    return (x * x).to(input.dtype)


reference = relu2
