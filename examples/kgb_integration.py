"""KGB 集成层（薄）：从 `@label` 取 key，调 vcd.autowire 装配题目模块的 4 角色。

这层**允许 import KGB**（get_all_labels）；vcd 本身保持 KGB-agnostic。
真实落地时这段逻辑进 KGB 的 test_single_operator.py 入口；PoC 里放这里供启动器复用。
"""
import vcd
from sandbox.verifier.test_parametrize import get_all_labels


def autowire_module(mod):
    """用模块里 @label 的 key 装配 4 角色。一文件一题：取该模块贡献的那个 label。"""
    keys = get_all_labels()
    if not keys:
        raise RuntimeError("no @label found; cannot derive problem key")
    key = keys[-1]  # 一文件一题：最近注册的即本模块的
    vcd.autowire(mod, key)
    return key
