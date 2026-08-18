"""Loopback PoC：启动本地评测服务，运行 Controller 后清理进程。

用法（自带 PYTHONPATH）：
    python examples/run_cross_poc.py
评测服务运行在同一台机器，只通过 backend 标签验证调度与比较流程。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KGB = "/share-evpfs/tj/workspace/KernelGenBench/src"
STORE = os.path.join(HERE, "_vcd_store")
RUN_JSON = os.path.join(HERE, "run.json")

sys.path.insert(0, KGB)
sys.path.insert(0, REPO)

import requests  # noqa: E402
import torch  # noqa: E402

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
EVALUATORS = [("nvidia", 9101), ("amd", 9102), ("ascend", 9103)]

env = dict(os.environ)
env["PYTHONPATH"] = os.pathsep.join([REPO, KGB, env.get("PYTHONPATH", "")])


def start_evaluator(backend, port):
    return subprocess.Popen(
        [
            sys.executable, "-m", "agent.server",
            "--backend", backend, "--port", str(port),
            "--storage", STORE, "--test-module", "examples.test_addmm",
            "--problem-key", "addmm", "--device", DEVICE,
            "--allow-solution-code",
        ],
        env=env, cwd=REPO,
    )


def wait_health(port, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    procs = []
    try:
        for backend, port in EVALUATORS:
            procs.append(start_evaluator(backend, port))
        for backend, port in EVALUATORS:
            ok = wait_health(port)
            print(f"evaluator {backend} :{port} -> {'ready' if ok else 'FAILED'}")
            if not ok:
                raise RuntimeError(f"evaluation service {backend} 未就绪")

        os.environ["VCD_MODE"] = "cross"
        import vcd
        from examples import test_addmm as T
        from examples.kgb_integration import autowire_module
        from vcd.cross import print_report

        autowire_module(T)  # controller 侧也按约定名装配（cross 分支）
        rows = vcd.run_cross(T.test_addmm, T.COMBOS, RUN_JSON)
        print_report("addmm", rows)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
