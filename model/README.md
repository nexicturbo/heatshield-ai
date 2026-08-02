# HeatShield environmental model pipeline

This directory contains a reproducible, environment-only Chicago heat
forecasting pipeline. It predicts each airport station's next-local-day maximum
apparent temperature and the probability that the maximum reaches at least
95 F. It does not predict illness, hospitalization, mortality, or demographic
outcomes.

## Reproduce

Use Python 3.12 and install the pinned dependencies into an isolated
environment:

    py -3.12 -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python -m unittest discover -s tests -v
    .venv\Scripts\python heatshield_pipeline.py all

The all command fetches May 1 through September 30 for 2015-2025 from
NOAA/NCEI Global Hourly for O'Hare (72530094846) and Midway
(72534014819). Each annual response is independently limited to 100 MiB and
stored under a content-addressed filename. data/raw/manifest.json records the
exact URL, UTC retrieval time, byte count, row count, response metadata, and
SHA-256. Existing provenance entries and content-addressed raw files are never
overwritten by a changed upstream response.

Generated outputs:

- data/processed/daily-supervised.csv: auditable station-day features and
  next-day targets.
- artifacts/heatshield-model.joblib: compact fitted preprocessing,
  regression, quantile, classifier, and calibration bundle.
- artifacts/heatshield-model-evaluation.json: source provenance, temporal
  splits, forward validation, untouched 2024-2025 holdout metrics, baselines,
  uncertainty coverage, and station/season slices.
- artifacts/holdout-predictions.csv: row-level holdout predictions for
  independent metric checks.

The script also supports fetch, build, and train as separate commands.
Re-running fetch verifies cached files against the manifest before reuse.

## Data quality and feature timing

The encoded Global Hourly fields are decoded as follows:

- TMP and DEW: signed tenths of a degree Celsius followed by a quality code;
  +9999 is missing.
- WND: wind speed is the fourth comma-delimited element in tenths of metres
  per second; 9999 is missing.
- ISD quality codes 0, 1, 4, and 5 are retained. Suspect, erroneous, and
  missing codes 2, 3, 6, 7, and 9 are rejected.

Duplicate aviation and synoptic reports are reduced to one robust median
observation per station and local clock hour. A station-day must have at least
12 valid apparent-temperature hours. Features contain current-day summaries,
one- to three-day lags, three- and seven-day trailing means, target-day
seasonality, and a station indicator. A row formed at the end of day D targets
day D+1 only; nonconsecutive pairs are discarded.

Model development uses target years through 2023. Target years 2024-2025 are
an untouched final holdout. Expanding-window validation tests 2019, 2020,
2021, 2022, and 2023 in turn. The report compares the model with persistence
and station/day-of-year climatology. Quantile models provide a central 80%
interval; the event classifier is class-balanced and Platt-calibrated using
forward out-of-fold predictions.

## Apparent-temperature definition and limitations

Relative humidity is derived from air temperature and dew point with the
Magnus formula. The implementation follows the official NWS Heat Index
procedure: it checks the simple formula, applies the Rothfusz regression only
when the warm-humid trigger reaches 80 F, and includes the official low- and
high-humidity adjustments. Below that trigger, this application uses air
temperature as apparent temperature rather than extrapolating the regression.

Heat Index describes shade with light wind. The NWS notes that direct sunshine
can make conditions feel up to roughly 15 F hotter. Airport stations cannot
resolve neighborhood-scale urban heat, indoor exposure, individual risk, or
health outcomes. This research model is limited to May-September and does not
replace official NWS forecasts, watches, warnings, or public-health guidance.

Primary references:

- NOAA/NCEI Access Data Service API:
  https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation
- NWS Heat Index equation and limitations:
  https://www.weather.gov/tbw/heatindex
- NOAA data-use statement: https://sos.noaa.gov/copyright/
