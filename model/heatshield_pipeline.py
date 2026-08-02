#!/usr/bin/env python3
"""Reproducible Chicago heat-forecast model pipeline.

The pipeline downloads NOAA/NCEI Global Hourly observations for Chicago
O'Hare and Midway, derives NWS-style apparent temperature, builds
leakage-resistant trailing daily features, and evaluates next-day regression
and exceedance models with forward temporal validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
ARTIFACT_DIR = BASE_DIR / "artifacts"
MANIFEST_PATH = RAW_DIR / "manifest.json"
PROCESSED_PATH = PROCESSED_DIR / "daily-supervised.csv"
MODEL_PATH = ARTIFACT_DIR / "heatshield-model.joblib"
EVALUATION_PATH = ARTIFACT_DIR / "heatshield-model-evaluation.json"
PREDICTIONS_PATH = ARTIFACT_DIR / "holdout-predictions.csv"

STATIONS = {
    "72530094846": "Chicago O'Hare International Airport",
    "72534014819": "Chicago Midway International Airport",
}
STATION_QUERY = "%2C".join(STATIONS)
URL_TEMPLATE = (
    "https://www.ncei.noaa.gov/access/services/data/v1"
    "?dataset=global-hourly"
    "&stations=" + STATION_QUERY +
    "&startDate={year}-05-01T00%3A00%3A00"
    "&endDate={year}-09-30T23%3A59%3A59"
    "&dataTypes=TMP%2CDEW%2CWND"
    "&format=csv"
    "&includeAttributes=false"
)
MAX_RESPONSE_BYTES = 100 * 1024 * 1024
ACCEPTED_QUALITY_CODES = frozenset({"0", "1", "4", "5"})
CHICAGO_TZ = "America/Chicago"
TARGET_THRESHOLD_F = 95.0

CURRENT_FEATURES = [
    "temp_max_f",
    "temp_mean_f",
    "temp_min_f",
    "dew_max_f",
    "dew_mean_f",
    "rh_max_pct",
    "rh_mean_pct",
    "apparent_max_f",
    "apparent_mean_f",
    "wind_mean_ms",
    "wind_max_ms",
    "hours_apparent_ge_90",
    "hours_apparent_ge_95",
    "observation_hours",
    "apparent_hours",
    "coverage_fraction",
]
TRAILING_METRICS = [
    "temp_max_f",
    "temp_min_f",
    "dew_max_f",
    "rh_mean_pct",
    "apparent_max_f",
    "wind_mean_ms",
    "hours_apparent_ge_90",
]


class DataCapError(RuntimeError):
    """Raised when a response would exceed the per-file download cap."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def stream_response_to_file(
    response: BinaryIO,
    destination: Path,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> int:
    """Stream a response to disk while enforcing a hard byte cap."""
    raw_length = getattr(response, "headers", {}).get("Content-Length")
    if raw_length:
        try:
            declared = int(raw_length)
        except ValueError:
            declared = -1
        if declared > max_bytes:
            raise DataCapError(
                f"Declared response size {declared:,} exceeds {max_bytes:,}-byte cap"
            )

    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise DataCapError(
                    f"Streamed response exceeds {max_bytes:,}-byte cap"
                )
            handle.write(chunk)
    return total


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {
            "schema_version": 1,
            "dataset": "NOAA/NCEI Global Hourly",
            "per_file_cap_bytes": MAX_RESPONSE_BYTES,
            "entries": [],
        }
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("per_file_cap_bytes") != MAX_RESPONSE_BYTES:
        raise RuntimeError("Existing manifest has an unexpected response cap")
    return manifest


def write_manifest(manifest: dict[str, Any]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=RAW_DIR, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, MANIFEST_PATH)


def verified_manifest_entry(
    manifest: dict[str, Any], year: int, url: str
) -> dict[str, Any] | None:
    for entry in reversed(manifest["entries"]):
        if entry["year"] != year or entry["url"] != url:
            continue
        path = BASE_DIR / entry["relative_path"]
        if (
            path.is_file()
            and path.stat().st_size == entry["bytes"]
            and sha256_file(path) == entry["sha256"]
        ):
            return entry
    return None


