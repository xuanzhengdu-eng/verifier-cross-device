import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from storage import serialize_output
from vcd.dataset import DatasetConfig, run_dataset
from vcd.errors import ConfigError


class MemoryStorage:
    def __init__(self):
        self.data = {
            "manifest.json": json.dumps(
                {
                    "version": 1,
                    "problems": {
                        "demo/add": {
                            "check_descriptor": {
                                "type": "standard",
                                "atol": 1e-4,
                                "rtol": 1e-4,
                            },
                            "cases": [{"idx": 0, "inputs_key": "demo/add/case_0/input"}],
                        }
                    },
                }
            ).encode()
        }

    def put(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data[key]


class FakeClient:
    def __init__(self, storage, reference_fails=False):
        self.storage = storage
        self.reference_fails = reference_fails
        self.payloads = []

    def health(self, spec):
        return {"status": "ok", "backend": spec.backend}

    def execute(self, spec, payload):
        self.payloads.append(payload)
        name = payload["executor_id"]
        if name == "reference" and self.reference_fails:
            return {"status": "error", "backend": spec.backend, "error": "reference failed"}
        output = {
            "reference": torch.tensor([2.0]),
            "correct_target": torch.tensor([2.0]),
            "incorrect_target": torch.tensor([3.0]),
        }[name]
        latency = {"reference": 2.0, "correct_target": 1.0, "incorrect_target": 4.0}[name]
        key = f"jobs/test/{payload['role']}/{name}/output.safetensors"
        self.storage.put(key, serialize_output(output))
        return {
            "status": "success",
            "backend": spec.backend,
            "role": payload["role"],
            "executor_id": name,
            "output_key": key,
            "latency_ms": latency,
            "timing": {"p50_ms": latency},
            "device": {"device": "cpu"},
        }


class DatasetRunTests(unittest.TestCase):
    def _config(self, root: Path) -> Path:
        for filename in ("reference.py", "correct.py", "incorrect.py"):
            (root / filename).write_text("def add(x): return x\n", encoding="utf-8")
        config = {
            "reference": {
                "backend": "cuda",
                "service": "http://reference.test:9100",
                "solution": "reference.py",
            },
            "targets": {
                "correct_target": {
                    "backend": "accelerator-a",
                    "service": "http://target-a.test:9100",
                    "solution": "correct.py",
                },
                "incorrect_target": {
                    "backend": "accelerator-b",
                    "service": "http://target-b.test:9100",
                    "solution": "incorrect.py",
                },
            },
            "storage": {
                "type": "ks3",
                "endpoint": "ks3.example.test",
                "bucket": "test",
            },
        }
        path = root / "run.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def test_runtime_reference_controls_correctness_and_speedup(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self._config(Path(temp))
            storage = MemoryStorage()
            client = FakeClient(storage)
            with patch("vcd.dataset.make_storage", return_value=storage), patch(
                "vcd.dataset.AgentClient", return_value=client
            ):
                rows = run_dataset(str(config), "demo/add", cases=[0], op="add")

        row = rows[0]
        self.assertEqual(row["reference"]["backend"], "cuda")
        self.assertEqual(row["reference"]["latency_ms"], 2.0)
        results = {result["target"]: result for result in row["results"]}
        self.assertTrue(results["correct_target"]["passed"])
        self.assertEqual(results["correct_target"]["speedup_vs_reference"], 2.0)
        self.assertFalse(results["incorrect_target"]["passed"])
        self.assertEqual(results["incorrect_target"]["speedup_vs_reference"], 0.5)
        roles = {payload["executor_id"]: payload["role"] for payload in client.payloads}
        self.assertEqual(roles["reference"], "reference")
        self.assertEqual(roles["correct_target"], "target")

    def test_reference_failure_fails_all_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self._config(Path(temp))
            storage = MemoryStorage()
            client = FakeClient(storage, reference_fails=True)
            with patch("vcd.dataset.make_storage", return_value=storage), patch(
                "vcd.dataset.AgentClient", return_value=client
            ):
                row = run_dataset(str(config), "demo/add", cases=[0], op="add")[0]

        self.assertEqual(row["reference"]["status"], "error")
        self.assertTrue(all(not result["passed"] for result in row["results"]))
        self.assertTrue(
            all(result["speedup_vs_reference"] is None for result in row["results"])
        )
        self.assertTrue(
            all("reference execution failed" in result["error"] for result in row["results"])
        )

    def test_reference_and_solutions_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "run.json"
            path.write_text(
                json.dumps(
                    {
                        "targets": {
                            "target": {
                                "service": "http://target.test:9100",
                                "solution": "target.py",
                            }
                        },
                        "storage": {"type": "ks3"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                DatasetConfig.load(path)

    def test_local_storage_is_supported_for_dataset_development(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = self._config(root)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["storage"] = {"type": "local", "root": "artifacts"}
            path.write_text(json.dumps(raw), encoding="utf-8")

            config = DatasetConfig.load(path)

            self.assertEqual(config.storage["type"], "local")
            self.assertEqual(config.storage["root"], "artifacts")

    def test_unknown_dataset_storage_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = self._config(root)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["storage"] = {"type": "unknown"}
            path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "local or ks3"):
                DatasetConfig.load(path)


if __name__ == "__main__":
    unittest.main()
