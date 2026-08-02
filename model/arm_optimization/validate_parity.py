from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from runtime import (
    OUTPUT_KEYS,
    OnnxRuntime,
    SklearnRuntime,
    sha256_file,
    system_metadata,
)


DEFAULT_TOLERANCES = {
    "point_f": 1e-3,
    "q10_f": 1e-3,
    "q50_f": 1e-3,
    "q90_f": 1e-3,
    "exceed_95_probability": 2e-5,
}


def validate(
    model_path: Path,
    export_directory: Path,
    output_path: Path,
    threads: int,
) -> dict[str, Any]:
    fixture_path = export_directory / "benchmark-inputs.npz"
    metadata = json.loads(
        (export_directory / "metadata.json").read_text(encoding="utf-8")
    )
    if sha256_file(fixture_path) != metadata["fixture"]["sha256"]:
        raise RuntimeError("Benchmark fixture SHA-256 does not match export metadata")
    with np.load(fixture_path) as fixture:
        features = fixture["features"]
        feature_columns = fixture["feature_columns"].tolist()
    if feature_columns != metadata["feature_columns"]:
        raise RuntimeError("Benchmark fixture columns do not match export metadata")
    baseline = SklearnRuntime(model_path)
    candidate = OnnxRuntime(export_directory, threads=threads)
    expected = baseline.predict(features)
    actual = candidate.predict(features)
    comparisons: dict[str, Any] = {}
    passed = True
    for key in DEFAULT_TOLERANCES:
        absolute = np.abs(expected[key] - actual[key])
        tolerance = DEFAULT_TOLERANCES[key]
        within = bool(np.all(absolute <= tolerance))
        passed = passed and within
        comparisons[key] = {
            "atol": tolerance,
            "max_absolute_error": float(np.max(absolute)),
            "mean_absolute_error": float(np.mean(absolute)),
            "mismatched_rows": int(np.count_nonzero(absolute > tolerance)),
            "passed": within,
        }
    classification_mismatches = int(
        np.count_nonzero(expected["exceed_95"] != actual["exceed_95"])
    )
    classification_passed = classification_mismatches == 0
    passed = passed and classification_passed
    comparisons["exceed_95"] = {
        "mismatched_rows": classification_mismatches,
        "passed": classification_passed,
    }
    report = {
        "schema_version": 1,
        "passed": passed,
        "scope": (
            "Exact-runtime parity on a synthetic branch-coverage fixture; this does "
            "not re-estimate holdout accuracy"
        ),
        "rows": int(features.shape[0]),
        "columns": int(features.shape[1]),
        "fixture_sha256": metadata["fixture"]["sha256"],
        "source_bundle_sha256": metadata["source_bundle"]["sha256"],
        "comparisons": comparisons,
        "system": system_metadata(),
        "output_keys": list(OUTPUT_KEYS),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("model/artifacts/heatshield-model.joblib"),
    )
    parser.add_argument(
        "--export-directory",
        type=Path,
        default=Path("model/artifacts/arm_onnx"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark-results/parity.json"),
    )
    parser.add_argument("--threads", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    result = validate(
        arguments.model,
        arguments.export_directory,
        arguments.output,
        arguments.threads,
    )
    raise SystemExit(0 if result["passed"] else 1)