def fetch_year(year: int, retries: int = 4) -> dict[str, Any]:
    """Fetch one warm-season file into content-addressed raw storage."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = URL_TEMPLATE.format(year=year)
    manifest = load_manifest()
    cached = verified_manifest_entry(manifest, year, url)
    if cached:
        print(f"{year}: verified cached {cached['relative_path']}")
        return cached

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".global-hourly-{year}-", suffix=".tmp", dir=RAW_DIR
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "HeatShieldResearch/1.0 "
                        "(reproducible public NOAA analysis)"
                    )
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                selected_headers = {
                    key.lower(): response.headers.get(key)
                    for key in (
                        "Content-Type",
                        "Content-Length",
                        "ETag",
                        "Last-Modified",
                    )
                    if response.headers.get(key) is not None
                }
                byte_count = stream_response_to_file(response, temporary)

            digest = sha256_file(temporary)
            final = RAW_DIR / f"global-hourly-{year}-{digest[:16]}.csv"
            if final.exists():
                if sha256_file(final) != digest:
                    raise RuntimeError(f"Content-address collision at {final}")
                temporary.unlink()
            else:
                os.replace(temporary, final)

            entry = {
                "year": year,
                "stations": list(STATIONS),
                "season": {"start": f"{year}-05-01", "end": f"{year}-09-30"},
                "url": url,
                "sha256": digest,
                "fetched_at_utc": utc_now(),
                "bytes": byte_count,
                "rows": count_csv_rows(final),
                "relative_path": final.relative_to(BASE_DIR).as_posix(),
                "response_headers": selected_headers,
            }
            # Preserve all prior entries. A changed upstream response creates a
            # new content-addressed file and a new provenance entry.
            manifest["entries"].append(entry)
            write_manifest(manifest)
            print(
                f"{year}: fetched {entry['rows']:,} rows, "
                f"{entry['bytes']:,} bytes, sha256={digest}"
            )
            return entry
        except (
            DataCapError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if isinstance(exc, DataCapError) or attempt == retries:
                break
            delay = 2 ** (attempt - 1)
            print(f"{year}: attempt {attempt} failed ({exc}); retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"Failed to fetch NOAA data for {year}: {last_error}")


def fetch_all(years: Iterable[int]) -> list[dict[str, Any]]:
    return [fetch_year(year) for year in years]


def parse_scaled_measurement(
    value: Any,
    *,
    scale: float = 10.0,
    sentinel: str = "+9999",
    accepted_quality: frozenset[str] = ACCEPTED_QUALITY_CODES,
) -> float:
    """Parse an ISD value such as '+0294,1' into engineering units."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return math.nan
    parts = str(value).strip().split(",")
    if len(parts) < 2:
        return math.nan
    raw, quality = parts[0], parts[1]
    if raw in {sentinel, sentinel.lstrip("+"), "-9999"}:
        return math.nan
    if quality not in accepted_quality:
        return math.nan
    try:
        return int(raw) / scale
    except ValueError:
        return math.nan


