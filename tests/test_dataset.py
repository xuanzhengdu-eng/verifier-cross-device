import unittest

import torch

from vcd.checks import make_check_fn
from vcd.dataset_format import pack_inputs, pack_outputs, unpack_inputs, unpack_outputs


class DatasetFormatTests(unittest.TestCase):
    def test_input_round_trip(self):
        payload = pack_inputs(
            {
                "x": torch.arange(4, dtype=torch.float32),
                "axis": 1,
                "enabled": True,
                "dtype": torch.float16,
                "shape": [2, 2],
                "optional": None,
                "check": {"must_not": "be serialized"},
            }
        )
        tensors, scalars = unpack_inputs(payload)
        torch.testing.assert_close(tensors["x"], torch.arange(4, dtype=torch.float32))
        self.assertEqual(
            scalars,
            {
                "axis": 1,
                "enabled": True,
                "dtype": torch.float16,
                "shape": [2, 2],
                "optional": None,
            },
        )

    def test_golden_output_round_trip_preserves_none_and_descriptor(self):
        descriptor = {"type": "standard", "atol": 0.01, "rtol": 0.02}
        payload = pack_outputs((torch.tensor([1.0]), None), descriptor)
        outputs, restored_descriptor = unpack_outputs(payload)
        self.assertEqual(restored_descriptor, descriptor)
        self.assertEqual(len(outputs), 2)
        torch.testing.assert_close(outputs[0], torch.tensor([1.0]))
        self.assertIsNone(outputs[1])

    def test_invalid_dataset_header_is_rejected(self):
        with self.assertRaises(ValueError):
            unpack_inputs(b"short")


class CheckStrategyTests(unittest.TestCase):
    def test_standard_tolerance_passes_and_fails(self):
        check = make_check_fn({"type": "standard", "atol": 1e-3, "rtol": 0})
        self.assertEqual(
            check([torch.tensor([1.0005])], [torch.tensor([1.0])])["status"], "PASS"
        )
        self.assertEqual(
            check([torch.tensor([1.1])], [torch.tensor([1.0])])["status"], "FAIL"
        )

    def test_output_count_and_shape_mismatch_fail_cleanly(self):
        check = make_check_fn({"type": "exact"})
        self.assertEqual(check([], [torch.tensor([1])])["status"], "FAIL")
        result = check([torch.tensor([1, 2])], [torch.tensor([[1, 2]])])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["max_err"], float("inf"))

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            make_check_fn({"type": "unknown"})


if __name__ == "__main__":
    unittest.main()
