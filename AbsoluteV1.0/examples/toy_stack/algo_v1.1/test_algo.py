import unittest

import algo


class AlgorithmContract(unittest.TestCase):
    def test_public_outputs_remain_nonnegative_numbers(self):
        self.assertIsInstance(algo.VALUE, (int, float))
        self.assertIsInstance(algo.LATENCY_MS, (int, float))
        self.assertGreaterEqual(algo.VALUE, 0)
        self.assertGreaterEqual(algo.LATENCY_MS, 0)