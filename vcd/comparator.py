"""**可选的作者 helper**（框架不调用它）。

框架对 accuracy 只记 pass/fail + 完整 error，不算任何指标。若作者想在报告里带一组
标准数值（即使 PASS 也想看「差多少」），可在自己的 `@vcd.compare` 里 import 本模块、
把结果 `return` 出去，框架会原样记进 `metrics`：

    from vcd.comparator import metrics
    @vcd.compare("addmm")
    def compare(ref_out, res_out, dtype=None):
        kernelgenbench.assert_close(res_out, ref_out, dtype)  # pass/fail
        return metrics(ref_out, res_out)                      # 可选：带上数值
"""
import torch


def _one(ref: torch.Tensor, res: torch.Tensor) -> dict:
    a = ref.detach().float().cpu()
    b = res.detach().float().cpu()
    diff = (a - b).abs()
    denom = a.abs().clamp_min(1e-12)
    return {
        "max_abs_error": diff.max().item() if diff.numel() else 0.0,
        "mean_abs_error": diff.mean().item() if diff.numel() else 0.0,
        "max_rel_error": (diff / denom).max().item() if diff.numel() else 0.0,
        "cosine": torch.nn.functional.cosine_similarity(
            a.flatten(), b.flatten(), dim=0, eps=1e-12
        ).item() if a.numel() else 1.0,
    }


def metrics(ref_out, res_out):
    """尽力而为：张量→一组指标；tuple/list[张量]→逐元素；其余→None。"""
    try:
        if isinstance(ref_out, (tuple, list)):
            return [_one(r, s) for r, s in zip(ref_out, res_out)]
        if torch.is_tensor(ref_out) and torch.is_tensor(res_out):
            return _one(ref_out, res_out)
    except Exception:
        pass
    return None
