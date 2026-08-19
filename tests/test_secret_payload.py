import json
import subprocess
import sys
from pathlib import Path

import pytest

from deploy.secret_payload import build_payload, load_credentials


SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "secret_payload.py"


def _private_file(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_build_payload_maps_repository_names_to_evaluator_names(tmp_path):
    credentials = _private_file(
        tmp_path / "ks3.json",
        json.dumps({"ks3_ak": "test-ak", "ks3_sk": "test-sk"}),
    )
    token = _private_file(tmp_path / "token", "test-token\n")

    assert build_payload(str(credentials), str(token)) == {
        "VCD_KS3_AK": "test-ak",
        "VCD_KS3_SK": "test-sk",
        "VCD_SERVICE_TOKEN": "test-token",
    }


def test_credentials_must_not_be_group_readable(tmp_path):
    credentials = tmp_path / "ks3.json"
    credentials.write_text(
        json.dumps({"ks3_ak": "test-ak", "ks3_sk": "test-sk"}),
        encoding="utf-8",
    )
    credentials.chmod(0o640)

    with pytest.raises(ValueError, match="must not be accessible"):
        load_credentials(str(credentials))


def test_cli_can_print_one_controller_field(tmp_path):
    credentials = _private_file(
        tmp_path / "ks3.json",
        json.dumps({"ks3_ak": "test-ak", "ks3_sk": "test-sk"}),
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--credentials",
            str(credentials),
            "--field",
            "ks3_ak",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == "test-ak\n"
