"""autowire —— 免手写 `@vcd.*`：按**函数名约定** + `@label` 的 key 自动装配 4 角色。

约定（与 KGB 对齐）：题目模块里 4 个裸函数
    input_build / compute_ref / compute_res / compare
框架 import 模块后，用本模块把它们包装成 vcd 角色行为（local 透传搬设备 / cross 发 HTTP），
并**回写模块属性**，使 `test_` 组合体里对同名函数的调用自然走包装版。

key 从 `@label` 提取（一文件一题）：不 import KGB —— 由调用方把 key 传进来（KGB 集成层从
`get_all_labels()` / `get_funcs_by_label` 拿），保持 vcd KGB-agnostic。
"""
from . import decorators as _d

# 约定角色名 -> vcd 角色装饰器工厂
_ROLE_FACTORY = {
    "input_build": _d.input_build,
    "compute_ref": _d.ref_compute,
    "compute_res": _d.res_compute,
    "compare": _d.compare,
}


def autowire(module, key: str) -> list[str]:
    """把 module 里符合约定名的裸函数包装成 vcd 角色并回写。返回已装配的角色名。"""
    wired = []
    for name, factory in _ROLE_FACTORY.items():
        func = getattr(module, name, None)
        if func is None or getattr(func, "_vcd_wired", False):
            continue
        wrapped = factory(key)(func)   # = @vcd.<role>(key) 手写的等价物
        wrapped._vcd_wired = True
        setattr(module, name, wrapped)  # 回写：test_ 组合体调用同名即走包装版
        wired.append(name)
    return wired
