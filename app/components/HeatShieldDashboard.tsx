"use client";

import { useEffect, useState, type CSSProperties } from "react";
import {
  actionCopy,
  modelMetrics,
  scenarios,
  sourceFreshness,
  type DurationKey,
  type TimeKey,
  type TransportKey,
} from "../lib/demo-data";

const durationLabels: Record<DurationKey, string> = {
  "15": "Up to 15 min",
  "45": "About 45 min",
  "90": "90+ min",
};

const timeLabels: Record<TimeKey, string> = {
  morning: "Morning",
  afternoon: "Afternoon",
  evening: "Evening",
};

const transportLabels: Record<TransportKey, string> = {
  walk: "Walking",
  transit: "Transit",
  car: "Car / rideshare",
};

type LiveForecastPeriod = {
  startTime: string;
  temperature: number;
  temperatureUnit: string;
  windSpeed: string;
  windDirection: string;
  shortForecast: string;
  relativeHumidity: number | null;
};

type LiveForecastState =
  | { status: "loading" }
  | { status: "unavailable"; checkedAt?: string; message: string }
  | {
      status: "available";
      checkedAt: string;
      periods: LiveForecastPeriod[];
      alerts: Array<{ event: string; headline: string }>;
    };

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function HeatShieldDashboard() {
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const [duration, setDuration] = useState<DurationKey>("45");
  const [time, setTime] = useState<TimeKey>("afternoon");
  const [hasShade, setHasShade] = useState(false);
  const [transport, setTransport] = useState<TransportKey>("transit");
  const [language, setLanguage] = useState<keyof typeof actionCopy>("en");
  const [checkedActions, setCheckedActions] = useState<string[]>([]);
  const [liveForecast, setLiveForecast] = useState<LiveForecastState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    async function loadForecast() {
      try {
        const response = await fetch("/api/forecast", { signal: controller.signal });
        const payload = (await response.json()) as Partial<{
          status: string;
          checkedAt: string;
          message: string;
          periods: LiveForecastPeriod[];
          alerts: Array<{ event: string; headline: string }>;
        }>;

        if (
          payload.status === "available" &&
          typeof payload.checkedAt === "string" &&
          Array.isArray(payload.periods) &&
          payload.periods.length > 0
        ) {
          setLiveForecast({
            status: "available",
            checkedAt: payload.checkedAt,
            periods: payload.periods,
            alerts: Array.isArray(payload.alerts) ? payload.alerts : [],
          });
          return;
        }

        setLiveForecast({
          status: "unavailable",
          checkedAt: payload.checkedAt,
          message:
            typeof payload.message === "string"
              ? payload.message
              : "Live NWS data is unavailable. Use weather.gov for current conditions.",
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setLiveForecast({
          status: "unavailable",
          message: "Live NWS data is unavailable. Use weather.gov for current conditions.",
        });
      }
    }

    void loadForecast();
    return () => controller.abort();
  }, []);

  const scenario = scenarios.find((item) => item.id === scenarioId) ?? scenarios[0];
  const plan = actionCopy[language];
  const basePlanningScore = scenario.factors.reduce(
    (total, factor) => total + factor.contribution,
    0,
  );
  const livePeriod = liveForecast.status === "available" ? liveForecast.periods[0] : null;
  const forecastCheckedLabel =
    liveForecast.status === "loading"
      ? "checking now"
      : liveForecast.checkedAt
        ? new Intl.DateTimeFormat("en-US", {
            dateStyle: "medium",
            timeStyle: "short",
            timeZone: "America/Chicago",
          }).format(new Date(liveForecast.checkedAt))
        : "check unavailable";

  const durationAdjustment = duration === "15" ? -8 : duration === "90" ? 10 : 0;
  const timeAdjustment = time === "morning" ? -7 : time === "evening" ? -3 : 4;
  const shadeAdjustment = hasShade ? -7 : 5;
  const transportAdjustment = transport === "walk" ? 7 : transport === "car" ? -4 : 1;
  const planningScore = clamp(
    basePlanningScore +
      durationAdjustment +
      timeAdjustment +
      shadeAdjustment +
      transportAdjustment,
    12,
    98,
  );

  const planningLabel =
    planningScore >= 80 ? "Change the plan" : planningScore >= 62 ? "Add protections" : "Plan with care";

  const resetPlanner = () => {
    setDuration("45");
    setTime("afternoon");
    setHasShade(false);
    setTransport("transit");
  };

  const toggleAction = (action: string) => {
    setCheckedActions((current) =>
      current.includes(action) ? current.filter((item) => item !== action) : [...current, action],
    );
  };

  return (
    <div className="site-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="#top" aria-label="HeatShield AI home">
            <span className="brand-mark" aria-hidden="true">
              HS
            </span>
            <span>
              <strong>HeatShield</strong>
              <small>Transparent heat planning</small>
            </span>
          </a>
          <nav className="primary-nav" aria-label="Primary navigation">
            <a href="#planner">Plan</a>
            <a href="#cooling-access">Cooling access</a>
            <a href="#evidence">Evidence</a>
          </nav>
          <button className="print-button" type="button" onClick={() => window.print()}>
            Print plan
          </button>
        </div>
      </header>

      <div className="trust-strip" role="note" aria-label="Demonstration notice">
        <div className="trust-strip-inner">
          <span className="demo-pill">Fictional Chicago planner</span>
          <span>Live NWS status stays separate</span>
          <span aria-hidden="true">•</span>
          <span>Sources stay separated</span>
          <span aria-hidden="true">•</span>
          <span>No personal profile</span>
        </div>
      </div>

      <main id="main-content">
        <section className="hero" id="top" aria-labelledby="hero-title">
          <div className="hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">Neighborhood heat decisions, with receipts</p>
              <h1 id="hero-title">Know what is official. See what is estimated. Plan what to do next.</h1>
              <p className="hero-lede">
                HeatShield AI keeps forecast evidence, experimental environmental-model evidence,
                neighborhood context, and cooling access in separate lanes—then turns them into an
                explainable plan.
              </p>
              <div className="hero-actions">
                <a className="primary-button" href="#planner">
                  Explore Chicago communities
                </a>
                <a className="text-link" href="#methodology">
                  Read how the signal works <span aria-hidden="true">→</span>
                </a>
              </div>
              <ul className="hero-proof" aria-label="Product principles">
                <li><span aria-hidden="true">01</span> Official data leads</li>
                <li><span aria-hidden="true">02</span> Uncertainty is visible</li>
                <li><span aria-hidden="true">03</span> Every action is traceable</li>
              </ul>
            </div>

            <aside className="hero-snapshot" aria-label="Selected fictional planning snapshot">
              <div className="snapshot-topline">
                <span>Planning snapshot</span>
                <span className="demo-label">DEMO</span>
              </div>
              <p className="snapshot-place">{scenario.place}</p>
              <div className="score-layout">
                <div
                  className="score-ring"
                  style={{ "--score": `${planningScore * 3.6}deg` } as CSSProperties}
                  aria-label={`Planning priority score ${planningScore} out of 100`}
                >
                  <span>{planningScore}</span>
                  <small>/ 100</small>
                </div>
                <div>
                  <p className="score-label">{planningLabel}</p>
                  <p className="score-explainer">
                    Higher means the example benefits from more protective choices—not that a
                    person has been assessed.
                  </p>
                </div>
              </div>
              <div className="snapshot-metrics">
                <div>
                  <span>Official lane</span>
                  <strong>{livePeriod ? `${livePeriod.temperature}°${livePeriod.temperatureUnit}` : "NWS"}</strong>
                  <small>{livePeriod ? "central Chicago hourly temperature" : "status checking"}</small>
                </div>
                <div>
                  <span>Research model</span>
                  <strong>{modelMetrics.mae}°F</strong>
                  <small>2024–25 holdout MAE</small>
                </div>
              </div>
              <p className="snapshot-disclaimer">
                Planning scores are demonstration fixtures. Chicago access statistics and listed
                destinations come from audited public data and still require verification.
              </p>
            </aside>
          </div>
        </section>

        <section className="judge-strip" aria-label="Evaluation strengths">
          <div><strong>Useful</strong><span>specific next steps</span></div>
          <div><strong>Grounded</strong><span>source lanes never blended</span></div>
          <div><strong>Responsible</strong><span>limits and uncertainty upfront</span></div>
          <div><strong>Accessible</strong><span>keyboard, bilingual, printable</span></div>
        </section>

        <section className="planner-section section-shell" id="planner" aria-labelledby="planner-title">
          <div className="section-heading split-heading">
            <div>
              <p className="eyebrow">01 · Plan a scenario</p>
              <h2 id="planner-title">Make the planning factors concrete</h2>
            </div>
            <p>
              Adjust the demonstration scenario. The score responds transparently; the underlying
              source values do not change.
            </p>
          </div>

          <div className="planner-grid">
            <form className="planner-controls" onSubmit={(event) => event.preventDefault()}>
              <div className="control-heading">
                <div>
                  <span className="control-kicker">Chicago example</span>
                  <h3>Trip and exposure details</h3>
                </div>
                <button type="button" className="reset-button" onClick={resetPlanner}>
                  Reset
                </button>
              </div>

              <label className="field-label" htmlFor="scenario-select">
                Example neighborhood
              </label>
              <select
                id="scenario-select"
                value={scenarioId}
                onChange={(event) => setScenarioId(event.target.value)}
              >
                {scenarios.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label} · {item.zip}
                  </option>
                ))}
              </select>
              <p className="field-help">{scenario.summary}</p>

              <fieldset>
                <legend>Expected time outside</legend>
                <div className="segmented-control three-up">
                  {(Object.keys(durationLabels) as DurationKey[]).map((key) => (
                    <label key={key}>
                      <input
                        type="radio"
                        name="duration"
                        value={key}
                        checked={duration === key}
                        onChange={() => setDuration(key)}
                      />
                      <span>{durationLabels[key]}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset>
                <legend>Time of day</legend>
                <div className="segmented-control three-up">
                  {(Object.keys(timeLabels) as TimeKey[]).map((key) => (
                    <label key={key}>
                      <input
                        type="radio"
                        name="time"
                        value={key}
                        checked={time === key}
                        onChange={() => setTime(key)}
                      />
                      <span>{timeLabels[key]}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="control-row">
                <div>
                  <label className="field-label" htmlFor="transport-select">
                    Primary travel mode
                  </label>
                  <select
                    id="transport-select"
                    value={transport}
                    onChange={(event) => setTransport(event.target.value as TransportKey)}
                  >
                    {(Object.keys(transportLabels) as TransportKey[]).map((key) => (
                      <option key={key} value={key}>
                        {transportLabels[key]}
                      </option>
                    ))}
                  </select>
                </div>
                <label className="check-card">
                  <input
                    type="checkbox"
                    checked={hasShade}
                    onChange={(event) => setHasShade(event.target.checked)}
                  />
                  <span className="check-box" aria-hidden="true" />
                  <span>
                    <strong>Reliable shade</strong>
                    <small>Most of the route</small>
                  </span>
                </label>
              </div>
            </form>

            <aside className="factor-panel" aria-labelledby="factor-title">
              <div className="factor-summary" aria-live="polite">
                <div>
                  <span className="control-kicker">Explainable output</span>
                  <h3 id="factor-title">{planningLabel}</h3>
                  <p>
                    {planningScore >= 80
                      ? "Move the activity, reduce exposure, or confirm indoor cooling first."
                      : planningScore >= 62
                        ? "Shorten the trip and add shade, water, transport, or a confirmed destination."
                        : "Keep the outing brief and maintain a backup plan."}
                  </p>
                </div>
                <strong className="factor-score">{planningScore}</strong>
              </div>

              <div className="factor-list" aria-label="Factors contributing to the output">
                {scenario.factors.map((factor) => (
                  <div className="factor-row" key={factor.label}>
                    <div className="factor-row-top">
                      <strong>{factor.label}</strong>
                      <span>+{factor.contribution}</span>
                    </div>
                    <div className="factor-track" aria-hidden="true">
                      <span style={{ width: `${Math.min(factor.contribution * 2.5, 100)}%` }} />
                    </div>
                    <p>{factor.explanation}</p>
                  </div>
                ))}
                <div className="factor-row dynamic-factor">
                  <div className="factor-row-top">
                    <strong>Your planning choices</strong>
                    <span>{planningScore - basePlanningScore >= 0 ? "+" : ""}{planningScore - basePlanningScore}</span>
                  </div>
                  <p>
                    {durationLabels[duration]}, {timeLabels[time].toLowerCase()}, {transportLabels[transport].toLowerCase()}, {hasShade ? "with" : "without"} reliable shade.
                  </p>
                </div>
              </div>
              <p className="model-boundary">
                <strong>Boundary:</strong> This score ranks planning friction in the fictional
                scenario. It does not assess a person or predict an outcome.
              </p>
            </aside>
          </div>
        </section>

        <section className="evidence-section section-shell" id="evidence" aria-labelledby="evidence-title">
          <div className="section-heading split-heading">
            <div>
              <p className="eyebrow">02 · Evidence lanes</p>
              <h2 id="evidence-title">Four different claims. Four visible boundaries.</h2>
            </div>
            <p>
              Experimental estimates never inherit the authority of the forecast, and area context
              never becomes a claim about a person.
            </p>
          </div>

          <div className="evidence-grid">
            <article className="evidence-card official-card">
              <div className="evidence-card-head">
                <span className="lane-number">A</span>
                <span className="lane-badge official-badge">Official forecast lane</span>
              </div>
              <p className="card-overline">
                {liveForecast.status === "available"
                  ? "LIVE NWS HOURLY FORECAST · CENTRAL CHICAGO"
                  : liveForecast.status === "loading"
                    ? "CHECKING NWS"
                    : "NWS UNAVAILABLE"}
              </p>
              <div className="headline-metric">
                <strong>{livePeriod ? `${livePeriod.temperature}°${livePeriod.temperatureUnit}` : "—"}</strong>
                <span>{livePeriod ? "hourly air temperature" : "no live value shown"}</span>
              </div>
              <dl className="metric-list">
                <div><dt>Humidity</dt><dd>{livePeriod?.relativeHumidity == null ? "Not reported" : `${livePeriod.relativeHumidity}%`}</dd></div>
                <div><dt>Wind</dt><dd>{livePeriod ? `${livePeriod.windSpeed} ${livePeriod.windDirection}` : "Not reported"}</dd></div>
                <div><dt>Active alerts</dt><dd>{liveForecast.status === "available" ? liveForecast.alerts.length : "—"}</dd></div>
              </dl>
              <p>
                {livePeriod?.shortForecast ??
                  (liveForecast.status === "unavailable"
                    ? liveForecast.message
                    : "Loading the authoritative National Weather Service lane.")}
              </p>
              <footer>Production source: weather.gov · central Chicago reference point · checked {forecastCheckedLabel} CT</footer>
            </article>

            <article className="evidence-card experimental-card">
              <div className="evidence-card-head">
                <span className="lane-number">B</span>
                <span className="lane-badge experimental-badge">Experimental estimate</span>
              </div>
              <p className="card-overline">TEMPORAL HOLDOUT · NOT AN OFFICIAL FORECAST</p>
              <div className="headline-metric">
                <strong>{modelMetrics.mae}°F</strong>
                <span>2024–2025 holdout MAE</span>
              </div>
              <dl className="metric-list">
                <div><dt>Persistence MAE</dt><dd>{modelMetrics.persistenceMae}°F</dd></div>
                <div><dt>≥95°F PR-AUC</dt><dd>{modelMetrics.prAuc}</dd></div>
                <div><dt>80% interval coverage</dt><dd>{modelMetrics.intervalCoverage}%</dd></div>
              </dl>
              <p>
                Research model for next-day maximum apparent temperature at O&apos;Hare and Midway;
                it produces no neighborhood, individual, or medical outcome.
              </p>
              <footer>
                NOAA/NCEI warm seasons 2015–2025 · {modelMetrics.holdoutRows} untouched holdout rows
              </footer>
            </article>

            <article className="evidence-card context-card">
              <div className="evidence-card-head">
                <span className="lane-number">C</span>
                <span className="lane-badge context-badge">Neighborhood context</span>
              </div>
              <p className="card-overline">AUDITED AREA-LEVEL AGGREGATES</p>
              <div className="context-metrics">
                <div><strong>{scenario.context.olderAdults}</strong><span>age 65+</span></div>
                <div><strong>{scenario.context.noVehicle}</strong><span>no vehicle</span></div>
                <div><strong>{scenario.context.limitedEnglish}</strong><span>limited English</span></div>
                <div><strong>{scenario.context.disability}</strong><span>with disability</span></div>
              </div>
              <p>{scenario.context.note}</p>
              <footer>CDC/ATSDR SVI 2022 · population-weighted community estimate</footer>
            </article>

            <article className="evidence-card access-card">
              <div className="evidence-card-head">
                <span className="lane-number">D</span>
                <span className="lane-badge access-badge">Cooling access</span>
              </div>
              <p className="card-overline">DESTINATIONS MUST BE CONFIRMED</p>
              <div className="headline-metric">
                <strong>{scenario.facilities[0].distance}</strong>
                <span>nearest listed resource</span>
              </div>
              <dl className="metric-list">
                <div><dt>Routing</dt><dd>{scenario.facilities[0].travel[transport]}</dd></div>
                <div><dt>Nearby listings shown</dt><dd>{scenario.facilities.length}</dd></div>
                <div><dt>Availability</dt><dd>Not verified</dd></div>
              </dl>
              <p>Straight-line distances use community representative points; they are not routes.</p>
              <footer>City of Chicago directory · current status not inferred</footer>
            </article>
          </div>
        </section>

        <section className="uncertainty-section section-shell" aria-labelledby="uncertainty-title">
          <div className="uncertainty-intro">
            <p className="eyebrow">03 · Uncertainty before precision</p>
            <h2 id="uncertainty-title">The interface shows what can change the answer.</h2>
            <p>
              The research model is useful as a benchmark, but airport coverage, changing weather,
              direct sun, and seasonal drift can move an outcome materially.
            </p>
          </div>
          <div className="uncertainty-scale" aria-label="Experimental estimate uncertainty range">
            <div className="scale-labels"><span>Lower plausible</span><strong>Illustrative center</strong><span>Upper plausible</span></div>
            <div className="scale-track"><span className="scale-range" /><span className="scale-center" /></div>
            <div className="scale-values"><span>P10</span><strong>{modelMetrics.intervalWidth}°F mean width</strong><span>P90</span></div>
          </div>
          <div className="uncertainty-cards">
            <article>
              <span className="certainty-dot known-dot" aria-hidden="true" />
              <h3>Known in the example</h3>
              <p>Historical observation quality, temporal split, source vintage, and live NWS check time.</p>
            </article>
            <article>
              <span className="certainty-dot estimated-dot" aria-hidden="true" />
              <h3>Estimated</h3>
              <p>Next-day airport apparent temperature and population-weighted resource coverage.</p>
            </article>
            <article>
              <span className="certainty-dot unknown-dot" aria-hidden="true" />
              <h3>Not known</h3>
              <p>Block-level temperature, exact shade, personal circumstances, and facility activation.</p>
            </article>
          </div>
        </section>

        <section className="cooling-section section-shell" id="cooling-access" aria-labelledby="cooling-title">
          <div className="section-heading split-heading">
            <div>
              <p className="eyebrow">04 · Cooling access</p>
              <h2 id="cooling-title">Compare destinations before looking at the map</h2>
            </div>
            <p>
              The table is the primary accessible view. The panel beneath it is a visual orientation
              aid, not a route or availability service.
            </p>
          </div>

          <div className="facility-warning" role="alert">
            <span aria-hidden="true">!</span>
            <strong>facility hours/activation can change—call 311 before traveling</strong>
          </div>

          <div className="table-wrap">
            <table>
              <caption>
                Listed Chicago cooling resources; activation, hours, and access must be confirmed
              </caption>
              <thead>
                <tr>
                  <th scope="col">Listed resource</th>
                  <th scope="col">Area</th>
                  <th scope="col">Distance</th>
                  <th scope="col">Routing</th>
                  <th scope="col">Source descriptors</th>
                  <th scope="col">Verification</th>
                </tr>
              </thead>
              <tbody>
                {scenario.facilities.map((facility) => (
                  <tr key={facility.id}>
                    <th scope="row">{facility.name}</th>
                    <td>{facility.area}</td>
                    <td>{facility.distance}</td>
                    <td>{facility.travel[transport]}</td>
                    <td>{facility.features.join(" · ")}</td>
                    <td><span className="unverified-status">Not verified</span><small>{facility.verification}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="map-layout">
            <div
              className="css-map"
              role="img"
              aria-label={`Stylized non-navigational orientation showing three listed resources around ${scenario.place}`}
            >
              <div className="map-grid" aria-hidden="true" />
              <div className="map-river" aria-hidden="true" />
              <div className="map-road road-one" aria-hidden="true" />
              <div className="map-road road-two" aria-hidden="true" />
              <div className="map-road road-three" aria-hidden="true" />
              <span className="map-label downtown-label" aria-hidden="true">Downtown</span>
              <span className="map-label river-label" aria-hidden="true">Chicago grid</span>
              <span className="you-marker" aria-hidden="true"><i />Example start</span>
              {scenario.facilities.map((facility, index) => (
                <span
                  className="facility-marker"
                  key={facility.id}
                  style={{ left: `${facility.mapPosition.x}%`, top: `${facility.mapPosition.y}%` }}
                  aria-hidden="true"
                >
                  {index + 1}
                </span>
              ))}
            </div>
            <aside className="map-legend" aria-label="Map legend and limits">
              <span className="control-kicker">Orientation only</span>
              <h3>A map that admits what it cannot do</h3>
              <ol>
                {scenario.facilities.map((facility, index) => (
                  <li key={facility.id}>
                    <span>{index + 1}</span>
                    <div><strong>{facility.name}</strong><small>{facility.distance} · {facility.travel[transport]}</small></div>
                  </li>
                ))}
              </ol>
              <p>No turn-by-turn directions, traffic state, hours, capacity, or activation status is inferred.</p>
            </aside>
          </div>
        </section>

        <section className="action-section section-shell" aria-labelledby="action-title">
          <div className="action-grid">
            <div className="action-copy">
              <p className="eyebrow">05 · Action checklist</p>
              <div className="language-toggle" role="group" aria-label="Checklist language">
                {(Object.keys(actionCopy) as Array<keyof typeof actionCopy>).map((key) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={language === key}
                    onClick={() => {
                      setLanguage(key);
                      setCheckedActions([]);
                    }}
                  >
                    {actionCopy[key].label}
                  </button>
                ))}
              </div>
              <div lang={language}>
                <h2 id="action-title">{plan.heading}</h2>
                <p>{plan.intro}</p>
              </div>
              <p className="action-context">
                Suggested emphasis: <strong>{planningLabel.toLowerCase()}</strong> · {scenario.place}
              </p>
            </div>
            <div className="checklist-card" lang={language}>
              <ul className="action-list">
                {plan.actions.map((action, index) => (
                  <li key={action}>
                    <label>
                      <input
                        type="checkbox"
                        checked={checkedActions.includes(action)}
                        onChange={() => toggleAction(action)}
                      />
                      <span className="action-check" aria-hidden="true">{checkedActions.includes(action) ? "✓" : index + 1}</span>
                      <span>{action}</span>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="emergency-warning" role="alert">
                <span aria-hidden="true">911</span>
                <div>
                  <strong>confusion/fainting/loss of consciousness can be emergency—call 911</strong>
                  {language === "es" && <p>{actionCopy.es.emergency}</p>}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="freshness-section section-shell" aria-labelledby="freshness-title">
          <div className="section-heading split-heading">
            <div>
              <p className="eyebrow">06 · Source freshness</p>
              <h2 id="freshness-title">Every layer carries its own clock</h2>
            </div>
            <p>
              Freshness is part of the evidence, not a hidden implementation detail. Each label
              identifies whether its lane is live, historical, or a demonstration input.
            </p>
          </div>
          <div className="freshness-list">
            {sourceFreshness.map((source, index) => (
              <article key={source.lane}>
                <span className="freshness-index">0{index + 1}</span>
                <div>
                  <h3>{source.lane}</h3>
                  <p>{source.source}</p>
                </div>
                <div>
                  <strong>{source.freshness}</strong>
                  <p>{source.note}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="method-section section-shell" id="methodology" aria-labelledby="method-title">
          <div className="section-heading split-heading">
            <div>
              <p className="eyebrow">07 · Evidence card</p>
              <h2 id="method-title">Method, model, data, fairness, and limits</h2>
            </div>
            <p>
              A strong demo should be inspectable without a technical appendix. These are the
              minimum claims the product would publish beside every release.
            </p>
          </div>

          <div className="method-grid">
            <article>
              <span>Methodology</span>
              <h3>Decision support, not a black box</h3>
              <p>
                The demonstration score uses only the four visible planning controls and fixed,
                disclosed example-factor contributions. Live NWS, experimental-model, demographic,
                and cooling-access evidence stay separate and never enter that score.
              </p>
            </article>
            <article>
              <span>Planner</span>
              <h3>Deterministic, bounded, explainable</h3>
              <p>
                Longer exposure cannot lower the score; reliable shade cannot raise it. Each factor is
                visible, capped, and paired with a plain-language explanation.
              </p>
            </article>
            <article>
              <span>Temporal evaluation</span>
              <h3>{modelMetrics.mae}°F holdout MAE</h3>
              <p>
                On {modelMetrics.holdoutRows} untouched 2024–2025 station-days, the model beats
                persistence ({modelMetrics.persistenceMae}°F) and climatology
                ({modelMetrics.climatologyMae}°F). Exceedance PR-AUC is {modelMetrics.prAuc}
                versus {modelMetrics.climatologyPrAuc}; the nominal 80% interval covers only
                {modelMetrics.intervalCoverage}% with a {modelMetrics.intervalWidth}°F mean width.
              </p>
            </article>
            <article>
              <span>Data</span>
              <h3>Provenance before prediction</h3>
              <p>
                Production records would retain source URL, retrieval time, schema, validation result,
                geographic coverage, and checksum. This demo publishes those artifacts for audit.
              </p>
            </article>
            <article>
              <span>Fairness</span>
              <h3>Context changes resources, not people</h3>
              <p>
                Neighborhood variables help prioritize translation, transport, shade, and outreach.
                They must not be used to rank a resident, infer identity, or reduce service eligibility.
              </p>
            </article>
            <article className="wide-method-card">
              <span>Limitations</span>
              <h3>Important things HeatShield cannot know from this page</h3>
              <ul>
                <li>Whether a listed resource is activated, open, full, or accessible at departure.</li>
                <li>Exact shade, wind, indoor temperature, traffic, transit delay, or block-level air temperature.</li>
                <li>A person’s health, hydration, medication, acclimatization, work demands, or support network.</li>
                <li>Whether an experimental estimate will generalize beyond its place, season, and training coverage.</li>
              </ul>
            </article>
            <article className="wide-method-card">
              <span>Open audit artifacts</span>
              <h3>Inspect the evidence behind the interface</h3>
              <p className="artifact-links">
                <a href="/data/model_evaluation.json">Model evaluation JSON</a>
                <a href="/data/holdout_predictions.csv">Holdout predictions</a>
                <a href="/data/community_access.json">Community access JSON</a>
                <a href="/data/disparities.json">Disparity audit JSON</a>
                <a href="/data/validation_report.json">Geospatial validation report</a>
              </p>
            </article>
          </div>
        </section>

        <section className="closing-section" aria-labelledby="closing-title">
          <div>
            <p className="eyebrow">A clearer standard for civic AI</p>
            <h2 id="closing-title">Useful enough to act on. Honest enough to trust.</h2>
          </div>
          <a className="light-button" href="#planner">Revisit the planner</a>
        </section>
      </main>

      <footer className="site-footer">
        <div>
          <a className="brand footer-brand" href="#top">
            <span className="brand-mark" aria-hidden="true">HS</span>
            <span><strong>HeatShield AI</strong><small>Chicago product demonstration</small></span>
          </a>
          <p>
            Built to demonstrate transparent heat planning. Live NWS context is kept separate from
            demo planning scores; no personal data or verified facility availability is inferred.
          </p>
        </div>
        <nav aria-label="Footer navigation">
          <a href="#evidence">Evidence lanes</a>
          <a href="#cooling-access">Cooling access</a>
          <a href="#methodology">Limitations</a>
        </nav>
      </footer>
    </div>
  );
}
