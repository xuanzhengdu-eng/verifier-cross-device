#!/usr/bin/env python3
"""Build the evaluator secret JSON without requiring jq on deployment hosts."""

import argparse
import json
import os
import stat
import sys


def _read_private_text(path, label):
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise ValueError(
            "{} must not be accessible by group or other users (mode={:04o})".format(
                label, mode
            )
        )
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_credentials(path):
    raw = _read_private_text(path, "KS3 credentials file")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("KS3 credentials file must contain a JSON object")
    for key in ("ks3_ak", "ks3_sk"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError("KS3 credentials file requires a non-empty {!r}".format(key))
    return value


def load_service_token(path):
    token = _read_private_text(path, "service token file").strip()
    if not token:
        raise ValueError("service token must not be empty")
    if "\n" in token or "\r" in token:
        raise ValueError("service token must contain exactly one line")
    return token


def build_payload(credentials_path, token_path):
    credentials = load_credentials(credentials_path)
    return {
        "VCD_KS3_AK": credentials["ks3_ak"],
        "VCD_KS3_SK": credentials["ks3_sk"],
        "VCD_SERVICE_TOKEN": load_service_token(token_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--service-token")
    parser.add_argument("--field", choices=("ks3_ak", "ks3_sk"))
    args = parser.parse_args()

    try:
        if args.field:
            if args.service_token:
                parser.error("--service-token cannot be combined with --field")
            print(load_credentials(args.credentials)[args.field])
            return
        if not args.service_token:
            parser.error("--service-token is required unless --field is used")
        json.dump(
            build_payload(args.credentials, args.service_token),
            sys.stdout,
            separators=(",", ":"),
        )
        sys.stdout.write("\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