def parse_wind_speed(
    value: Any,
    accepted_quality: frozenset[str] = ACCEPTED_QUALITY_CODES,
) -> float:
    """Parse WND's tenths-of-m/s speed and its quality code."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return math.nan
    parts = str(value).strip().split(",")
    if len(parts) < 5:
        return math.nan
    raw_speed, quality = parts[3], parts[4]
    if raw_speed == "9999" or quality not in accepted_quality:
        return math.nan
    try:
        return int(raw_speed) / 10.0
    except ValueError:
        return math.nan


def relative_humidity_pct(temp_c: Any, dew_c: Any) -> np.ndarray:
    """Magnus-formula relative humidity, clipped to physical bounds."""
    temperature = np.asarray(temp_c, dtype=float)
    dewpoint = np.asarray(dew_c, dtype=float)
    exponent_dew = (17.625 * dewpoint) / (243.04 + dewpoint)
    exponent_temp = (17.625 * temperature) / (243.04 + temperature)
    rh = 100.0 * np.exp(exponent_dew - exponent_temp)
    return np.clip(rh, 0.0, 100.0)


def nws_apparent_temperature_f(temp_f: Any, rh_pct: Any) -> np.ndarray:
    """NWS Heat Index procedure, with air temperature below its threshold.

    The Rothfusz regression is selected only when the simple-formula average
    reaches 80 F. For cooler/drier observations this application defines
    apparent temperature as air temperature rather than extrapolating the
    regression beyond its intended warm-humid domain.
    """
    temperature = np.asarray(temp_f, dtype=float)
    humidity = np.asarray(rh_pct, dtype=float)

    simple = 0.5 * (
        temperature
        + 61.0
        + ((temperature - 68.0) * 1.2)
        + (humidity * 0.094)
    )
    simple_average = 0.5 * (simple + temperature)
    use_regression = simple_average >= 80.0

    t = temperature
    r = humidity
    rothfusz = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * r
        - 0.22475541 * t * r
        - 0.00683783 * t * t
        - 0.05481717 * r * r
        + 0.00122874 * t * t * r
        + 0.00085282 * t * r * r
        - 0.00000199 * t * t * r * r
    )

    low_mask = (r < 13.0) & (t >= 80.0) & (t <= 112.0)
    low_adjustment = (
        ((13.0 - r) / 4.0)
        * np.sqrt(np.maximum(0.0, (17.0 - np.abs(t - 95.0)) / 17.0))
    )
    rothfusz = np.where(low_mask, rothfusz - low_adjustment, rothfusz)

    high_mask = (r > 85.0) & (t >= 80.0) & (t <= 87.0)
    high_adjustment = ((r - 85.0) / 10.0) * ((87.0 - t) / 5.0)
    rothfusz = np.where(high_mask, rothfusz + high_adjustment, rothfusz)

    return np.where(use_regression, rothfusz, temperature)


def c_to_f(value: Any) -> Any:
    return np.asarray(value, dtype=float) * 9.0 / 5.0 + 32.0


def selected_manifest_entries(years: Iterable[int]) -> list[dict[str, Any]]:
    manifest = load_manifest()
    selected: list[dict[str, Any]] = []
    for year in years:
        url = URL_TEMPLATE.format(year=year)
        entry = verified_manifest_entry(manifest, year, url)
        if entry is None:
            raise RuntimeError(
                f"No verified manifest entry for {year}; run the fetch command first"
            )
        selected.append(entry)
    return selected


def load_hourly_observations(years: Iterable[int]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    required = {"STATION", "DATE", "TMP", "DEW", "WND"}
    for entry in selected_manifest_entries(years):
        path = BASE_DIR / entry["relative_path"]
        frame = pd.read_csv(
            path,
            dtype=str,
            usecols=lambda column: column in required | {"REPORT_TYPE"},
            low_memory=False,
        )
        missing = required - set(frame)
        if missing:
            raise RuntimeError(f"{path} lacks required columns: {sorted(missing)}")
        frames.append(frame)
    raw = pd.concat(frames, ignore_index=True)

    raw["station"] = raw["STATION"].astype(str)
    raw = raw[raw["station"].isin(STATIONS)].copy()
    raw["timestamp_utc"] = pd.to_datetime(raw["DATE"], utc=True, errors="coerce")
    raw["temp_c"] = raw["TMP"].map(parse_scaled_measurement)
    raw["dew_c"] = raw["DEW"].map(parse_scaled_measurement)
    raw["wind_ms"] = raw["WND"].map(parse_wind_speed)
    raw = raw.dropna(subset=["timestamp_utc", "temp_c"])

    # Multiple aviation/synoptic report types can occur within one clock hour.
    # Hourly medians avoid double-weighting duplicate reports and damp obvious
    # within-hour outliers while preserving real observations.
    raw["local_hour"] = (
        raw["timestamp_utc"].dt.tz_convert(CHICAGO_TZ).dt.floor("h")
    )
    hourly = (
        raw.groupby(["station", "local_hour"], as_index=False)
        .agg(
            temp_c=("temp_c", "median"),
            dew_c=("dew_c", "median"),
            wind_ms=("wind_ms", "median"),
            source_reports=("DATE", "size"),
        )
        .sort_values(["station", "local_hour"])
    )
    hourly["temp_f"] = c_to_f(hourly["temp_c"])
    hourly["dew_f"] = c_to_f(hourly["dew_c"])
    hourly["rh_pct"] = relative_humidity_pct(hourly["temp_c"], hourly["dew_c"])
    hourly["apparent_f"] = nws_apparent_temperature_f(
        hourly["temp_f"], hourly["rh_pct"]
    )
    hourly["local_date"] = hourly["local_hour"].dt.tz_localize(None).dt.normalize()
    return hourly


def build_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    working = hourly.copy()
    working["apparent_ge_90"] = (working["apparent_f"] >= 90.0).astype(float)
    working["apparent_ge_95"] = (working["apparent_f"] >= 95.0).astype(float)
    daily = (
        working.groupby(["station", "local_date"], as_index=False)
        .agg(
            temp_max_f=("temp_f", "max"),
            temp_mean_f=("temp_f", "mean"),
            temp_min_f=("temp_f", "min"),
            dew_max_f=("dew_f", "max"),
            dew_mean_f=("dew_f", "mean"),
            rh_max_pct=("rh_pct", "max"),
            rh_mean_pct=("rh_pct", "mean"),
            apparent_max_f=("apparent_f", "max"),
            apparent_mean_f=("apparent_f", "mean"),
            wind_mean_ms=("wind_ms", "mean"),
            wind_max_ms=("wind_ms", "max"),
            hours_apparent_ge_90=("apparent_ge_90", "sum"),
            hours_apparent_ge_95=("apparent_ge_95", "sum"),
            observation_hours=("local_hour", "nunique"),
            apparent_hours=("apparent_f", "count"),
        )
        .sort_values(["station", "local_date"])
    )
    daily["coverage_fraction"] = np.minimum(
        1.0, daily["observation_hours"].astype(float) / 24.0
    )
    # A daily target based on fewer than half the expected hours is too fragile.
    daily = daily[daily["apparent_hours"] >= 12].copy()
    return daily


def build_supervised(daily: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    frame = daily.sort_values(["station", "local_date"]).copy()
    grouped = frame.groupby("station", group_keys=False)
    for metric in TRAILING_METRICS:
        for lag in (1, 2, 3):
            frame[f"{metric}_lag_{lag}d"] = grouped[metric].shift(lag)
        for window in (3, 7):
            frame[f"{metric}_rolling_{window}d_mean"] = grouped[metric].transform(
                lambda series, size=window: series.rolling(
                    size, min_periods=max(2, size - 1)
                ).mean()
            )

    frame["target_date"] = grouped["local_date"].shift(-1)
    frame["target_max_apparent_f"] = grouped["apparent_max_f"].shift(-1)
    frame["target_exceed_95f"] = (
        frame["target_max_apparent_f"] >= TARGET_THRESHOLD_F
    ).astype(float)
    day_gap = frame["target_date"] - frame["local_date"]
    frame = frame[day_gap == pd.Timedelta(days=1)].copy()
    frame["target_exceed_95f"] = frame["target_exceed_95f"].astype(int)
    frame["target_year"] = frame["target_date"].dt.year.astype(int)
    frame["target_month"] = frame["target_date"].dt.month.astype(int)
    target_day = frame["target_date"].dt.dayofyear.astype(float)
    frame["target_doy_sin"] = np.sin(2.0 * np.pi * target_day / 365.25)
    frame["target_doy_cos"] = np.cos(2.0 * np.pi * target_day / 365.25)
    frame["station_is_midway"] = (
        frame["station"] == "72534014819"
    ).astype(int)

    engineered = [
        column
        for column in frame.columns
        if "_lag_" in column or "_rolling_" in column
    ]
    features = (
        CURRENT_FEATURES
        + engineered
        + ["target_doy_sin", "target_doy_cos", "station_is_midway"]
    )
    return frame.reset_index(drop=True), features


def build_dataset(years: Iterable[int]) -> tuple[pd.DataFrame, list[str]]:
    hourly = load_hourly_observations(years)
    daily = build_daily(hourly)
    supervised, features = build_supervised(daily)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    supervised.to_csv(PROCESSED_PATH, index=False, float_format="%.6f")
    metadata = {
        "generated_at_utc": utc_now(),
        "hourly_rows": int(len(hourly)),
        "daily_rows": int(len(daily)),
        "supervised_rows": int(len(supervised)),
        "feature_columns": features,
        "processed_sha256": sha256_file(PROCESSED_PATH),
    }
    with (PROCESSED_DIR / "dataset-metadata.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"Built {len(hourly):,} station-hours, {len(daily):,} station-days, "
        f"and {len(supervised):,} supervised rows"
    )
    return supervised, features


def read_processed() -> tuple[pd.DataFrame, list[str]]:
    if not PROCESSED_PATH.exists():
        raise RuntimeError("Processed dataset is missing; run build first")
    frame = pd.read_csv(
        PROCESSED_PATH,
        parse_dates=["local_date", "target_date"],
    )
    with (PROCESSED_DIR / "dataset-metadata.json").open(
        "r", encoding="utf-8"
    ) as handle:
        metadata = json.load(handle)
    if sha256_file(PROCESSED_PATH) != metadata["processed_sha256"]:
        raise RuntimeError("Processed dataset hash no longer matches its metadata")
    return frame, metadata["feature_columns"]


def fit_regression(
    train: pd.DataFrame, test: pd.DataFrame, features: list[str]
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    from sklearn.ensemble import (
        GradientBoostingRegressor,
        HistGradientBoostingRegressor,
    )
    from sklearn.impute import SimpleImputer

    imputer = SimpleImputer(strategy="median", add_indicator=True)
    x_train = imputer.fit_transform(train[features])
    x_test = imputer.transform(test[features])
    y_train = train["target_max_apparent_f"].to_numpy(dtype=float)

    point = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.04,
        max_iter=300,
        max_leaf_nodes=15,
        min_samples_leaf=12,
        l2_regularization=1.0,
        random_state=2026,
    )
    point.fit(x_train, y_train)
    predictions: dict[str, np.ndarray] = {"point": point.predict(x_test)}

    quantiles: dict[str, Any] = {}
    for label, alpha in (("q10", 0.10), ("q50", 0.50), ("q90", 0.90)):
        model = GradientBoostingRegressor(
            loss="quantile",
            alpha=alpha,
            n_estimators=240,
            learning_rate=0.035,
            max_depth=2,
            min_samples_leaf=10,
            subsample=0.9,
            random_state=2026,
        )
        model.fit(x_train, y_train)
        quantiles[label] = model
        predictions[label] = model.predict(x_test)

    ordered = np.sort(
        np.column_stack(
            [predictions["q10"], predictions["q50"], predictions["q90"]]
        ),
        axis=1,
    )
    predictions["q10"], predictions["q50"], predictions["q90"] = ordered.T
    return {
        "imputer": imputer,
        "point_model": point,
        "quantile_models": quantiles,
    }, predictions


def _fit_base_classifier(
    train: pd.DataFrame, features: list[str]
) -> tuple[Any, Any]:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.utils.class_weight import compute_sample_weight

    imputer = SimpleImputer(strategy="median", add_indicator=True)
    x_train = imputer.fit_transform(train[features])
    y_train = train["target_exceed_95f"].to_numpy(dtype=int)
    model = HistGradientBoostingClassifier(
        learning_rate=0.04,
        max_iter=280,
        max_leaf_nodes=15,
        min_samples_leaf=12,
        l2_regularization=1.0,
        random_state=2026,
    )
    weights = compute_sample_weight(class_weight="balanced", y=y_train)
    model.fit(x_train, y_train, sample_weight=weights)
    return imputer, model


def _logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def fit_calibrated_classifier(
    train: pd.DataFrame, test: pd.DataFrame, features: list[str]
) -> tuple[dict[str, Any], np.ndarray, dict[str, Any]]:
    """Fit a classifier plus Platt calibration on forward out-of-fold scores."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score

    oof_probabilities: list[np.ndarray] = []
    oof_labels: list[np.ndarray] = []
    oof_years: list[int] = []
    years = sorted(int(year) for year in train["target_year"].unique())
    for year in years:
        earlier = train[train["target_year"] < year]
        current = train[train["target_year"] == year]
        if (
            len(earlier) < 400
            or len(current) == 0
            or earlier["target_exceed_95f"].nunique() < 2
        ):
            continue
        imputer, model = _fit_base_classifier(earlier, features)
        raw = model.predict_proba(imputer.transform(current[features]))[:, 1]
        oof_probabilities.append(raw)
        oof_labels.append(current["target_exceed_95f"].to_numpy(dtype=int))
        oof_years.append(year)

    calibrator: Any | None = None
    threshold = 0.5
    calibration_method = "identity-insufficient-temporal-oof"
    if oof_probabilities:
        oof_raw = np.concatenate(oof_probabilities)
        oof_y = np.concatenate(oof_labels)
        if len(oof_y) >= 200 and np.unique(oof_y).size == 2:
            calibrator = LogisticRegression(
                C=1.0, solver="lbfgs", random_state=2026
            )
            calibrator.fit(_logit(oof_raw), oof_y)
            oof_calibrated = calibrator.predict_proba(_logit(oof_raw))[:, 1]
            candidates = np.linspace(0.10, 0.90, 81)
            scores = [
                f1_score(oof_y, oof_calibrated >= candidate, zero_division=0)
                for candidate in candidates
            ]
            threshold = float(candidates[int(np.argmax(scores))])
            calibration_method = "Platt logistic on forward out-of-fold logits"

    final_imputer, final_model = _fit_base_classifier(train, features)
    raw_test = final_model.predict_proba(
        final_imputer.transform(test[features])
    )[:, 1]
    if calibrator is None:
        calibrated_test = raw_test
    else:
        calibrated_test = calibrator.predict_proba(_logit(raw_test))[:, 1]
    return (
        {
            "imputer": final_imputer,
            "base_model": final_model,
            "calibrator": calibrator,
            "decision_threshold": threshold,
        },
        calibrated_test,
        {
            "method": calibration_method,
            "oof_years": oof_years,
            "oof_rows": int(sum(len(labels) for labels in oof_labels)),
            "decision_threshold": threshold,
        },
    )


