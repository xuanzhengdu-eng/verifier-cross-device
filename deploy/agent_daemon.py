#!/usr/bin/env python3
"""Start/stop a VCD agent while receiving secrets through standard input."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

PID_FILE = Path("/run/vcd-agent.pid")
LOG_FILE = Path("/var/log/vcd-agent.log")
ALLOWED_SECRETS = {"OP_VERIFY_KS3_AK", "OP_VERIFY_KS3_SK", "VCD_AGENT_TOKEN"}


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start(agent_args: list[str]) -> None:
    if _alive(_read_pid()):
        raise SystemExit(f"VCD agent is already running with PID {_read_pid()}")
    if sys.stdin.isatty():
        raise SystemExit("start requires a JSON secret object on standard input")
    raw = sys.stdin.buffer.read(16_385)
    if len(raw) > 16_384:
        raise SystemExit("secret payload is too large")
    try:
        secrets = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid secret JSON: {exc}") from exc
    if not isinstance(secrets, dict) or set(secrets) != ALLOWED_SECRETS:
        raise SystemExit(f"secret JSON must contain exactly: {sorted(ALLOWED_SECRETS)}")
    if not all(isinstance(value, str) and value for value in secrets.values()):
        raise SystemExit("all secret values must be non-empty strings")

    first = os.fork()
    if first:
        os.waitpid(first, 0)
        for _ in range(50):
            pid = _read_pid()
            if _alive(pid):
                print(f"started PID {pid}; log={LOG_FILE}")
                return
            time.sleep(0.1)
        raise SystemExit("agent daemon did not start")

    os.setsid()
    second = os.fork()
    if second:
        os._exit(0)

    os.chdir("/")
    os.umask(0o077)
    log = LOG_FILE.open("ab", buffering=0)
    null = open(os.devnull, "rb", buffering=0)
    os.dup2(null.fileno(), 0)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    os.environ.update(secrets)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        sys.argv = ["vcd-agent", *agent_args]
        from agent.server import main

        main()
    finally:
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass


def stop() -> None:
    pid = _read_pid()
    if not _alive(pid):
        print("VCD agent is not running")
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not _alive(pid):
            try:
                PID_FILE.unlink()
            except FileNotFoundError:
                pass
            print(f"stopped PID {pid}")
            return
        time.sleep(0.1)
    raise SystemExit(f"agent PID {pid} did not stop within 10 seconds")


def status() -> None:
    pid = _read_pid()
    state = "running" if _alive(pid) else "stopped"
    print(f"{state}" + (f" PID {pid}" if pid else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("agent_args", nargs=argparse.REMAINDER)
    sub.add_parser("stop")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "start":
        agent_args = args.agent_args[1:] if args.agent_args[:1] == ["--"] else args.agent_args
        start(agent_args)
    elif args.command == "stop":
        stop()
    else:
        status()


if __name__ == "__main__":
    main()
