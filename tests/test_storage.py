import tempfile
import unittest

import torch

from storage import (
    LocalStorage,
    deserialize_bundle,
    deserialize_output,
    serialize_bundle,
    serialize_output,
)


class StorageTests(unittest.TestCase):
    def test_bundle_round_trip_preserves_metadata_shapes(self):
        source = {
            "x": torch.arange(4),
            "shape": (2, 2),
            "options": {"enabled": True, "dims": [1, 2]},
            "dtype": torch.float16,
        }
        restored = deserialize_bundle(serialize_bundle(source))
        torch.testing.assert_close(restored.pop("x"), source["x"])
        self.assertEqual(restored, {k: v for k, v in source.items() if k != "x"})

    def test_output_round_trip_preserves_tuple_and_none(self):
        source = (torch.tensor([1.0]), None, torch.tensor([2.0]))
        restored = deserialize_output(serialize_output(source))
        self.assertIsInstance(restored, tuple)
        self.assertIsNone(restored[1])
        torch.testing.assert_close(restored[0], source[0])
        torch.testing.assert_close(restored[2], source[2])

    def test_local_storage_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            storage = LocalStorage(temp)
            with self.assertRaises(ValueError):
                storage.put("../outside", b"bad")


if __name__ == "__main__":
    unittest.main()

