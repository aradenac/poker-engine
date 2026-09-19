#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest

from tools.simulation.benchmark_paired_preflop_validation import run_validation


class PairedPreflopValidationTests(unittest.TestCase):
    def test_frozen_validation_benchmark(self):
        result = run_validation()
        print("ISSUE338_VALIDATION_RESULT_BEGIN")
        print(json.dumps(result, indent=2, sort_keys=True))
        print("ISSUE338_VALIDATION_RESULT_END")
        self.assertEqual(result["phase"], "VALIDATION")
        self.assertFalse(result["scientific_boundaries"]["test_consumed"])
        self.assertFalse(result["scientific_boundaries"]["test_authorized"])
        self.assertTrue(result["metrics"]["deterministic_fixed"])
        self.assertTrue(result["metrics"]["deterministic_paired"])
        self.assertTrue(result["metrics"]["materialized_common_worlds"])
        self.assertTrue(result["acceptance"]["pass"])


if __name__ == "__main__":
    unittest.main()
