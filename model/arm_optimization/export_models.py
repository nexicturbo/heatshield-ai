from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import onnx
import onnxruntime
import sklearn
import skl2onnx
from skl2onnx import convert_sklearn
from skl2onnx.common import _container as skl2onnx_container
from skl2onnx.common.data_types import FloatTensorType

from runtime import clean_float, sha256_file


REGRESSOR_NAMES = ("point", "q10", "q50", "q90")


def convert_with_tree_attribute_compatibility(
    model: Any, **kwargs: Any
) -> onnx.ModelProto:
    """Convert while normalizing one schema-defined TreeEnsemble int attribute.

    skl2onnx 1.20 emits Python/NumPy booleans for the ONNX-ML
    ``nodes_missing_value_tracks_true`` attribute. ONNX 1.22 correctly models
    that attribute as repeated INT and its newer protobuf binding rejects bools.
    The values are semantically 0/1, so normalize only that attribute while the
    converter constructs its node and restore the library function afterward.
    """

    original_make_node = skl2onnx_container.make_node

    def compatible_make_node(
        op_type: str,
        inputs: Any,
        outputs: Any,
        name: str | None = None,
        **attributes: Any,
    ) -> Any:
        key = "nodes_missing_value_tracks_true"
        if key in attributes:
            attributes[key] = [int(value) for value in attributes[key]]
        return original_make_node(op_type, inputs, outputs, name=name, **attributes)

    skl2onnx_container.make_node = compatible_make_node
    try:
        return convert_sklearn(model, **kwargs)
    finally:
        skl2onnx_container.make_node = original_make_node


def float32_branch_boundary(threshold: float) -> np.float32:
    """Return the float32 boundary equivalent to a float64 ``<=`` split.

    HeatShield accepts float32 feature matrices, but scikit-learn promotes them
    to float64 before evaluating HistGradientBoosting thresholds.  ONNX-ML v1
    stores those thresholds as floats.  Rounding a fitted threshold upward can
    therefore include one float32 value that scikit-learn sends to the false
    branch.  The greatest float32 value not above the fitted threshold preserves
    the source branch decision for every possible float32 input.
    """

    exact = float(threshold)
    if not np.isfinite(exact):
        raise ValueError(f"Expected a finite tree threshold, received {exact!r}")
    boundary = np.float32(exact)
    if float(boundary) > exact:
        boundary = np.nextafter(
            boundary, np.float32(-np.inf), dtype=np.float32
        )
    return boundary


def preserve_hist_gradient_boosting_branches(
    source_model: Any, converted: onnx.ModelProto
) -> int:
    """Repair lossy HistGradientBoosting thresholds in a converted ONNX tree.

    ``skl2onnx`` serializes the model's float64 split thresholds using ONNX-ML
    v1's repeated-float attribute.  This function maps each exported tree/node
    back to the fitted predictor and writes the branch-equivalent float32 floor.
    It returns the number of thresholds that required downward adjustment.
    Other sklearn tree families are left unchanged.
    """

    predictor_iterations = getattr(source_model, "_predictors", None)
    if predictor_iterations is None:
        return 0
    predictors = [
        predictor
        for iteration in predictor_iterations
        for predictor in iteration
    ]
    tree_nodes = [
        node
        for node in converted.graph.node
        if node.op_type in {"TreeEnsembleRegressor", "TreeEnsembleClassifier"}
    ]
    if len(tree_nodes) != 1:
        raise RuntimeError(
            "Expected exactly one converted TreeEnsemble for HistGradientBoosting"
        )
    tree_node = tree_nodes[0]
    attributes = {attribute.name: attribute for attribute in tree_node.attribute}
    required = {"nodes_treeids", "nodes_nodeids", "nodes_modes", "nodes_values"}
    missing = sorted(required - attributes.keys())
    if missing:
        raise RuntimeError(f"Converted TreeEnsemble is missing attributes: {missing}")
    tree_ids = list(attributes["nodes_treeids"].ints)
    node_ids = list(attributes["nodes_nodeids"].ints)
    modes = list(attributes["nodes_modes"].strings)
    if not (len(tree_ids) == len(node_ids) == len(modes)):
        raise RuntimeError(
            "Converted TreeEnsemble node attributes have unequal lengths"
        )

    values: list[float] = []
    adjusted = 0
    for tree_id, node_id, mode in zip(tree_ids, node_ids, modes, strict=True):
        if not 0 <= tree_id < len(predictors):
            raise RuntimeError(f"Converted tree id {tree_id} is out of range")
        nodes = predictors[tree_id].nodes
        if not 0 <= node_id < len(nodes):
            raise RuntimeError(
                f"Converted node id {node_id} is out of range for tree {tree_id}"
            )
        source_is_leaf = bool(nodes[node_id]["is_leaf"])
        if mode == b"LEAF":
            if not source_is_leaf:
                raise RuntimeError(
                    f"Converted tree {tree_id} node {node_id} changed into a leaf"
                )
            values.append(0.0)
            continue
        if mode != b"BRANCH_LEQ" or source_is_leaf:
            raise RuntimeError(
                "Only matching numerical <= HistGradientBoosting branches are "
                f"supported; tree {tree_id} node {node_id} uses {mode!r}"
            )
        exact = float(nodes[node_id]["num_threshold"])
        boundary = float32_branch_boundary(exact)
        adjusted += int(float(boundary) != float(np.float32(exact)))
        values.append(float(boundary))

    values_attribute = attributes["nodes_values"]
    del values_attribute.floats[:]
    values_attribute.floats.extend(values)
    return adjusted


