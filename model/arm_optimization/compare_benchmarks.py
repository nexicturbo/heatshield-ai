from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EXPECTED_PARITY_TOLERANCES = {
    "point_f": 1e-3,
    "q10_f": 1e-3,
    "q50_f": 1e-3,
    "q90_f": 1e-3,
    "exceed_95_probability": 2e-5,
}


def official_github_native_arm_provenance(system: dict[str, Any]) -> bool:
    """Return whether metadata identifies an official GitHub Arm64 Actions run."""
    repository = system.get("github_repository")
    run_id = system.get("github_run_id")
    run_url = system.get("github_run_url")
    sha = system.get("github_sha")
    workflow = system.get("github_workflow")
    runner_arch = system.get("runner_arch")
    runner_os = system.get("runner_os")
    architecture = system.get("architecture")

    if system.get("github_actions") is not True:
        return False
    if not isinstance(repository, str) or repository.strip() != repository:
        return False
    repository_parts = repository.split("/")
    if len(repository_parts) != 2 or not all(repository_parts):
        return False
    if not isinstance(run_id, str) or not run_id.isdecimal() or int(run_id) < 1:
        return False
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-fA-F]{40}", sha) is None:
        return False
    if not isinstance(workflow, str) or not workflow.strip():
        return False
    expected_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    if run_url != expected_url:
        return False
    normalized_architecture = str(architecture or "").lower().replace("_", "")
    normalized_runner_arch = str(runner_arch or "").lower().replace("_", "")
    return bool(
        normalized_architecture in {"aarch64", "arm64"}
        and normalized_runner_arch in {"aarch64", "arm64"}
        and runner_os == "Linux"
    )


def parity_details_passed(parity: dict[str, Any]) -> bool:
    comparisons = parity["comparisons"]
    if set(EXPECTED_PARITY_TOLERANCES) - set(comparisons):
        raise RuntimeError("Parity report is missing required numeric outputs")
    passed = bool(parity["passed"])
    for key, expected_tolerance in EXPECTED_PARITY_TOLERANCES.items():
        details = comparisons[key]
        if float(details["atol"]) != expected_tolerance:
            raise RuntimeError(
                f"Parity tolerance changed for {key}: {details['atol']} != "
                f"{expected_tolerance}"
            )
        within = bool(
            details["passed"]
            and int(details["mismatched_rows"]) == 0
            and float(details["max_absolute_error"]) <= expected_tolerance
        )
        passed = passed and within
    classification = comparisons["exceed_95"]
    passed = passed and bool(
        classification["passed"]
        and int(classification["mismatched_rows"]) == 0
    )
    return passed


