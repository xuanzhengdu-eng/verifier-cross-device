import unittest

from deploy.agent_daemon import _normalize_secrets


class DaemonSecretTests(unittest.TestCase):
    def test_current_secret_names_are_preserved(self):
        source = {
            "VCD_KS3_AK": "ak",
            "VCD_KS3_SK": "sk",
            "VCD_SERVICE_TOKEN": "token",
        }
        self.assertEqual(_normalize_secrets(source), source)

    def test_legacy_secret_names_are_normalized(self):
        self.assertEqual(
            _normalize_secrets(
                {
                    "OP_VERIFY_KS3_AK": "ak",
                    "OP_VERIFY_KS3_SK": "sk",
                    "VCD_AGENT_TOKEN": "token",
                }
            ),
            {
                "VCD_KS3_AK": "ak",
                "VCD_KS3_SK": "sk",
                "VCD_SERVICE_TOKEN": "token",
            },
        )

    def test_unknown_or_empty_secrets_are_rejected(self):
        with self.assertRaises(ValueError):
            _normalize_secrets({"unexpected": "value"})
        with self.assertRaises(ValueError):
            _normalize_secrets(
                {"VCD_KS3_AK": "", "VCD_KS3_SK": "sk", "VCD_SERVICE_TOKEN": "token"}
            )


if __name__ == "__main__":
    unittest.main()
