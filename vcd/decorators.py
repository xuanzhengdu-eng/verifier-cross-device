"""四个角色装饰器 + problem-key 注册表。

- local 模式：装饰器透传就地执行（还原 KGB 单机行为）；ref/res 顺带 do_bench 计时；
  compare 记 pass/fail（没报错=PASS，报错=FAIL 存完整消息），作者可选 return dict 记为指标。
- cross 模式：装饰器把角色调用转成对各 agent 的 HTTP 请求（见 vcd/cross.py）。

装饰器本身 KGB-agnostic：不关心函数体调了什么（`kernelgenbench.baseline/.solution` 是题目内容的事）。
"""
import functools

from . import context

# problem key -> {role: original func}；agent 侧按 key 查角色函数本地执行
REGISTRY: dict[str, dict] = {}


def _register(key: str, role: str, func):
    REGISTRY.setdefault(key, {})[role] = func


def _timed(func, role: str):
    """执行并记录 latency（ms）。

    计时统一用 `triton.testing.do_bench`（warmup + 多次迭代 + 分位），和 KGB 一致；
    各后端（NV/AMD/Ascend）的同步/对齐由 do_bench 内部处理，这里不分厂商。
    do_bench 只返回耗时、不返回算子输出，所以先单独取一次 output 供 compare。
    """
    import triton.testing as tt

    out = func()  # 实际输出（给 compare）
    res = tt.do_bench(func, quantiles=[0.5, 0.2, 0.8])  # 内部 warmup+多次+分位
    p50 = res[0] if isinstance(res, (list, tuple)) else res
    context.record_latency(role, float(p50))  # type: ignore[arg-type]
    return out


def _local_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _to_local_device(kwargs: dict) -> dict:
    """local 模式把 CPU 生成的张量搬到本机设备（对应 cross 里 agent 做的搬运）。"""
    import torch

    dev = _local_device()
    return {k: (v.to(dev) if torch.is_tensor(v) else v) for k, v in kwargs.items()}


def input_build(key: str):
    def deco(func):
        _register(key, "input_build", func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            named = func(*args, **kwargs)  # 本机（CPU）生成整包输入
            if context.mode() == "cross":
                from . import cross

                cross.upload_inputs(key, named)  # 序列化上传数据层 + 记 input_key
            return named

        return wrapper

    return deco


def ref_compute(key: str):
    def deco(func):
        _register(key, "ref_compute", func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if context.mode() == "cross":
                from . import cross

                return cross.dispatch_ref(key)  # 不本地执行，派到 ref agent
            # local：把 CPU 输入搬到本机设备再跑（= 单机 controller+agent 合体）
            kwargs = _to_local_device(kwargs)
            return _timed(lambda: func(*args, **kwargs), "ref")

        return wrapper

    return deco


def res_compute(key: str):
    def deco(func):
        _register(key, "res_compute", func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if context.mode() == "cross":
                from . import cross

                return cross.dispatch_res(key)  # 扇出各 res agent -> {backend: resp}
            kwargs = _to_local_device(kwargs)
            return _timed(lambda: func(*args, **kwargs), "res")

        return wrapper

    return deco


def compare(key: str):
    def deco(func):
        _register(key, "compare", func)

        @functools.wraps(func)
        def wrapper(ref_out, res_out, *args, **kwargs):
            if context.mode() == "cross":
                from . import cross

                # ref_out=ref resp；res_out={backend: resp}；逐 backend 下载比较
                return cross.run_compare(key, func, ref_out, res_out, args, kwargs)
            # local：没报错=PASS，报错=FAIL（存完整消息）；作者可选 return dict 记为指标
            rec = run_compare_body(func, ref_out, res_out, args, kwargs)
            context.record_compare(rec)
            return rec

        return wrapper

    return deco


def run_compare_body(func, ref_out, res_out, args, kwargs) -> dict:
    """accuracy 记录：**没报错 = PASS，报错 = FAIL（存完整消息）**。框架不算任何指标、不做比较。

    比较方法/容差/消息全归作者（复用 KGB `assert_close`/`assert_equal`，或自写任意逻辑）。
    作者 compare 可选 `return` 一个 dict → 原样记进 `metrics`（框架不解读；须 JSON-safe）。
    """
    rec: dict = {"passed": True, "error": None}
    try:
        ret = func(ref_out, res_out, *args, **kwargs)
        if isinstance(ret, dict):
            rec["metrics"] = ret
    except Exception as e:  # 任何异常都算 FAIL（同 KGB），存完整消息
        rec["passed"] = False
        rec["error"] = str(e)
    return rec