def compare(
    baseline_path: Path,
    candidate_path: Path,
    parity_path: Path,
    output_path: Path,
    primary_batch: int,
    minimum_speedup: float,
    require_native_arm: bool,
) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    if (
        baseline.get("engine") != "baseline"
        or candidate.get("engine") != "candidate"
    ):
        raise RuntimeError("Expected baseline and candidate engine reports")
    if baseline["fixture_sha256"] != candidate["fixture_sha256"]:
        raise RuntimeError("Before/after runs used different benchmark fixtures")
    if parity["fixture_sha256"] != baseline["fixture_sha256"]:
        raise RuntimeError("Parity and performance runs used different fixtures")
    if baseline["system"] != candidate["system"]:
        raise RuntimeError("Before/after runs did not execute in the same environment")
    if parity["system"] != baseline["system"]:
        raise RuntimeError("Parity and performance runs did not share one environment")
    configuration_keys = (
        "threads",
        "thread_environment",
        "controlled_thread_environment",
        "warmup_iterations",
        "measured_iterations",
    )
    unequal_configuration = {
        key: (baseline.get(key), candidate.get(key))
        for key in configuration_keys
        if baseline.get(key) != candidate.get(key)
    }
    if unequal_configuration:
        raise RuntimeError(
            "Before/after execution configuration differs: "
            f"{unequal_configuration}"
        )
    controlled_threads = bool(baseline.get("controlled_thread_environment"))
    expected_thread_value = str(baseline["threads"])
    recorded_thread_environment = baseline.get("thread_environment", {})
    if controlled_threads and any(
        value != expected_thread_value
        for value in recorded_thread_environment.values()
    ):
        raise RuntimeError("Recorded thread environment does not match thread count")
    if require_native_arm and not controlled_threads:
        raise RuntimeError("Native Arm evidence requires a controlled thread policy")
    if set(baseline["batches"]) != set(candidate["batches"]):
        raise RuntimeError("Before/after runs measured different batch sizes")
    if str(primary_batch) not in baseline["batches"]:
        raise RuntimeError(f"Primary batch {primary_batch} was not measured")
    if require_native_arm and not (
        baseline["native_arm64"] and candidate["native_arm64"]
    ):
        raise RuntimeError("Comparison requires two native Arm64 benchmark runs")
    comparisons: dict[str, Any] = {}
    for batch_size in baseline["batches"]:
        before = baseline["batches"][batch_size]
        after = candidate["batches"][batch_size]
        before_median = before["latency_seconds"]["median"]
        after_median = after["latency_seconds"]["median"]
        before_p95 = before["latency_seconds"]["p95"]
        after_p95 = after["latency_seconds"]["p95"]
        if min(before_median, after_median, before_p95, after_p95) <= 0:
            raise RuntimeError("Benchmark latencies must all be positive")
        comparisons[batch_size] = {
            "median_latency_speedup": before_median / after_median,
            "p95_latency_speedup": before_p95 / after_p95,
            "baseline_median_seconds": before_median,
            "candidate_median_seconds": after_median,
            "baseline_p95_seconds": before_p95,
            "candidate_p95_seconds": after_p95,
        }
    primary = comparisons[str(primary_batch)]
    native_arm_evidence = bool(
        baseline["native_arm64"] and candidate["native_arm64"]
    )
    official_github_evidence = official_github_native_arm_provenance(
        baseline["system"]
    )
    parity_passed = parity_details_passed(parity)
    speedup_passed = primary["median_latency_speedup"] >= minimum_speedup
    performance_claim_allowed = bool(
        native_arm_evidence
        and official_github_evidence
        and controlled_threads
        and parity_passed
        and speedup_passed
    )
    report = {
        "schema_version": 1,
        "native_arm_evidence": native_arm_evidence,
        "official_github_evidence": official_github_evidence,
        "parity_passed": parity_passed,
        "parity_tolerances_locked": True,
        "controlled_thread_environment": controlled_threads,
        "primary_batch_size": primary_batch,
        "minimum_median_latency_speedup": minimum_speedup,
        "primary_speedup_passed": speedup_passed,
        "performance_claim_allowed": performance_claim_allowed,
        "claim_policy": (
            "A performance claim requires runtime parity, two same-environment native "
            "Arm64 runs from an identified official GitHub Actions job, and the "
            "configured primary-batch median-latency speedup."
        ),
        "fixture_sha256": baseline["fixture_sha256"],
        "system": baseline["system"],
        "benchmark_configuration": {
            key: baseline.get(key) for key in configuration_keys
        },
        "parity_comparisons": parity["comparisons"],
        "artifact_bytes": {
            "baseline": baseline["artifact_bytes"],
            "candidate": candidate["artifact_bytes"],
        },
        "maximum_rss_bytes": {
            "baseline": baseline["maximum_rss_bytes"],
            "candidate": candidate["maximum_rss_bytes"],
        },
        "batches": comparisons,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--parity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--primary-batch", type=int, default=256)
    parser.add_argument("--minimum-speedup", type=float, default=1.20)
    parser.add_argument("--require-native-arm", action="store_true")
    parser.add_argument(
        "--enforce-gate",
        action="store_true",
        help="Exit nonzero unless native evidence, parity, and speedup all pass",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    result = compare(
        arguments.baseline,
        arguments.candidate,
        arguments.parity,
        arguments.output,
        arguments.primary_batch,
        arguments.minimum_speedup,
        arguments.require_native_arm,
    )
    if arguments.enforce_gate and not result["performance_claim_allowed"]:
        raise SystemExit("Native Arm performance evidence gate failed")
