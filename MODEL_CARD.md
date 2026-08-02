# HeatShield environmental model card

## Intended use

Estimate next-day maximum apparent temperature at Chicago O'Hare and Midway as
one research input to preparedness planning. Official NWS forecasts and alerts
remain the authoritative operational source.

## Out-of-scope uses

- individual illness, mortality, hospitalization, or emergency prediction;
- diagnosis, treatment, or medical triage;
- block-level temperature or urban-heat-island estimation;
- facility availability, capacity, accessibility, or safe-route certification;
- prioritizing people or neighborhoods by race, ethnicity, disability, age, or
  another protected or sensitive characteristic.

## Targets

Primary: each airport station's next-local-day maximum apparent temperature.

Secondary: whether next-day maximum apparent temperature reaches 95°F. This is
an environmental threshold indicator, not a probability of harm.

## Inputs

- current-day temperature, dew point, humidity, apparent-temperature, wind,
  duration, observation-count, and coverage summaries;
- one- to three-day lags and three- and seven-day trailing means;
- target-day sine/cosine seasonality; and
- station identity.

No demographic variable is a model input.

## Models

- persistence and seasonal-climatology baselines;
- a histogram gradient-boosted point regressor;
- P10/P50/P90 gradient-boosted quantile regressors; and
- a calibrated gradient-boosted classifier for the 95°F indicator.

The pipeline uses rolling-origin validation and holds out 2024–2025. It does not
use a random row split.

## Reported metrics

- MAE, RMSE, P10/P50/P90 pinball loss, and empirical interval coverage;
- precision, recall, PR-AUC, Brier score, and 10-bin expected calibration error;
- comparison with persistence and seasonal climatology; and
- slices by station and early/mid/late summer.

The untouched 2024–2025 holdout contains 536 station-days:

- point MAE: 5.447°F versus 5.841°F persistence and 7.275°F climatology;
- point RMSE: 7.080°F;
- ≥95°F PR-AUC: 0.428 versus 0.174 climatology;
- ≥95°F Brier score: 0.0870 versus 0.1022 climatology; and
- central 80% interval coverage: 73.7%, mean width 15.48°F.

The interval under-covers its nominal 80% target, so uncertainty bands should
not be interpreted as calibrated guarantees. Exact values live in the
[evaluation JSON](model/artifacts/heatshield-model-evaluation.json), and the
[row-level predictions](model/artifacts/holdout-predictions.csv) are committed
alongside it.

## Abstention

The public NWS lane returns unavailable when required fields are missing or the
source cannot be reached. The experimental model is not silently substituted
for official data.

## Known limitations

- Airport observations are not neighborhood measurements.
- Historical weather and future forecasts can differ structurally.
- Apparent-temperature formulas have domain limitations.
- A calibrated historical threshold does not make the system clinically valid.
- The 73.7% empirical coverage falls short of the nominal 80% interval.
- Climate change can reduce the relevance of older seasons.

## Versioning

The evaluation artifact records source and input hashes, feature schema,
temporal splits, model classes and calibration settings, evaluation metrics,
and SHA-256 values for the generated model and prediction artifacts. The
committed evaluation JSON's SHA-256 is
`6a492c21a2feb0e3aebd8388f28412846b3d6afb5f238bce9eae5cb9d64c00cd`.
