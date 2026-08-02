from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))

from compare_benchmarks import compare  # noqa: E402


class ComparisonEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = {
            "architecture": "aarch64",
            "github_actions": True,
            "github_repository": "nexicturbo/heatshield-ai",
            "github_run_id": "123",
            "github_run_url": (
                "https://github.com/nexicturbo/heatshield-ai/actions/runs/123"
            ),
            "github_sha": "a" * 40,
            "github_workflow": "Native Arm64 inference benchmark",
            "runner_arch": "ARM64",
            "runner_os": "Linux",
        }
        self.thread_environment = {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
        }
        common = {
            "fixture_sha256": "f" * 64,
            "system": self.system,
            "native_arm64": True,
            "threads": 1,
            "thread_environment": self.thread_environment,
            "controlled_thread_environment": True,
            "warmup_iterations": 10,
            "measured_iterations": 100,
            "artifact_bytes": 100,
            "maximum_rss_bytes": 1_000,
        }
        self.baseline = {
            **common,
            "engine": "baseline",
            "batches": {
                "256": {
                    "latency_seconds": {"median": 0.0125, "p95": 0.0140}
                }
            },
        }
        self.candidate = {
            **common,
            "engine": "candidate",
            "artifact_bytes": 80,
            "maximum_rss_bytes": 900,
            "batches": {
                "256": {
                    "latency_seconds": {"median": 0.0100, "p95": 0.0110}
                }
            },
        }
        self.parity = {
            "fixture_sha256": "f" * 64,
            "system": self.system,
            "passed": True,
            "comparisons": {
                key: {
                    "atol": tolerance,
                    "max_absolute_error": tolerance / 10,
                    "mean_absolute_error": tolerance / 100,
                    "mismatched_rows": 0,
                    "passed": True,
                }
                for key, tolerance in {
                    "point_f": 1e-3,
                    "q10_f": 1e-3,
                    "q50_f": 1e-3,
                    "q90_f": 1e-3,
                    "exceed_95_probability": 2e-5,
                }.items()
            }
            | {
                "exceed_95": {"mismatched_rows": 0, "passed": True},
            },
        }

    def run_compare(self) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "baseline": root / "baseline.json",
                "candidate": root / "candidate.json",
                "parity": root / "parity.json",
                "output": root / "comparison.json",
            }
            for name in ("baseline", "candidate", "parity"):
                paths[name].write_text(
                    json.dumps(getattr(self, name)), encoding="utf-8"
                )
            return compare(
                paths["baseline"],
                paths["candidate"],
                paths["parity"],
                paths["output"],
                primary_batch=256,
                minimum_speedup=1.20,
                require_native_arm=True,
            )

    def test_allows_claim_only_when_native_parity_and_speed_pass(self) -> None:
        result = self.run_compare()
        self.assertTrue(result["official_github_evidence"])
        self.assertTrue(result["performance_claim_allowed"])
        self.assertAlmostEqual(
            result["batches"]["256"]["median_latency_speedup"], 1.25
        )
        self.assertEqual(result["parity_comparisons"], self.parity["comparisons"])

    def test_below_threshold_does_not_allow_claim(self) -> None:
        self.candidate["batches"]["256"]["latency_seconds"]["median"] = 0.011
        result = self.run_compare()
        self.assertFalse(result["primary_speedup_passed"])
        self.assertFalse(result["performance_claim_allowed"])

    def test_local_native_arm_run_cannot_allow_performance_claim(self) -> None:
        self.system.update(
            {
                "github_actions": False,
                "github_repository": None,
                "github_run_id": None,
                "github_run_url": None,
                "github_sha": None,
                "github_workflow": None,
                "runner_arch": None,
                "runner_os": None,
            }
        )
        result = self.run_compare()
        self.assertTrue(result["native_arm_evidence"])
        self.assertTrue(result["primary_speedup_passed"])
        self.assertFalse(result["official_github_evidence"])
        self.assertFalse(result["performance_claim_allowed"])

    def test_mismatched_github_run_url_cannot_allow_claim(self) -> None:
        self.system["github_run_url"] = (
            "https://github.com/nexicturbo/heatshield-ai/actions/runs/456"
        )
        result = self.run_compare()
        self.assertFalse(result["official_github_evidence"])
        self.assertFalse(result["performance_claim_allowed"])

    def test_rejects_parity_from_another_fixture(self) -> None:
        self.parity["fixture_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "different fixtures"):
            self.run_compare()

    def test_rejects_unequal_thread_policy(self) -> None:
        self.candidate = copy.deepcopy(self.candidate)
        self.candidate["thread_environment"]["OMP_NUM_THREADS"] = "2"
        with self.assertRaisesRegex(RuntimeError, "configuration differs"):
            self.run_compare()

    def test_rejects_weakened_parity_tolerance(self) -> None:
        self.parity["comparisons"]["point_f"]["atol"] = 1e-2
        with self.assertRaisesRegex(RuntimeError, "tolerance changed"):
            self.run_compare()


if __name__ == "__main__":
    unittest.main()