def preprocessor_metadata(imputer: Any) -> dict[str, Any]:
    indicator = getattr(imputer, "indicator_", None)
    indicator_features = [] if indicator is None else indicator.features_.tolist()
    statistics = np.asarray(imputer.statistics_, dtype=np.float32)
    if np.isnan(statistics).any():
        raise ValueError("The exported bundle contains an all-missing training feature")
    return {
        "strategy": "median_with_missing_indicators",
        "statistics": [clean_float(value) for value in statistics],
        "indicator_features": [int(value) for value in indicator_features],
        "input_feature_count": int(len(statistics)),
        "output_feature_count": int(len(statistics) + len(indicator_features)),
    }


def regressor_output_name(model: onnx.ModelProto) -> str:
    if len(model.graph.output) != 1:
        raise RuntimeError("Expected one regressor output")
    return model.graph.output[0].name


def classifier_output_names(model: onnx.ModelProto) -> tuple[str, str]:
    if len(model.graph.output) != 2:
        raise RuntimeError("Expected classifier label and probability outputs")
    names = [output.name for output in model.graph.output]
    probability = next((name for name in names if "prob" in name.lower()), names[1])
    label = next(name for name in names if name != probability)
    return label, probability


def model_thresholds(model: Any, raw_feature_count: int) -> list[list[float]]:
    thresholds: list[list[float]] = [[] for _ in range(raw_feature_count)]
    bin_mapper = getattr(model, "_bin_mapper", None)
    if bin_mapper is not None:
        for index, values in enumerate(bin_mapper.bin_thresholds_[:raw_feature_count]):
            thresholds[index].extend(float(value) for value in values)
    estimators = getattr(model, "estimators_", None)
    if estimators is not None:
        for estimator in np.asarray(estimators, dtype=object).reshape(-1):
            tree = getattr(estimator, "tree_", None)
            if tree is None:
                continue
            for feature, threshold in zip(tree.feature, tree.threshold, strict=True):
                if 0 <= int(feature) < raw_feature_count:
                    thresholds[int(feature)].append(float(threshold))
    return thresholds


def make_branch_fixture(bundle: dict[str, Any], rows: int, seed: int) -> np.ndarray:
    raw_feature_count = len(bundle["feature_columns"])
    medians = np.asarray(
        bundle["regression"]["imputer"].statistics_, dtype=np.float32
    )
    thresholds = [[] for _ in range(raw_feature_count)]
    models = [
        bundle["regression"]["point_model"],
        *bundle["regression"]["quantile_models"].values(),
        bundle["classifier"]["base_model"],
    ]
    for model in models:
        for index, values in enumerate(model_thresholds(model, raw_feature_count)):
            thresholds[index].extend(values)
    rng = np.random.default_rng(seed)
    fixture = np.tile(medians, (rows, 1)).astype(np.float32)
    for feature_index, values in enumerate(thresholds):
        finite = np.unique(np.asarray(values, dtype=np.float64))
        finite = finite[np.isfinite(finite)]
        if finite.size == 0:
            continue
        if len(finite) > 1:
            gaps = np.diff(finite)
            positive_gaps = gaps[gaps > 0]
            edge_gap = (
                float(np.median(positive_gaps)) if positive_gaps.size else 1.0
            )
            interior = (finite[:-1] + finite[1:]) / 2.0
            candidates = np.concatenate(
                (
                    [finite[0] - edge_gap / 2.0],
                    interior,
                    [finite[-1] + edge_gap / 2.0],
                )
            )
        else:
            edge_gap = max(abs(float(finite[0])) * 0.01, 0.1)
            candidates = np.asarray(
                [finite[0] - edge_gap, finite[0] + edge_gap], dtype=np.float64
            )
        choices = rng.integers(0, len(candidates), size=rows)
        # Bin interiors exercise learned paths without placing float32 values on
        # split boundaries where equivalent runtimes may round in either direction.
        fixture[:, feature_index] = candidates[choices].astype(np.float32)
    indicator_features = np.unique(
        np.concatenate(
            (
                bundle["regression"]["imputer"].indicator_.features_,
                bundle["classifier"]["imputer"].indicator_.features_,
            )
        )
    )
    for offset, feature_index in enumerate(indicator_features):
        fixture[(np.arange(rows) + offset) % 17 == 0, int(feature_index)] = np.nan
    fixture[0] = medians
    return fixture


