# HeatShield AI

**Know the heat. Find a listed cooling resource. Make a plan.**

HeatShield AI is a transparent Chicago heat-readiness and cooling-access
decision aid. It puts three different kinds of evidence next to one another
without collapsing them into a misleading personal-risk score:

1. official National Weather Service forecasts and alerts;
2. evaluation evidence for an experimental, uncertainty-aware model trained to
   estimate next-day maximum apparent temperature from historical airport
   weather; and
3. neighborhood context and access to City-listed cooling resources.

The project was created for the ML Empowerment Build Challenge 2.0. It is not a
medical device, does not diagnose heat illness, and never claims that a listed
facility is currently open.

## The problem

A weather alert can say that a city will be hot, but people still need to
distinguish current official information from experimental evidence, see where
cooling resources are listed, and decide what to verify before leaving.

In the committed access analysis, 83.75% of an estimated 2.65 million Chicago
residents are within one kilometre straight-line of a City-listed cooling
resource. That leaves about 430,000 outside the radius under the analysis's
uniform-within-tract assumption, while no directory record proves that a site
is activated or open.

HeatShield turns public data into an auditable plan while preserving the
distinction between an official forecast, an experimental model, static
neighborhood context, and an unverified facility listing.

## Product experience

- A calm, accessible first screen explains exactly what the tool can and cannot
  do.
- Chicago's Austin Community Area 25 anchors the first demonstration, with
  Humboldt Park and North Lawndale as audited comparisons. Planning-score
  fixtures are explicitly separated from live NWS values.
- Forecast, model-evaluation, neighborhood-context, and cooling-access evidence
  appear as separate cards.
- Each evidence lane identifies its source, freshness or check time, status, and
  relevant limitations.
- A semantic facility table remains usable without maps, JavaScript tiles, or
  precise location access.
- Planning factors adjust only the transparent fictional score and its planning
  guidance. They never alter live NWS or model-evaluation data.
- English and Spanish critical guidance is available without an account.

## Technical architecture

```text
NOAA Global Hourly ──► quality-aware feature pipeline ──► temporal evaluation
                                  │                              │
                                  └──► offline model artifact    └──► model-evaluation card

NWS forecast + alerts ─────────────────────────────────────► official evidence card

CDC/ATSDR SVI ─┐
Census geometry ├──► transparent coverage analysis ───► access + context cards
Chicago centers ┘

Next.js / TypeScript ──► accessible web interface ─────► deployable demo
```

The environmental target is next-day maximum apparent temperature across
O'Hare and Midway, with a separately calibrated indicator for whether apparent
temperature reaches 95°F. Demographic variables are excluded from that model.
They are used only for area-level context and to audit whether access to listed
resources differs across SVI and selected context-variable quartiles.

## Trust boundaries

- **Official evidence first.** The NWS lane is the first evidence card, and no
  derived value is presented as an official forecast.
- **No personal medical prediction.** The model estimates environmental heat,
  not illness, hospitalization, mortality, or individual danger.
- **No opaque personal-risk score.** The adjustable planning-friction score
  shows its fixed-factor contributions and the net adjustment from four visible
  choices. It never uses demographic or medical inputs. Forecast, uncertainty,
  community context, and access stay separately inspectable.
- **No “open now” inference.** City records contain published or usual hours,
  not guaranteed live activation. HeatShield tells users to call 311 or the
  listed facility before traveling.
- **Fail visibly.** Missing, malformed, or unreachable NWS inputs produce an
  explicit unavailable state rather than a fabricated live value.
- **No account or location history.** Neighborhood and planning selections stay
  on the device.

## Data

The committed provenance and derived artifacts document:

- 287 City of Chicago cooling-resource records, each with a valid point;
- 1,331 Cook County 2022 CDC/ATSDR SVI tract records;
- the warm-season NOAA/NCEI hourly observations from O'Hare and Midway used to
  train and evaluate the model; and
- official NWS point forecasts and alerts at runtime with a conspicuous
  structured unavailable state when the source cannot be reached.

Both data pipelines cap individual downloads at 100 MiB. Their committed
manifests record request URLs, retrieval times, byte sizes, SHA-256 hashes, and
available HTTP metadata; structured sources add schema, row-count, and
validation evidence where applicable. See [DATA_SOURCES.md](DATA_SOURCES.md).

## Evaluation

