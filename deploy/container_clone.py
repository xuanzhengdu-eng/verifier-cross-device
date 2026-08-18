#!/usr/bin/env python3
"""Create, save, and resume VCD work containers without mutating base containers."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _validate_name(value: str, kind: str) -> str:
    if not _NAME.fullmatch(value):
        raise SystemExit(f"invalid {kind}: {value!r}")
    return value


def _run(args: list[str], capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout if capture else ""


def _inspect(name: str) -> dict[str, Any]:
    return json.loads(_run(["docker", "inspect", name], capture=True))[0]


def build_run_args(
    inspected: dict[str, Any],
    work: str,
    image: str,
    host_port: int,
    container_port: int,
    include_data_mounts: bool = False,
) -> list[str]:
    host = inspected["HostConfig"]
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        work,
        "--label",
        "vcd.role=work",
        "--label",
        f"vcd.base-container={inspected['Name'].lstrip('/')}",
    ]

    network = host.get("NetworkMode") or "default"
    if network == "host":
        args.extend(["--network", "host"])
    else:
        if network not in {"default", "bridge"}:
            args.extend(["--network", network])
        args.extend(["-p", f"{host_port}:{container_port}"])

    if host.get("Privileged"):
        args.append("--privileged")
    if host.get("IpcMode") not in {None, "", "private"}:
        args.extend(["--ipc", host["IpcMode"]])
    if host.get("PidMode"):
        args.extend(["--pid", host["PidMode"]])
    if host.get("ShmSize"):
        args.extend(["--shm-size", str(host["ShmSize"])])

    for device in host.get("Devices") or []:
        args.extend(
            [
                "--device",
                f"{device['PathOnHost']}:{device['PathInContainer']}:{device['CgroupPermissions']}",
            ]
        )

    for mount in inspected.get("Mounts") or []:
        destination = mount.get("Destination", "")
        if destination in {"/data", "/home", "/root"} and not include_data_mounts:
            continue
        source = mount.get("Source")
        if not source or not destination:
            continue
        read_only = destination.startswith(("/usr", "/etc")) and not destination.startswith(
            "/usr/slog"
        )
        mode = "ro" if read_only else (mount.get("Mode") or "rw")
        args.extend(["-v", f"{source}:{destination}:{mode}"])

    args.extend(
        [
            "--workdir",
            "/root",
            "--entrypoint",
            "/bin/bash",
            image,
            "-lc",
            "while true; do sleep 3600; done",
        ]
    )
    return args


def clone(args) -> None:
    base = _validate_name(args.base, "base container")
    work = _validate_name(args.work, "work container")
    if base == work:
        raise SystemExit("base and work container names must differ")
    try:
        _inspect(work)
    except subprocess.CalledProcessError:
        pass
    else:
        raise SystemExit(f"work container already exists: {work}")

    inspected = _inspect(base)
    print(f"Committing read-only base snapshot: {base} -> {args.snapshot_image}")
    _run(["docker", "commit", "--pause=true", base, args.snapshot_image])
    command = build_run_args(
        inspected,
        work,
        args.snapshot_image,
        args.host_port,
        args.container_port,
        args.include_data_mounts,
    )
    print(f"Starting isolated work container: {work}")
    _run(command)
    print(_run(["docker", "inspect", "--format={{.State.Status}}", work], capture=True).strip())


def save(args) -> None:
    work = _validate_name(args.work, "work container")
    inspected = _inspect(work)
    labels = inspected.get("Config", {}).get("Labels") or {}
    if labels.get("vcd.role") != "work":
        raise SystemExit(f"refusing to save non-VCD work container: {work}")
    _run(["docker", "commit", "--pause=true", work, args.image])
    print(f"Saved {work} -> {args.image}")
    if args.stop:
        _run(["docker", "stop", work])
        print(f"Stopped {work}; resume with: docker start {work}")


def resume(args) -> None:
    work = _validate_name(args.work, "work container")
    inspected = _inspect(work)
    labels = inspected.get("Config", {}).get("Labels") or {}
    if labels.get("vcd.role") != "work":
        raise SystemExit(f"refusing to start non-VCD work container: {work}")
    _run(["docker", "start", work])
    print(f"Started {work}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("clone")
    create.add_argument("--base", required=True)
    create.add_argument("--work", required=True)
    create.add_argument("--snapshot-image", required=True)
    create.add_argument("--host-port", type=int, default=9100)
    create.add_argument("--container-port", type=int, default=9100)
    create.add_argument(
        "--include-data-mounts",
        action="store_true",
        help="also reuse /data, /home, and /root mounts; disabled to isolate base data",
    )
    create.set_defaults(func=clone)

    save_parser = sub.add_parser("save")
    save_parser.add_argument("--work", required=True)
    save_parser.add_argument("--image", required=True)
    save_parser.add_argument("--stop", action="store_true")
    save_parser.set_defaults(func=save)

    resume_parser = sub.add_parser("resume")
    resume_parser.add_argument("--work", required=True)
    resume_parser.set_defaults(func=resume)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

