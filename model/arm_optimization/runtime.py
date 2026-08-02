from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sys
from pathlib import Path
from typing import Any, Protocol

import numpy as np


OUTPUT_KEYS = (
    "point_f",
    "q10_f",
    "q50_f",
    "q90_f",
    "exceed_95_probability",
    "exceed_95",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_float(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Expected a finite number, received {result!r}")
    return result


def system_metadata() -> dict[str, Any]:
    github_server_url = os.environ.get("GITHUB_SERVER_URL")
    github_repository = os.environ.get("GITHUB_REPOSITORY")
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    github_run_url = None
    if github_server_url and github_repository and github_run_id:
        github_run_url = (
            f"{github_server_url}/{github_repository}/actions/runs/{github_run_id}"
        )
    return {
        "architecture": platform.machine().lower(),
        "cpu_count": os.cpu_count(),
        "operating_system": platform.platform(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "executable": Path(sys.executable).name,
        "github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
        "github_repository": github_repository,
        "github_ref": os.environ.get("GITHUB_REF"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_run_id": github_run_id,
        "github_run_url": github_run_url,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_workflow": os.environ.get("GITHUB_WORKFLOW"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "runner_os": os.environ.get("RUNNER_OS"),
    }


def is_native_arm64(machine: str | None = None) -> bool:
    normalized = (machine or platform.machine()).lower().replace("_", "")
    return normalized in {"aarch64", "arm64"}


def _calibrate_probability(
    raw_probability: np.ndarray, metadata: dict[str, Any]
) -> np.ndarray:
    raw = np.asarray(raw_probability, dtype=np.float64).reshape(-1)
    calibration = metadata["calibration"]
    if calibration["kind"] == "identity":
        return np.clip(raw, 0.0, 1.0)
    if calibration["kind"] != "platt_logit":
        raise ValueError(f"Unsupported calibration kind: {calibration['kind']}")
    epsilon = float(calibration["clip_epsilon"])
    clipped = np.clip(raw, epsilon, 1.0 - epsilon)
    logits = np.log(clipped / (1.0 - clipped))
    z = float(calibration["coefficient"]) * logits + float(calibration["intercept"])
    probability = np.empty_like(z)
    positive = z >= 0
    probability[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
    exp_z = np.exp(z[~positive])
    probability[~positive] = exp_z / (1.0 + exp_z)
    return probability


def _result(
    point: np.ndarray,
    quantiles: np.ndarray,
    raw_probability: np.ndarray,
    metadata: dict[str, Any],
) -> dict[str, np.ndarray]:
    ordered = np.sort(np.asarray(quantiles, dtype=np.float64), axis=1)
    calibrated = _calibrate_probability(raw_probability, metadata)
    threshold = float(metadata["decision_threshold"])
    return {
        "point_f": np.asarray(point, dtype=np.float64).reshape(-1),
        "q10_f": ordered[:, 0],
        "q50_f": ordered[:, 1],
        "q90_f": ordered[:, 2],
        "exceed_95_probability": calibrated,
        "exceed_95": calibrated >= threshold,
    }


class Runtime(Protocol):
    def predict(self, features: np.ndarray) -> dict[str, np.ndarray]: ...


class SklearnRuntime:
    """Faithful before-optimization runtime for the persisted joblib bundle."""

    def __init__(self, model_path: Path) -> None:
        import joblib

        self.model_path = model_path
        self.bundle = joblib.load(model_path)
        calibrator = self.bundle["classifier"]["calibrator"]
        if calibrator is None:
            calibration = {"kind": "identity"}
        else:
            calibration = {
                "kind": "platt_logit",
                "coefficient": clean_float(calibrator.coef_[0, 0]),
                "intercept": clean_float(calibrator.intercept_[0]),
                "clip_epsilon": 1e-6,
            }
        self.metadata = {
            "calibration": calibration,
            "decision_threshold": clean_float(
                self.bundle["classifier"]["decision_threshold"]
            ),
        }

    @property
    def feature_count(self) -> int:
        return len(self.bundle["feature_columns"])

    def predict(self, features: np.ndarray) -> dict[str, np.ndarray]:
        x = np.asarray(features, dtype=np.float32)
        if x.ndim != 2 or x.shape[1] != self.feature_count:
            raise ValueError(
                f"Expected [rows, {self.feature_count}] features, received {x.shape}"
            )
        regression = self.bundle["regression"]
        reg_x = regression["imputer"].transform(x)
        point = regression["point_model"].predict(reg_x)
        quantiles = np.column_stack(
            [
                regression["quantile_models"][name].predict(reg_x)
                for name in ("q10", "q50", "q90")
            ]
        )
        classifier = self.bundle["classifier"]
        cls_x = classifier["imputer"].transform(x)
        raw_probability = classifier["base_model"].predict_proba(cls_x)[:, 1]
        return _result(point, quantiles, raw_probability, self.metadata)


class MedianIndicatorPreprocessor:
    """Dependency-light equivalent of the fitted SimpleImputer transforms."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.statistics = np.asarray(config["statistics"], dtype=np.float32)
        self.indicator_features = np.asarray(
            config["indicator_features"], dtype=np.int64
        )
        self.output_feature_count = int(config["output_feature_count"])
        if np.isnan(self.statistics).any():
            raise ValueError("All-missing training features are not supported")

    def transform(self, features: np.ndarray) -> np.ndarray:
        x = np.asarray(features, dtype=np.float32)
        if x.ndim != 2 or x.shape[1] != len(self.statistics):
            raise ValueError(
                f"Expected [rows, {len(self.statistics)}] features, received {x.shape}"
            )
        missing = np.isnan(x)
        filled = np.where(missing, self.statistics[None, :], x)
        if self.indicator_features.size:
            indicators = missing[:, self.indicator_features].astype(np.float32)
            filled = np.concatenate((filled, indicators), axis=1)
        if filled.shape[1] != self.output_feature_count:
            raise RuntimeError(
                "Exported preprocessing shape does not match the fitted model: "
                f"{filled.shape[1]} != {self.output_feature_count}"
            )
        return np.ascontiguousarray(filled, dtype=np.float32)


class OnnxRuntime:
    """Arm-ready runtime with NumPy preprocessing and ONNX Runtime scoring."""

    def __init__(self, export_directory: Path, threads: int = 1) -> None:
        import onnxruntime as ort

        self.export_directory = export_directory
        self.metadata = json.loads(
            (export_directory / "metadata.json").read_text(encoding="utf-8")
        )
        self.regression_preprocessor = MedianIndicatorPreprocessor(
            self.metadata["preprocessing"]["regression"]
        )
        self.classifier_preprocessor = MedianIndicatorPreprocessor(
            self.metadata["preprocessing"]["classifier"]
        )
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = int(threads)
        options.inter_op_num_threads = 1
        self.sessions: dict[str, Any] = {}
        for name, file_metadata in self.metadata["models"].items():
            model_path = export_directory / file_metadata["path"]
            actual_sha = sha256_file(model_path)
            if actual_sha != file_metadata["sha256"]:
                raise RuntimeError(f"SHA-256 mismatch for {model_path.name}")
            self.sessions[name] = ort.InferenceSession(
                str(model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )

    @property
    def feature_count(self) -> int:
        return len(self.metadata["feature_columns"])

    def _run_regressor(self, name: str, features: np.ndarray) -> np.ndarray:
        session = self.sessions[name]
        output_name = self.metadata["models"][name]["prediction_output"]
        return session.run([output_name], {"features": features})[0].reshape(-1)

    def predict(self, features: np.ndarray) -> dict[str, np.ndarray]:
        x = np.asarray(features, dtype=np.float32)
        if x.ndim != 2 or x.shape[1] != self.feature_count:
            raise ValueError(
                f"Expected [rows, {self.feature_count}] features, received {x.shape}"
            )
        reg_x = self.regression_preprocessor.transform(x)
        point = self._run_regressor("point", reg_x)
        quantiles = np.column_stack(
            [self._run_regressor(name, reg_x) for name in ("q10", "q50", "q90")]
        )
        cls_x = self.classifier_preprocessor.transform(x)
        classifier = self.sessions["classifier"]
        probability_output = self.metadata["models"]["classifier"][
            "probability_output"
        ]
        raw_probability = classifier.run(
            [probability_output], {"features": cls_x}
        )[0][:, int(self.metadata["positive_class_index"])]
        return _result(point, quantiles, raw_probability, self.metadata)


def output_digest(outputs: dict[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for key in OUTPUT_KEYS:
        values = np.ascontiguousarray(outputs[key])
        digest.update(key.encode("utf-8"))
        digest.update(values.tobytes())
    return digest.hexdigest()
