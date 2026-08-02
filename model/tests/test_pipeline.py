from __future__ import annotations

import io
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from heatshield_pipeline import (  # noqa: E402
    CURRENT_FEATURES,
    DataCapError,
    build_supervised,
    nws_apparent_temperature_f,
    parse_scaled_measurement,
    parse_wind_speed,
    relative_humidity_pct,
    stream_response_to_file,
)


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, declared_length: int | None = None):
        super().__init__(payload)
        self.headers = {}
        if declared_length is not None:
            self.headers["Content-Length"] = str(declared_length)


class ParsingTests(unittest.TestCase):
    def test_scaled_measurement_quality_and_sentinel(self) -> None:
        self.assertAlmostEqual(parse_scaled_measurement("+0294,1"), 29.4)
        self.assertAlmostEqual(parse_scaled_measurement("-0050,5"), -5.0)
        self.assertTrue(math.isnan(parse_scaled_measurement("+9999,9")))
        self.assertTrue(math.isnan(parse_scaled_measurement("+0294,3")))
        self.assertTrue(math.isnan(parse_scaled_measurement("bad")))

    def test_wind_speed_quality_and_sentinel(self) -> None:
        self.assertAlmostEqual(parse_wind_speed("300,1,N,0067,1"), 6.7)
        self.assertTrue(math.isnan(parse_wind_speed("999,9,C,9999,9")))
        self.assertTrue(math.isnan(parse_wind_speed("300,1,N,0067,7")))

    def test_magnus_relative_humidity(self) -> None:
        value = relative_humidity_pct([30.0], [20.0])[0]
        self.assertGreater(value, 54.0)
        self.assertLess(value, 56.0)
        supersaturated = relative_humidity_pct([20.0], [25.0])[0]
        self.assertEqual(supersaturated, 100.0)

    def test_nws_heat_index_and_low_temperature_domain(self) -> None:
        hot = nws_apparent_temperature_f([90.0], [70.0])[0]
        self.assertGreater(hot, 105.0)
        self.assertLess(hot, 107.0)
        cool = nws_apparent_temperature_f([75.0], [80.0])[0]
        self.assertEqual(cool, 75.0)


class ProvenanceTests(unittest.TestCase):
    def test_declared_response_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "response.csv"
            response = FakeResponse(b"abc", declared_length=101)
            with self.assertRaises(DataCapError):
                stream_response_to_file(response, destination, max_bytes=100)

    def test_streamed_response_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "response.csv"
            response = FakeResponse(b"x" * 101)
            with self.assertRaises(DataCapError):
                stream_response_to_file(response, destination, max_bytes=100)


class FeatureTests(unittest.TestCase):
    def test_next_day_target_is_strictly_forward(self) -> None:
        dates = pd.date_range("2023-07-01", periods=10, freq="D")
        data: dict[str, object] = {
            "station": ["72530094846"] * len(dates),
            "local_date": dates,
        }
        for index, feature in enumerate(CURRENT_FEATURES):
            data[feature] = np.arange(len(dates), dtype=float) + index
        data["apparent_max_f"] = np.arange(80.0, 90.0)
        daily = pd.DataFrame(data)
        supervised, features = build_supervised(daily)

        self.assertEqual(len(supervised), 9)
        first = supervised.iloc[0]
        self.assertEqual(
            first["target_date"], first["local_date"] + pd.Timedelta(days=1)
        )
        self.assertEqual(first["target_max_apparent_f"], 81.0)
        self.assertEqual(first["apparent_max_f"], 80.0)
        self.assertNotIn("target_max_apparent_f", features)
        self.assertNotIn("target_exceed_95f", features)


if __name__ == "__main__":
    unittest.main()
