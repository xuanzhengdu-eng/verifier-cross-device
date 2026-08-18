"""跨机 PoC 题目：baseline + 4 个**裸**角色函数 + test_ 组合体（label/parametrize 挂 test_ 上）。

**无手写 `@vcd.*`**：框架按函数名约定（input_build/compute_ref/compute_res/compare）
+ `@label` 的 key 自动装配（见 vcd.autowire）。local/cross 共用此文件，一字不改。

由 Controller 和评测服务共同加载。input_build 在 CPU 生成，solution 注册到
kernelgenbench.solution。
"""
import types

import torch

import kernelgenbench
from sandbox.verifier.test_parametrize import label, parametrize

# baseline（参考实现）随 benchmark 代码部署到评测环境
if not hasattr(kernelgenbench, "baseline"):
    kernelgenbench.baseline = types.SimpleNamespace()


def _baseline_addmm(input, mat1, mat2, beta=1.0, alpha=1.0):
    return torch.addmm(input, mat1, mat2, beta=beta, alpha=alpha)


kernelgenbench.baseline.addmm = _baseline_addmm


# ---- 4 个裸角色函数（无 @vcd.*）----
def input_build(config):
    m, k, n, dtype = config
    return {  # CPU 生成；运行框架负责搬运到目标设备
        "input": torch.randn(m, n, dtype=dtype),
        "mat1": torch.randn(m, k, dtype=dtype),
        "mat2": torch.randn(k, n, dtype=dtype),
        "beta": 1.0,
        "alpha": 1.0,
    }


def compute_ref(input, mat1, mat2, beta, alpha):
    return kernelgenbench.baseline.addmm(input, mat1, mat2, beta=beta, alpha=alpha)


def compute_res(input, mat1, mat2, beta, alpha):
    return kernelgenbench.solution.addmm(input, mat1, mat2, beta=beta, alpha=alpha)


def compare(ref_out, res_out, dtype=None):
    # 比较逻辑归作者：抛异常=FAIL，正常=PASS，return dict=指标进报告
    ref = ref_out.float()
    res = res_out.float()
    max_rel = ((res - ref).abs() / ref.abs().clamp_min(1e-6)).max().item()
    assert max_rel < 1e-2, f"max rel error {max_rel:.3e} exceeds 1e-2"
    return {"my_max_rel": round(max_rel, 6)}


# ---- test_ 组合体：@label/@parametrize 照旧挂这里 ----
@label("addmm")
@parametrize("config", [
    (256, 256, 256, torch.float16),
    (512, 512, 512, torch.float16),
])
def test_addmm(config):
    inp = input_build(config)
    ref_out = compute_ref(**inp)
    res_out = compute_res(**inp)
    compare(ref_out, res_out, dtype=config[-1])


COMBOS = [
    (256, 256, 256, torch.float16),
    (512, 512, 512, torch.float16),
]
