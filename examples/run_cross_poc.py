"""loopback cross PoC 一键脚本：起 3 个 agent（假装 nvidia/amd/ascend）→ 跑 controller → 收尾。

用法（自带 PYTHONPATH）：
    python examples/run_cross_poc.py
所有 agent 其实跑在同一台机器（同一 GPU），只用 --backend 打标签模拟不同后端；
不需要开端口给外网、不需要三台机器。
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
AGENTS = [("nvidia", 9101), ("amd", 9102), ("ascend", 9103)]

env = dict(os.environ)
env["PYTHONPATH"] = os.pathsep.join([REPO, KGB, env.get("PYTHONPATH", "")])


def start_agent(backend, port):
    return subprocess.Popen(
        [
            sys.executable, "-m", "agent.server",
            "--backend", backend, "--port", str(port),
            "--storage", STORE, "--test-module", "examples.test_addmm",
            "--device", DEVICE,
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
        for backend, port in AGENTS:
            procs.append(start_agent(backend, port))
        for backend, port in AGENTS:
            ok = wait_health(port)
            print(f"agent {backend} :{port} -> {'ready' if ok else 'FAILED'}")
            if not ok:
                raise RuntimeError(f"agent {backend} 未就绪")

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
