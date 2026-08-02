from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))

from runtime import (  # noqa: E402
    MedianIndicatorPreprocessor,
    _calibrate_probability,
    is_native_arm64,
)
from export_models import float32_branch_boundary  # noqa: E402


class PreprocessorTests(unittest.TestCase):
    def test_median_imputation_and_indicator_order(self) -> None:
        preprocessor = MedianIndicatorPreprocessor(
            {
                "statistics": [10.0, 20.0, 30.0],
                "indicator_features": [2, 0],
                "output_feature_count": 5,
            }
        )
        actual = preprocessor.transform(
            np.asarray([[np.nan, 2.0, np.nan], [1.0, np.nan, 3.0]], dtype=np.float32)
        )
        expected = np.asarray(
            [[10.0, 2.0, 30.0, 1.0, 1.0], [1.0, 20.0, 3.0, 0.0, 0.0]],
            dtype=np.float32,
        )
        np.testing.assert_array_equal(actual, expected)

    def test_rejects_wrong_shape(self) -> None:
        preprocessor = MedianIndicatorPreprocessor(
            {
                "statistics": [1.0, 2.0],
                "indicator_features": [],
                "output_feature_count": 2,
            }
        )
        with self.assertRaises(ValueError):
            preprocessor.transform(np.ones((3, 1), dtype=np.float32))


class CalibrationTests(unittest.TestCase):
    def test_identity_calibration_clips_to_probability_domain(self) -> None:
        actual = _calibrate_probability(
            np.asarray([-1.0, 0.25, 2.0]), {"calibration": {"kind": "identity"}}
        )
        np.testing.assert_array_equal(actual, [0.0, 0.25, 1.0])

    def test_platt_transform_is_stable_at_probability_bounds(self) -> None:
        actual = _calibrate_probability(
            np.asarray([0.0, 0.5, 1.0]),
            {
                "calibration": {
                    "kind": "platt_logit",
                    "coefficient": 1.0,
                    "intercept": 0.0,
                    "clip_epsilon": 1e-6,
                }
            },
        )
        self.assertTrue(np.isfinite(actual).all())
        self.assertAlmostEqual(actual[1], 0.5)
        self.assertLess(actual[0], actual[1])
        self.assertLess(actual[1], actual[2])


class ArchitectureTests(unittest.TestCase):
    def test_arm64_aliases(self) -> None:
        self.assertTrue(is_native_arm64("aarch64"))
        self.assertTrue(is_native_arm64("ARM64"))
        self.assertFalse(is_native_arm64("AMD64"))


class ExportCompatibilityTests(unittest.TestCase):
    def test_float32_boundary_preserves_float64_less_equal_split(self) -> None:
        threshold = 1.0 - 2.0**-25
        self.assertGreater(float(np.float32(threshold)), threshold)
        boundary = float32_branch_boundary(threshold)
        candidates = np.asarray(
            [np.nextafter(np.float32(1.0), np.float32(-np.inf)), 1.0],
            dtype=np.float32,
        )
        expected = candidates.astype(np.float64) <= threshold
        actual = candidates <= boundary
        np.testing.assert_array_equal(actual, expected)

    def test_float32_boundary_does_not_move_exact_threshold(self) -> None:
        self.assertEqual(float32_branch_boundary(1.5), np.float32(1.5))


if __name__ == "__main__":
    unittest.main()
