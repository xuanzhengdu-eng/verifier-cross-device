import unittest

from vcd.runtime import benchmark, detect_device


class RuntimeTests(unittest.TestCase):
    def test_cpu_benchmark_returns_ordered_quantiles(self):
        result = benchmark(lambda: sum(range(100)), "cpu", warmup=0, iterations=5)
        self.assertEqual(result.iterations, 5)
        self.assertLessEqual(result.p20_ms, result.p50_ms)
        self.assertLessEqual(result.p50_ms, result.p80_ms)

    def test_explicit_cpu_detection(self):
        self.assertEqual(detect_device("cpu"), "cpu")


if __name__ == "__main__":
    unittest.main()