def write_model(model: onnx.ModelProto, path: Path) -> dict[str, Any]:
    onnx.checker.check_model(model)
    path.write_bytes(model.SerializeToString())
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def export(
    model_path: Path, output_directory: Path, fixture_rows: int, seed: int
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    bundle = joblib.load(model_path)
    regression_feature_count = int(
        bundle["regression"]["point_model"].n_features_in_
    )
    classifier_feature_count = int(
        bundle["classifier"]["base_model"].n_features_in_
    )
    regressors = {
        "point": bundle["regression"]["point_model"],
        **bundle["regression"]["quantile_models"],
    }
    model_metadata: dict[str, Any] = {}
    threshold_adjustments: dict[str, int] = {}
    for name in REGRESSOR_NAMES:
        converted = convert_with_tree_attribute_compatibility(
            regressors[name],
            initial_types=[
                ("features", FloatTensorType([None, regression_feature_count]))
            ],
            target_opset={"": 21, "ai.onnx.ml": 3},
        )
        threshold_adjustments[name] = preserve_hist_gradient_boosting_branches(
            regressors[name], converted
        )
        details = write_model(converted, output_directory / f"{name}.onnx")
        details["prediction_output"] = regressor_output_name(converted)
        model_metadata[name] = details
    classifier = bundle["classifier"]["base_model"]
    converted_classifier = convert_with_tree_attribute_compatibility(
        classifier,
        initial_types=[
            ("features", FloatTensorType([None, classifier_feature_count]))
        ],
        options={id(classifier): {"zipmap": False}},
        target_opset={"": 21, "ai.onnx.ml": 3},
    )
    threshold_adjustments["classifier"] = preserve_hist_gradient_boosting_branches(
        classifier, converted_classifier
    )
    label_output, probability_output = classifier_output_names(converted_classifier)
    classifier_details = write_model(
        converted_classifier, output_directory / "classifier.onnx"
    )
    classifier_details.update(
        {"label_output": label_output, "probability_output": probability_output}
    )
    model_metadata["classifier"] = classifier_details

    calibrator = bundle["classifier"]["calibrator"]
    if calibrator is None:
        calibration: dict[str, Any] = {"kind": "identity"}
    else:
        calibration = {
            "kind": "platt_logit",
            "coefficient": clean_float(calibrator.coef_[0, 0]),
            "intercept": clean_float(calibrator.intercept_[0]),
            "clip_epsilon": 1e-6,
        }
    fixture = make_branch_fixture(bundle, rows=fixture_rows, seed=seed)
    fixture_path = output_directory / "benchmark-inputs.npz"
    np.savez_compressed(
        fixture_path,
        features=fixture,
        feature_columns=np.asarray(bundle["feature_columns"], dtype=str),
    )
    metadata = {
        "schema_version": 1,
        "purpose": "Arm64 ONNX Runtime export of the HeatShield environmental model",
        "source_bundle": {
            "path": model_path.name,
            "bytes": model_path.stat().st_size,
            "sha256": sha256_file(model_path),
            "schema_version": int(bundle["schema_version"]),
        },
        "feature_columns": bundle["feature_columns"],
        "preprocessing": {
            "regression": preprocessor_metadata(bundle["regression"]["imputer"]),
            "classifier": preprocessor_metadata(bundle["classifier"]["imputer"]),
        },
        "models": model_metadata,
        "positive_class_index": 1,
        "calibration": calibration,
        "decision_threshold": clean_float(
            bundle["classifier"]["decision_threshold"]
        ),
        "postprocessing": {
            "quantiles": "sort q10/q50/q90 per row",
            "classification": "calibrated probability >= decision_threshold",
        },
        "fixture": {
            "path": fixture_path.name,
            "rows": int(fixture.shape[0]),
            "columns": int(fixture.shape[1]),
            "seed": int(seed),
            "sha256": sha256_file(fixture_path),
            "scope": "synthetic branch-coverage fixture; not accuracy evidence",
        },
        "tool_versions": {
            "joblib": joblib.__version__,
            "numpy": np.__version__,
            "onnx": onnx.__version__,
            "onnxruntime": onnxruntime.__version__,
            "scikit_learn": sklearn.__version__,
            "skl2onnx": skl2onnx.__version__,
        },
        "export_compatibility": {
            "normalized_attribute": "nodes_missing_value_tracks_true",
            "normalization": "boolean values converted to schema-required integers 0/1",
            "hist_gradient_boosting_thresholds": {
                "strategy": (
                    "greatest float32 value not above each fitted float64 threshold"
                ),
                "purpose": (
                    "preserve scikit-learn <= branch decisions for float32 inputs"
                ),
                "downward_adjustments": threshold_adjustments,
            },
        },
    }
    (output_directory / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "export_directory": str(output_directory),
                "fixture_rows": fixture_rows,
                "model_count": len(model_metadata),
                "source_bundle_sha256": metadata["source_bundle"]["sha256"],
            },
            sort_keys=True,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("model/artifacts/heatshield-model.joblib"),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("model/artifacts/arm_onnx"),
    )
    parser.add_argument("--fixture-rows", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=20260802)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    export(
        arguments.model,
        arguments.output_directory,
        fixture_rows=arguments.fixture_rows,
        seed=arguments.seed,
    )
