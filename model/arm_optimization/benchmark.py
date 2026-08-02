from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from runtime import (
    OnnxRuntime,
    SklearnRuntime,
    is_native_arm64,
    output_digest,
    sha256_file,
    system_metadata,
)


THREAD_ENVIRONMENT_KEYS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
FEATURE_NAME_WARNING = (
    "X does not have valid feature names, but SimpleImputer was fitted with "
    "feature names"
)


def thread_environment() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in THREAD_ENVIRONMENT_KEYS}


def require_controlled_thread_environment(threads: int) -> None:
    expected = str(threads)
    actual = thread_environment()
    mismatches = {name: value for name, value in actual.items() if value != expected}
    if mismatches:
        raise RuntimeError(
            "A controlled benchmark requires every numerical thread environment "
            f"variable to equal {expected}: {mismatches}"
        )


def maximum_rss_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def benchmark(
    engine_name: str,
    model_path: Path,
    export_directory: Path,
    output_path: Path,
    batch_sizes: list[int],
    warmup: int,
    iterations: int,
    threads: int,
    require_native_arm: bool,
    require_controlled_threads: bool,
) -> dict[str, Any]:
    if warmup < 1 or iterations < 1 or threads < 1:
        raise ValueError("warmup, iterations, and threads must all be positive")
    if not batch_sizes or len(set(batch_sizes)) != len(batch_sizes):
        raise ValueError("batch sizes must be non-empty and unique")
    if require_controlled_threads:
        require_controlled_thread_environment(threads)
    system = system_metadata()
    if require_native_arm and not is_native_arm64(system["architecture"]):
        raise RuntimeError(
            "Native Arm64 evidence was required, but platform.machine() returned "
            f"{system['architecture']!r}"
        )
    fixture_path = export_directory / "benchmark-inputs.npz"
    with np.load(fixture_path) as fixture:
        features = np.asarray(fixture["features"], dtype=np.float32)
    started = time.perf_counter()
    if engine_name == "baseline":
        engine = SklearnRuntime(model_path)
        artifact_bytes = model_path.stat().st_size
    elif engine_name == "candidate":
        engine = OnnxRuntime(export_directory, threads=threads)
        metadata = json.loads(
            (export_directory / "metadata.json").read_text(encoding="utf-8")
        )
        artifact_bytes = sum(
            int(details["bytes"]) for details in metadata["models"].values()
        ) + (export_directory / "metadata.json").stat().st_size
    else:
        raise ValueError(f"Unknown engine: {engine_name}")
    load_seconds = time.perf_counter() - started
    results: dict[str, Any] = {}
    digest = None
    # The persisted imputers remember pandas column names, while the benchmark
    # deliberately feeds the same contiguous ndarray to both runtimes. Suppress
    # only that diagnostic so stderr I/O is not counted as baseline inference.
    # This does not alter input values, predictions, parity, or tolerances.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=FEATURE_NAME_WARNING)
        for batch_size in batch_sizes:
            if batch_size <= 0 or batch_size > len(features):
                raise ValueError(
                    f"Batch size {batch_size} is outside fixture size {len(features)}"
                )
            batch = np.ascontiguousarray(features[:batch_size])
            for _ in range(warmup):
                digest = output_digest(engine.predict(batch))
            durations: list[float] = []
            for _ in range(iterations):
                start = time.perf_counter_ns()
                outputs = engine.predict(batch)
                durations.append((time.perf_counter_ns() - start) / 1_000_000_000)
                digest = output_digest(outputs)
            median = statistics.median(durations)
            p95 = percentile(durations, 0.95)
            results[str(batch_size)] = {
                "batch_size": batch_size,
                "iterations": iterations,
                "latency_seconds": {
                    "min": min(durations),
                    "median": median,
                    "p95": p95,
                    "max": max(durations),
                },
                "throughput_rows_per_second": {
                    "at_median_latency": batch_size / median,
                    "at_p95_latency": batch_size / p95,
                },
            }
    gc.collect()
    report = {
        "schema_version": 1,
        "engine": engine_name,
        "threads": threads,
        "thread_environment": thread_environment(),
        "controlled_thread_environment": require_controlled_threads,
        "warmup_iterations": warmup,
        "measured_iterations": iterations,
        "fixture_sha256": sha256_file(fixture_path),
        "fixture_rows": int(features.shape[0]),
        "fixture_columns": int(features.shape[1]),
        "scope": "Synthetic branch-coverage inference benchmark; not accuracy evidence",
        "warning_policy": (
            "Suppress only sklearn's feature-name diagnostic while scoring identical "
            "ndarray inputs; predictions and parity checks remain unchanged"
        ),
        "artifact_bytes": artifact_bytes,
        "load_seconds": load_seconds,
        "maximum_rss_bytes": maximum_rss_bytes(),
        "last_output_sha256": digest,
        "native_arm64": is_native_arm64(system["architecture"]),
        "system": system,
        "batches": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("baseline", "candidate"), required=True)
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-sizes", default="1,32,256,1024")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--require-native-arm", action="store_true")
    parser.add_argument("--require-controlled-threads", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    benchmark(
        arguments.engine,
        arguments.model,
        arguments.export_directory,
        arguments.output,
        batch_sizes=[int(value) for value in arguments.batch_sizes.split(",")],
        warmup=arguments.warmup,
        iterations=arguments.iterations,
        threads=arguments.threads,
        require_native_arm=arguments.require_native_arm,
        require_controlled_threads=arguments.require_controlled_threads,
    )
