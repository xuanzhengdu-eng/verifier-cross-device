import json
import os
import tempfile
import unittest
from pathlib import Path

from vcd.config import AgentSpec, RunConfig, load_run_config
from vcd.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_rejects_credentials_in_service_url(self):
        with self.assertRaises(ConfigError):
            AgentSpec.from_dict(
                {"backend": "bad", "service": "http://user:password@example.test"},
                "service",
            )

    def test_resolves_solution_and_token_from_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "solution.py").write_text("def add(x): return x\n", encoding="utf-8")
            config = {
                "problem_key": "add",
                "reference": {"backend": "ref", "service": "http://127.0.0.1:1"},
                "targets": {
                    "target": {
                        "service": "http://127.0.0.1:2",
                        "solution": "solution.py",
                        "token_env": "VCD_TEST_TOKEN",
                    }
                },
                "storage": {"type": "local", "root": "artifacts"},
            }
            path = root / "run.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            old = os.environ.get("VCD_TEST_TOKEN")
            os.environ["VCD_TEST_TOKEN"] = "test-token"
            try:
                loaded = load_run_config(path)
                self.assertEqual(loaded.targets["target"].token(), "test-token")
                self.assertEqual(loaded.solution_path("target"), root / "solution.py")
            finally:
                if old is None:
                    os.environ.pop("VCD_TEST_TOKEN", None)
                else:
                    os.environ["VCD_TEST_TOKEN"] = old

    def test_resolves_reference_solution_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "reference.py").write_text(
                "def add(x): return x\n", encoding="utf-8"
            )
            config = RunConfig.from_dict(
                {
                    "reference": {
                        "backend": "cpu",
                        "service": "http://127.0.0.1:1",
                        "solution": "reference.py",
                    },
                    "targets": {
                        "target": {
                            "service": "http://127.0.0.1:2",
                        }
                    },
                    "storage": {"type": "local", "root": "artifacts"},
                },
                root,
            )

            self.assertEqual(config.solution_path("reference"), root / "reference.py")

    def test_legacy_agent_key_remains_compatible(self):
        spec = AgentSpec.from_dict(
            {"backend": "cpu", "agent": "http://127.0.0.1:9100"}, "target"
        )
        self.assertEqual(spec.url, "http://127.0.0.1:9100")


if __name__ == "__main__":
    unittest.main()
