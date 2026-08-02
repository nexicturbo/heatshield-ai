# HeatShield native Arm64 inference prototype

This prototype converts the complete persisted HeatShield model bundle from
scikit-learn/joblib to five ONNX models and scores them with ONNX Runtime on a
native Arm64 CPU. It preserves:

- median imputation and fitted missing-value indicators;
- the point forecast and all three quantile forecasts;
- per-row quantile ordering;
- the exceedance classifier, fitted Platt calibration, and decision threshold.

The export also preserves scikit-learn's HistGradientBoosting branch semantics.
The source runtime receives float32 features but evaluates fitted float64 split
thresholds. Because ONNX-ML v1 stores thresholds as floats, the exporter uses
the greatest float32 boundary not above each fitted threshold instead of
round-to-nearest. This prevents threshold-adjacent rows from changing branches.

The before/after benchmark uses separate processes on the same machine. The
native workflow fixes both runtimes to one numerical-library thread, suppresses
only scikit-learn's feature-name diagnostic during timing, and measures 100
iterations after 10 warmups at the contest's primary batch size of 256. It
records median and p95 latency, throughput, model bytes, process maximum RSS,
runtime versions, architecture, fixture hash, and an output digest in JSON.

## Evidence boundary

No Arm performance claim exists until `comparison.json` contains all three:

1. `native_arm_evidence: true`;
2. `parity_passed: true`; and
3. `primary_speedup_passed: true` for the configured 1.20x median-latency gate.

The workflow passes `--enforce-gate`, so a result below 1.20x cannot produce a
green evidence job. `comparison.json` also embeds the exact unchanged parity
tolerances and requires its parity, baseline, and candidate reports to use the
same fixture and GitHub runner environment.

The deterministic input fixture samples fitted tree split neighborhoods and
missing-value paths. It is useful for conversion parity and repeatable runtime
measurement, but it is **not** a substitute for the already documented
2024-2025 holdout evaluation and does not re-estimate model accuracy.

## Reproduce locally

From the repository root with Python 3.12:

```bash
python -m venv .venv-arm
.venv-arm/bin/python -m pip install -r model/arm_optimization/requirements.txt
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv-arm/bin/python model/arm_optimization/export_models.py
.venv-arm/bin/python model/arm_optimization/validate_parity.py
.venv-arm/bin/python model/arm_optimization/benchmark.py \
  --engine baseline --output benchmark-results/baseline.json \
  --batch-sizes 256 --warmup 10 --iterations 100 \
  --threads 1 --require-controlled-threads
.venv-arm/bin/python model/arm_optimization/benchmark.py \
  --engine candidate --output benchmark-results/candidate.json \
  --batch-sizes 256 --warmup 10 --iterations 100 \
  --threads 1 --require-controlled-threads
.venv-arm/bin/python model/arm_optimization/compare_benchmarks.py \
  --baseline benchmark-results/baseline.json \
  --candidate benchmark-results/candidate.json \
  --parity benchmark-results/parity.json \
  --output benchmark-results/comparison.json
```

On Windows, replace `.venv-arm/bin/python` with
`.venv-arm\\Scripts\\python.exe`.

The GitHub Actions workflow runs the same commands on GitHub's native
`ubuntu-24.04-arm` image, requires `platform.machine()` to resolve to Arm64,
and uploads every machine-readable result plus the exported ONNX package.

## External runner evidence still required

Local x86 results are useful only as a harness smoke test. Before making the
contest performance claim, preserve a successful GitHub Actions run for the
exact submitted commit and its `heatshield-native-arm64-evidence` artifact. The
artifact must contain:

- `comparison.json` with `system.architecture` equal to `aarch64` or `arm64`, a
  non-null GitHub run URL and commit SHA, `parity_passed: true`,
  `primary_batch_size: 256`, `primary_speedup_passed: true`, and
  `performance_claim_allowed: true`;
- `parity.json` showing zero classification mismatches and every numeric result
  within the committed tolerances (1e-3 for forecasts and 2e-5 for calibrated
  probability);
- `baseline.json` and `candidate.json` showing identical fixture, runner, thread
  policy, warmup count, and iteration count; and
- `SHA256SUMS.txt`, the pinned Python environment, and the exported ONNX package
  so the evidence can be independently checked.

A green job URL plus that artifact is the remaining external proof. Until it
exists, `performance_claim_allowed` must remain false and no native-Arm speedup
number should be presented as contest evidence.
