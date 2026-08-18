from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path

import vcd
from .config import load_run_config
from .cross import print_report, run_cross
from .dataset import print_dataset_report, run_dataset


def _json_default(value):
    return str(value)


def run_command(args) -> int:
    os.environ["VCD_MODE"] = "cross"
    cfg = load_run_config(args.config)
    module = importlib.import_module(args.module)
    problem_key = args.problem_key or cfg.problem_key
    if not problem_key:
        raise SystemExit("problem key is required in run config or --problem-key")
    vcd.autowire(module, problem_key)
    test_func = getattr(module, args.test)
    combos = getattr(module, args.combos_attr)
    rows = run_cross(test_func, combos, args.config)
    print_report(problem_key, rows)
    if args.report:
        report = {
            "problem_key": problem_key,
            "config": str(Path(args.config).resolve()),
            "rows": rows,
        }
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n",
            encoding="utf-8",
        )
        print(f"report: {Path(args.report).resolve()}")
    any_failure = any(
        row["error"] or any(not item.get("passed") for item in row["compares"])
        for row in rows
    )
    return 1 if any_failure else 0


def main():
    parser = argparse.ArgumentParser(description="Cross-device kernel verification controller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run", help="run one problem across configured evaluation services"
    )
    run.add_argument("--config", required=True)
    run.add_argument("--module", required=True)
    run.add_argument("--test", required=True)
    run.add_argument("--combos-attr", default="COMBOS")
    run.add_argument("--problem-key")
    run.add_argument("--report")
    run.set_defaults(func=run_command)

    dataset = subparsers.add_parser(
        "dataset-run", help="run kernels against manifest inputs and golden outputs in KS3"
    )
    dataset.add_argument("--config", required=True)
    dataset.add_argument("--problem", required=True)
    dataset.add_argument("--case", action="append", type=int, dest="cases")
    dataset.add_argument("--op", help="solution function name; defaults to problem basename")
    dataset.add_argument("--report")
    dataset.set_defaults(func=dataset_command)
    args = parser.parse_args()
    raise SystemExit(args.func(args))


def dataset_command(args) -> int:
    rows = run_dataset(args.config, args.problem, cases=args.cases, op=args.op)
    print_dataset_report(args.problem, rows)
    if args.report:
        Path(args.report).write_text(
            json.dumps(
                {"problem": args.problem, "rows": rows},
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"report: {Path(args.report).resolve()}")
    return 1 if any(
        not result.get("passed") for row in rows for result in row["results"]
    ) else 0


if __name__ == "__main__":
    main()
