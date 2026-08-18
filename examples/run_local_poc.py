"""local 模式 PoC 启动器：用和 cross **完全相同**的 examples/test_addmm.py。

唯一区别在启动器、不在 test 文件：跑前把一个 solution.py 装进 kernelgenbench.solution
对应跨设备模式中评测服务从任务配置加载 solution；local 模式在单进程完成相同逻辑。
（真实 KGB 入口对应 `VCD_MODE=local test_single_operator <solution.py> --test-module test_addmm.py`。）

跑法：python examples/run_local_poc.py
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KGB = "/share-evpfs/tj/workspace/KernelGenBench/src"

os.environ.setdefault("VCD_MODE", "local")
sys.path.insert(0, KGB)
sys.path.insert(0, REPO)

import kernelgenbench  # noqa: E402
import vcd  # noqa: E402
from examples import test_addmm as T  # noqa: E402
from examples.kgb_integration import autowire_module  # noqa: E402

autowire_module(T)  # 按约定名 + @label 装配 4 角色（免手写 @vcd.*）


def install_solution(op: str, path: str):
    """加载 solution 文件并将入口函数注册到 kernelgenbench.solution。"""
    ns: dict = {}
    exec(compile(open(path).read(), path, "exec"), ns)
    if not hasattr(kernelgenbench, "solution"):
        kernelgenbench.solution = types.SimpleNamespace()
    setattr(kernelgenbench.solution, op, ns[op])


def run_with(sol_rel: str, title: str):
    install_solution("addmm", os.path.join(HERE, sol_rel))
    vcd.print_report(title, vcd.run_local(T.test_addmm, T.COMBOS))


if __name__ == "__main__":
    run_with("solutions/addmm/amd.py", "addmm (solution=amd, 正确)")
    run_with("solutions/addmm/ascend.py", "addmm (solution=ascend, 故意错)")
