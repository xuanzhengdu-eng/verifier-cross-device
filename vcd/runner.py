"""local 模式 runner：对每个参数组合跑一遍 test_ 组合体，收集指标/延迟/pass-fail。

KGB-agnostic：`combos` 由调用方枚举好传进来（cross 模式下将由 KGB 侧
`get_funcs_by_label`+`expand_params` 提供；PoC 里示例直接给 list）。
"""
from . import context


def run_local(test_func, combos) -> list[dict]:
    rows = []
    for combo in combos:
        context.new_run()
        error = None
        try:
            test_func(combo)
        except Exception as e:  # 组合体本身（build/ref/res）异常
            error = f"{type(e).__name__}: {e}"
        run = context.run() or {"compares": [], "latency": {}}
        rows.append(
            {
                "combo": combo,
                "compares": run["compares"],
                "latency": run["latency"],
                "error": error,
            }
        )
    return rows


def print_report(key: str, rows: list[dict]):
    print(f"\n=== report: {key} ===")
    for r in rows:
        combo = r["combo"]
        lat = r["latency"]
        lat_s = " ".join(f"{k}={v:.3f}ms" for k, v in lat.items())
        if r["error"]:
            print(f"[ERROR] {combo}: {r['error']}")
            continue
        for c in r["compares"]:
            verdict = "PASS" if c["passed"] else "FAIL"
            metrics = f"  {c['metrics']}" if c.get("metrics") else ""
            err = c.get("error")
            err_s = f"  ({err.splitlines()[0]})" if err else ""
            print(f"[{verdict}] {combo}  {lat_s}{metrics}{err_s}")