def regression_metrics(
    actual: np.ndarray,
    point: np.ndarray,
    q10: np.ndarray | None = None,
    q50: np.ndarray | None = None,
    q90: np.ndarray | None = None,
) -> dict[str, Any]:
    from sklearn.metrics import mean_absolute_error, mean_pinball_loss

    y = np.asarray(actual, dtype=float)
    prediction = np.asarray(point, dtype=float)
    result: dict[str, Any] = {
        "rows": int(len(y)),
        "mae_f": float(mean_absolute_error(y, prediction)),
        "rmse_f": float(np.sqrt(np.mean((y - prediction) ** 2))),
        "mean_bias_f": float(np.mean(prediction - y)),
    }
    if q10 is not None and q50 is not None and q90 is not None:
        lower = np.asarray(q10, dtype=float)
        median = np.asarray(q50, dtype=float)
        upper = np.asarray(q90, dtype=float)
        result["quantile"] = {
            "pinball_q10": float(mean_pinball_loss(y, lower, alpha=0.10)),
            "pinball_q50": float(mean_pinball_loss(y, median, alpha=0.50)),
            "pinball_q90": float(mean_pinball_loss(y, upper, alpha=0.90)),
            "central_80_coverage": float(np.mean((y >= lower) & (y <= upper))),
            "mean_interval_width_f": float(np.mean(upper - lower)),
        }
    return result


