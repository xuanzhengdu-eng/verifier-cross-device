import hashlib
import sys
import tempfile
import types
import unittest

import torch
from fastapi.testclient import TestClient

import vcd
from agent.server import build_app
from storage import LocalStorage, deserialize_output, serialize_bundle
from vcd.dataset_format import pack_inputs


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(self.temp.name)
        self.storage.put("inputs.safetensors", serialize_bundle({"x": torch.tensor([2.0])}))

        self.fake_kgb = types.ModuleType("kernelgenbench")
        self.fake_kgb.solution = types.SimpleNamespace()
        self.previous_kgb = sys.modules.get("kernelgenbench")
        sys.modules["kernelgenbench"] = self.fake_kgb

        vcd.REGISTRY["add_one"] = {
            "ref_compute": lambda x: x + 1,
            "res_compute": lambda x: self.fake_kgb.solution.add_one(x),
        }
        app = build_app(
            "cpu-test",
            "cpu",
            self.storage,
            auth_token="secret",
            allow_solution_code=True,
            warmup=0,
            iterations=1,
        )
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer secret"}

    def tearDown(self):
        vcd.REGISTRY.pop("add_one", None)
        if self.previous_kgb is None:
            sys.modules.pop("kernelgenbench", None)
        else:
            sys.modules["kernelgenbench"] = self.previous_kgb
        self.temp.cleanup()

    def _payload(self, role):
        return {
            "job_id": "job1",
            "problem_key": "add_one",
            "op": "add_one",
            "role": role,
            "input_key": "inputs.safetensors",
        }

    def test_authentication_and_reference_execution(self):
        self.assertEqual(self.client.get("/health").status_code, 401)
        self.assertEqual(self.client.get("/health", headers=self.headers).status_code, 200)
        response = self.client.post(
            "/execute", json=self._payload("ref"), headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        torch.testing.assert_close(
            deserialize_output(self.storage.get(body["output_key"])), torch.tensor([3.0])
        )

    def test_solution_hash_is_checked(self):
        code = "def add_one(x):\n    return x + 1\n"
        payload = self._payload("res")
        payload.update(
            {
                "solution_code": code,
                "solution_sha256": hashlib.sha256(code.encode()).hexdigest(),
            }
        )
        good = self.client.post("/execute", json=payload, headers=self.headers).json()
        self.assertEqual(good["status"], "success")

        payload["solution_sha256"] = "0" * 64
        bad = self.client.post("/execute", json=payload, headers=self.headers).json()
        self.assertEqual(bad["status"], "error")
        self.assertIn("does not match", bad["error"])

    def test_dataset_execution_uses_in_tree_format(self):
        self.storage.put("dataset-input.safetensors", pack_inputs({"x": torch.tensor([4.0])}))
        code = "def add_one(x):\n    return x + 1\n"
        payload = self._payload("res")
        payload.update(
            {
                "input_format": "dataset",
                "input_key": "dataset-input.safetensors",
                "solution_code": code,
                "solution_sha256": hashlib.sha256(code.encode()).hexdigest(),
            }
        )
        response = self.client.post(
            "/execute", json=payload, headers=self.headers
        ).json()
        self.assertEqual(response["status"], "success")
        torch.testing.assert_close(
            deserialize_output(self.storage.get(response["output_key"])),
            torch.tensor([5.0]),
        )

    def test_dataset_reference_executes_submitted_reference_code(self):
        self.storage.put("dataset-input.safetensors", pack_inputs({"x": torch.tensor([4.0])}))
        code = "def add_one(x):\n    return x + 1\n"
        payload = self._payload("reference")
        payload.update(
            {
                "executor_id": "nvidia-reference",
                "input_format": "dataset",
                "input_key": "dataset-input.safetensors",
                "solution_code": code,
                "solution_sha256": hashlib.sha256(code.encode()).hexdigest(),
            }
        )
        response = self.client.post(
            "/execute", json=payload, headers=self.headers
        ).json()
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["role"], "reference")
        self.assertIn("/reference/nvidia-reference/", response["output_key"])
        torch.testing.assert_close(
            deserialize_output(self.storage.get(response["output_key"])),
            torch.tensor([5.0]),
        )

    def test_four_role_reference_can_execute_submitted_source(self):
        code = "def add_one(x):\n    return x + 10\n"
        payload = self._payload("ref")
        payload.update(
            {
                "solution_code": code,
                "solution_sha256": hashlib.sha256(code.encode()).hexdigest(),
            }
        )

        response = self.client.post(
            "/execute", json=payload, headers=self.headers
        ).json()

        self.assertEqual(response["status"], "success")
        torch.testing.assert_close(
            deserialize_output(self.storage.get(response["output_key"])),
            torch.tensor([12.0]),
        )


if __name__ == "__main__":
    unittest.main()