The project uses blocked, forward-in-time validation rather than a random row
split. The untouched 2024–2025 holdout contains 536 station-days. The model
achieved 5.447°F MAE versus 5.841°F for persistence and 7.275°F for
climatology. The ≥95°F classifier achieved 0.428 PR-AUC versus 0.174 for
climatology and a 0.0870 Brier score versus 0.1022. Its central 80% interval
covered 73.7% of outcomes with a mean width of 15.48°F, a visible
under-coverage limitation. The committed evaluation artifact also reports:

- MAE and RMSE for apparent temperature;
- P10/P50/P90 pinball loss and empirical interval coverage;
- precision, recall, PR-AUC, Brier score, and 10-bin expected calibration error
  for the 95°F exceedance indicator;
- persistence and seasonal-climatology baselines;
- airport and early/mid/late-summer slices; and
- cooling-resource coverage gaps across SVI, no-vehicle, limited-English,
  disability, and older-adult quartiles.

Race and ethnicity fields are retained only in the tract-level audit artifact;
they are not prediction features, planning-score inputs, or variables in the
committed quartile-disparity summary. Numeric performance claims are rendered
only from the versioned evaluation artifact generated by the pipeline.

The committed audit files include the [model evaluation
JSON](model/artifacts/heatshield-model-evaluation.json), [row-level holdout
predictions](model/artifacts/holdout-predictions.csv), [geospatial validation
report](public/data/validation_report.json), and [access-disparity
analysis](public/data/disparities.json). See [MODEL_CARD.md](MODEL_CARD.md) for
the model's intended use and limits.

## Native Arm64 optimization

HeatShield's five-model scikit-learn bundle also has a parity-safe ONNX Runtime
path for Arm64 cloud inference. The exporter preserves fitted preprocessing,
calibration, quantile ordering, the final decision threshold, and
`HistGradientBoosting` branch behavior when float64 split thresholds must be
serialized as float32 ONNX attributes.

The controlled [native Arm64 evidence
run](https://github.com/nexicturbo/heatshield-ai/actions/runs/30748183130)
measured a **2.539x median batch-256 latency speedup** over the original joblib
runtime: 0.012330439 seconds versus 0.004855972 seconds. Exact parity passed on
8,192 branch-coverage rows with zero classification mismatches, and the
committed workflow permits the claim only when the native architecture,
locked tolerances, identical fixture and runner, controlled thread policy, and
1.20x minimum gate all pass.

See [model/arm_optimization/README.md](model/arm_optimization/README.md) for the
reproduction commands, evidence boundary, and machine-readable artifacts.

## Local development

Prerequisite: Node.js 22.13 or newer.

```powershell
npm ci
npm run dev
```

Build and verify:

```powershell
npm run build
npm test
npm run lint
```

The public demo requires no secrets. The NWS runtime route uses a descriptive
User-Agent, validates response shape, caches briefly, and returns a structured
unavailable state on failure.

## Accessibility

- semantic landmarks and a table-first resource experience;
- keyboard-operable controls with visible focus;
- text and pattern in addition to color for every status;
- high-contrast palette and clearly labeled controls;
- responsive layouts and reduced-motion styles;
- concise English and Spanish critical guidance; and
- print-friendly emergency and cooling-resource plans.

## Limitations

- Two airport stations cannot capture block-level urban heat-island variation.
- Forecasts change and can be wrong.
- SVI represents 2018–2022 ACS context, includes margins of error, and is not a
  personal score.
- Listed cooling-resource hours and activation can change. Confirm through 311.
- Straight-line distance does not certify a safe, accessible, or available
  route.
- The prototype has not been clinically validated and must not be used for
  diagnosis or emergency triage.

Confusion, fainting, or loss of consciousness during heat can be an emergency.
Call 911 now.

## Attribution

HeatShield uses public information from NOAA/NCEI, the National Weather
Service, CDC/ATSDR, the U.S. Census Bureau, and the City of Chicago. The project
is independent and does not imply endorsement by any source agency. Derived
analysis and any errors are the project's responsibility.

## License

The project's original source code and documentation are available under the
[MIT License](LICENSE). Source records and committed artifacts that reproduce
or derive from source data remain subject to their respective terms and
attribution requirements. See [DATA_SOURCES.md](DATA_SOURCES.md) for the exact
license boundary, source-specific notices, and the City of Chicago modified-data
disclaimer.