def expected_calibration_error(
    actual: np.ndarray, probability: np.ndarray, bins: int = 10
) -> float:
    y = np.asarray(actual, dtype=int)
    p = np.asarray(probability, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    error = 0.0
    for index in range(bins):
        if index == bins - 1:
            mask = (p >= edges[index]) & (p <= edges[index + 1])
        else:
            mask = (p >= edges[index]) & (p < edges[index + 1])
        if mask.any():
            error += (mask.sum() / total) * abs(y[mask].mean() - p[mask].mean())
    return float(error)


def classification_metrics(
    actual: np.ndarray, probability: np.ndarray, threshold: float
) -> dict[str, Any]:
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        f1_score,
        log_loss,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y = np.asarray(actual, dtype=int)
    p = np.clip(np.asarray(probability, dtype=float), 1e-8, 1.0 - 1e-8)
    predicted = p >= threshold
    result: dict[str, Any] = {
        "rows": int(len(y)),
        "event_rate": float(np.mean(y)),
        "threshold": float(threshold),
        "brier_score": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "precision": float(precision_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted, zero_division=0)),
        "f1": float(f1_score(y, predicted, zero_division=0)),
        "expected_calibration_error_10bin": expected_calibration_error(y, p),
    }
    if np.unique(y).size == 2:
        result["average_precision"] = float(average_precision_score(y, p))
        result["roc_auc"] = float(roc_auc_score(y, p))
    else:
        result["average_precision"] = None
        result["roc_auc"] = None
    return result


def climatology_predictions(
    train: pd.DataFrame, test: pd.DataFrame, day_window: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    history = train.copy()
    history["target_doy"] = history["target_date"].dt.dayofyear
    point_predictions: list[float] = []
    event_probabilities: list[float] = []
    for row in test.itertuples(index=False):
        target_doy = row.target_date.dayofyear
        station_history = history[history["station"] == row.station]
        neighborhood = station_history[
            (station_history["target_doy"] - target_doy).abs() <= day_window
        ]
        if len(neighborhood) < 10:
            neighborhood = station_history
        point_predictions.append(
            float(neighborhood["target_max_apparent_f"].mean())
        )
        positives = float(neighborhood["target_exceed_95f"].sum())
        event_probabilities.append((positives + 1.0) / (len(neighborhood) + 2.0))
    return np.asarray(point_predictions), np.asarray(event_probabilities)


def season_slice(month: int) -> str:
    if month <= 6:
        return "early_may_june"
    if month <= 8:
        return "peak_july_august"
    return "late_september"


def slice_metrics(
    holdout: pd.DataFrame,
    point: np.ndarray,
    q10: np.ndarray,
    q50: np.ndarray,
    q90: np.ndarray,
    probability: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {"station": {}, "season": {}}
    holdout = holdout.reset_index(drop=True).copy()
    holdout["season_slice"] = holdout["target_month"].map(season_slice)
    for grouping, labels in (
        ("station", holdout["station"]),
        ("season", holdout["season_slice"]),
    ):
        for label in sorted(labels.unique()):
            mask = labels.to_numpy() == label
            display = STATIONS.get(str(label), str(label))
            result[grouping][display] = {
                "regression": regression_metrics(
                    holdout.loc[mask, "target_max_apparent_f"].to_numpy(),
                    point[mask],
                    q10[mask],
                    q50[mask],
                    q90[mask],
                ),
                "classifier": classification_metrics(
                    holdout.loc[mask, "target_exceed_95f"].to_numpy(),
                    probability[mask],
                    threshold,
                ),
            }
    return result


def evaluate_temporal_folds(
    frame: pd.DataFrame, features: list[str]
) -> list[dict[str, Any]]:
    folds: list[dict[str, Any]] = []
    for year in range(2019, 2024):
        train = frame[frame["target_year"] < year]
        test = frame[frame["target_year"] == year]
        if len(train) < 500 or len(test) == 0:
            continue
        _, regression = fit_regression(train, test, features)
        classifier_bundle, probability, calibration = fit_calibrated_classifier(
            train, test, features
        )
        climatology_point, climatology_probability = climatology_predictions(
            train, test
        )
        y_reg = test["target_max_apparent_f"].to_numpy(dtype=float)
        y_cls = test["target_exceed_95f"].to_numpy(dtype=int)
        folds.append(
            {
                "test_year": year,
                "train_target_years": [
                    int(train["target_year"].min()),
                    int(train["target_year"].max()),
                ],
                "rows": {"train": int(len(train)), "test": int(len(test))},
                "model": {
                    "regression": regression_metrics(
                        y_reg,
                        regression["point"],
                        regression["q10"],
                        regression["q50"],
                        regression["q90"],
                    ),
                    "classifier": classification_metrics(
                        y_cls,
                        probability,
                        classifier_bundle["decision_threshold"],
                    ),
                    "calibration": calibration,
                },
                "baselines": {
                    "persistence": regression_metrics(
                        y_reg, test["apparent_max_f"].to_numpy(dtype=float)
                    ),
                    "climatology_regression": regression_metrics(
                        y_reg, climatology_point
                    ),
                    "climatology_classifier": classification_metrics(
                        y_cls, climatology_probability, 0.5
                    ),
                },
            }
        )
        print(f"Validated forward fold {year}")
    return folds


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def train_and_evaluate(
    frame: pd.DataFrame, features: list[str]
) -> dict[str, Any]:
    import joblib

    train = frame[frame["target_year"] <= 2023].copy()
    holdout = frame[frame["target_year"].between(2024, 2025)].copy()
    if train.empty or holdout.empty:
        raise RuntimeError("Expected both 2015-2023 training and 2024-2025 holdout rows")
    if train["target_exceed_95f"].nunique() < 2:
        raise RuntimeError("Training data does not contain both classifier outcomes")

    forward_folds = evaluate_temporal_folds(train, features)
    regression_bundle, regression = fit_regression(train, holdout, features)
    classifier_bundle, probability, calibration = fit_calibrated_classifier(
        train, holdout, features
    )
    threshold = classifier_bundle["decision_threshold"]
    climatology_point, climatology_probability = climatology_predictions(
        train, holdout
    )
    y_reg = holdout["target_max_apparent_f"].to_numpy(dtype=float)
    y_cls = holdout["target_exceed_95f"].to_numpy(dtype=int)

    predictions = holdout[
        [
            "station",
            "local_date",
            "target_date",
            "target_max_apparent_f",
            "target_exceed_95f",
        ]
    ].copy()
    predictions["model_point_f"] = regression["point"]
    predictions["model_q10_f"] = regression["q10"]
    predictions["model_q50_f"] = regression["q50"]
    predictions["model_q90_f"] = regression["q90"]
    predictions["model_exceed_95_probability"] = probability
    predictions["persistence_f"] = holdout["apparent_max_f"].to_numpy()
    predictions["climatology_f"] = climatology_point
    predictions["climatology_exceed_95_probability"] = climatology_probability
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(PREDICTIONS_PATH, index=False, float_format="%.6f")

    model_bundle = {
        "schema_version": 1,
        "feature_columns": features,
        "stations": STATIONS,
        "target": {
            "regression": "next local calendar day's maximum apparent temperature (F)",
            "classifier": "next-day maximum apparent temperature >= 95 F",
        },
        "regression": regression_bundle,
        "classifier": classifier_bundle,
        "postprocessing": {
            "quantile_crossing": "sort q10/q50/q90 predictions per forecast",
            "below_nws_heat_index_threshold": "use air temperature",
        },
    }
    joblib.dump(model_bundle, MODEL_PATH, compress=3)

    manifest = load_manifest()
    selected_entries = selected_manifest_entries(range(2015, 2026))
    artifact = {
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "purpose": (
            "Environmental next-day heat forecasting for Chicago; no medical "
            "outcome or demographic features"
        ),
        "data": {
            "source": "NOAA/NCEI Global Hourly",
            "source_documentation": (
                "https://www.ncei.noaa.gov/support/"
                "access-data-service-api-user-documentation"
            ),
            "stations": STATIONS,
            "warm_seasons": [2015, 2025],
            "manifest_path": MANIFEST_PATH.relative_to(BASE_DIR).as_posix(),
            "manifest_sha256": sha256_file(MANIFEST_PATH),
            "raw_entries": selected_entries,
            "processed_path": PROCESSED_PATH.relative_to(BASE_DIR).as_posix(),
            "processed_sha256": sha256_file(PROCESSED_PATH),
            "quality_policy": {
                "accepted_isd_quality_codes": sorted(ACCEPTED_QUALITY_CODES),
                "rejected_quality_codes": ["2", "3", "6", "7", "9"],
                "temperature_dewpoint_sentinel": "+9999",
                "wind_speed_sentinel": "9999",
                "minimum_apparent_observations_per_station_day": 12,
                "duplicate_report_handling": "median by station and local clock hour",
            },
        },
        "target": {
            "forecast_origin": "end of local feature day",
            "regression": "next-day maximum apparent temperature, degrees F",
            "classifier": "next-day maximum apparent temperature >= 95 F",
            "threshold_f": TARGET_THRESHOLD_F,
        },
        "features": {
            "count": len(features),
            "columns": features,
            "demographic_features": [],
            "medical_outcome_features": [],
        },
        "split": {
            "model_development_target_years": [
                int(train["target_year"].min()),
                int(train["target_year"].max()),
            ],
            "untouched_holdout_target_years": [2024, 2025],
            "forward_validation_test_years": [
                fold["test_year"] for fold in forward_folds
            ],
        },
        "rows": {
            "total": int(len(frame)),
            "development": int(len(train)),
            "holdout": int(len(holdout)),
            "holdout_events": int(y_cls.sum()),
        },
        "models": {
            "point_regressor": "HistGradientBoostingRegressor",
            "quantile_regressors": (
                "GradientBoostingRegressor at q=0.10, 0.50, 0.90"
            ),
            "classifier": "class-balanced HistGradientBoostingClassifier",
            "calibration": calibration,
        },
        "forward_validation": forward_folds,
        "holdout": {
            "model": {
                "regression": regression_metrics(
                    y_reg,
                    regression["point"],
                    regression["q10"],
                    regression["q50"],
                    regression["q90"],
                ),
                "classifier": classification_metrics(
                    y_cls, probability, threshold
                ),
            },
            "baselines": {
                "persistence": regression_metrics(
                    y_reg, holdout["apparent_max_f"].to_numpy(dtype=float)
                ),
                "climatology_regression": regression_metrics(
                    y_reg, climatology_point
                ),
                "climatology_classifier": classification_metrics(
                    y_cls, climatology_probability, 0.5
                ),
            },
            "slices": slice_metrics(
                holdout,
                regression["point"],
                regression["q10"],
                regression["q50"],
                regression["q90"],
                probability,
                threshold,
            ),
        },
        "artifacts": {
            "model_bundle": {
                "path": MODEL_PATH.relative_to(BASE_DIR).as_posix(),
                "sha256": sha256_file(MODEL_PATH),
                "bytes": MODEL_PATH.stat().st_size,
            },
            "holdout_predictions": {
                "path": PREDICTIONS_PATH.relative_to(BASE_DIR).as_posix(),
                "sha256": sha256_file(PREDICTIONS_PATH),
                "bytes": PREDICTIONS_PATH.stat().st_size,
            },
        },
        "limitations": [
            (
                "The NWS Heat Index describes shade with light wind; direct "
                "sun can make conditions feel up to about 15 F hotter."
            ),
            (
                "The Rothfusz regression is not extrapolated below its official "
                "warm-humid trigger; apparent temperature equals air temperature "
                "there."
            ),
            (
                "Airport station observations do not resolve neighborhood-scale "
                "urban heat, indoor exposure, health outcomes, or personal risk."
            ),
            (
                "This is a research forecast trained on May-September observations "
                "and should not replace official NWS alerts or forecasts."
            ),
        ],
        "references": {
            "nws_heat_index": "https://www.weather.gov/tbw/heatindex",
            "noaa_data_terms": "https://sos.noaa.gov/copyright/",
        },
    }
    artifact = clean_json(artifact)
    with EVALUATION_PATH.open("w", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(
        f"Holdout MAE={artifact['holdout']['model']['regression']['mae_f']:.3f} F; "
        f"PR-AUC={artifact['holdout']['model']['classifier']['average_precision']:.3f}; "
        f"Brier={artifact['holdout']['model']['classifier']['brier_score']:.4f}"
    )
    print(f"Wrote {EVALUATION_PATH}")
    return artifact


def parse_years(specification: str) -> list[int]:
    if ":" in specification:
        start, end = (int(part) for part in specification.split(":", maxsplit=1))
        if start > end:
            raise ValueError("Year range start must not exceed end")
        return list(range(start, end + 1))
    return [int(item) for item in specification.split(",")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("fetch", "build", "train", "all"),
        default="all",
    )
    parser.add_argument("--years", default="2015:2025")
    args = parser.parse_args()
    years = parse_years(args.years)

    if args.command in {"fetch", "all"}:
        fetch_all(years)
    if args.command in {"build", "all"}:
        frame, features = build_dataset(years)
    elif args.command == "train":
        frame, features = read_processed()
    else:
        frame = pd.DataFrame()
        features = []
    if args.command in {"train", "all"}:
        train_and_evaluate(frame, features)


if __name__ == "__main__":
    main()
