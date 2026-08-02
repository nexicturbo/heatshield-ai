import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";

const projectRoot = new URL("../", import.meta.url);

async function source(path) {
  return readFile(new URL(path, projectRoot), "utf8");
}

async function collectTextFiles(directoryUrl) {
  const entries = await readdir(directoryUrl, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const child = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directoryUrl);
    if (entry.isDirectory()) {
      files.push(...(await collectTextFiles(child)));
    } else if (/\.(?:css|mjs|ts|tsx)$/i.test(entry.name)) {
      files.push({ path: child.pathname, text: await readFile(child, "utf8") });
    }
  }

  return files;
}

function assertBefore(haystack, first, second, message) {
  const firstIndex = haystack.indexOf(first);
  const secondIndex = haystack.indexOf(second);
  assert.ok(firstIndex >= 0, `Missing first marker: ${first}`);
  assert.ok(secondIndex >= 0, `Missing second marker: ${second}`);
  assert.ok(firstIndex < secondIndex, message);
}

function compact(value) {
  return value.replace(/\s+/g, " ");
}

async function render() {
  const workerUrl = new URL("dist/server/index.js", projectRoot);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("demo planning scores stay distinct from live NWS and audited access data", async () => {
  const [page, dashboard, data] = await Promise.all([
    source("app/page.tsx"),
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
  ]);
  const publicCopy = `${page}\n${dashboard}\n${data}`;

  assert.match(page, /Chicago demonstration/i);
  assert.match(page, /live National Weather Service context/i);
  assert.match(dashboard, /Fictional Chicago planner/i);
  assert.match(dashboard, /Live NWS status stays separate/i);
  assert.match(dashboard, /Planning scores are demonstration fixtures/i);
  assert.match(
    compact(dashboard),
    /Chicago access statistics and listed destinations come from audited public data and still require verification/i,
  );
  assert.match(dashboard, /Availability[\s\S]{0,100}Not verified/i);
  assert.match(data, /City listing[^"\n]*current activation, hours, capacity, and access not verified/i);
  assert.match(data, /demo planner; live NWS data stays separate/i);
  assert.doesNotMatch(data, /Fictional demo record/i);
  assert.doesNotMatch(
    compact(dashboard),
    /These labels describe the fictional demonstration fixtures/i,
    "Live NWS, audited model, context, and facility provenance must not all be described as fictional fixtures.",
  );
  assert.doesNotMatch(publicCopy, /\bcurrent facility (?:availability|status)\b/i);
});

test("Chicago geography stays consistent across UI, metadata, API, and model", async () => {
  const [page, layout, dashboard, data, api, readme, modelCard] = await Promise.all([
    source("app/page.tsx"),
    source("app/layout.tsx"),
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
    source("app/api/forecast/route.ts"),
    source("README.md"),
    source("MODEL_CARD.md"),
  ]);
  const publicProduct = `${page}\n${layout}\n${dashboard}\n${data}`;
  const allClaims = `${publicProduct}\n${api}\n${readme}\n${modelCard}`;

  assert.match(allClaims, /Chicago/i);
  assert.match(
    publicProduct,
    /(?:Austin[\s\S]{0,80}Community Area\s*25|Community Area\s*25[\s\S]{0,80}Austin)/i,
    "The demo must identify Austin as Chicago Community Area 25, not Austin, Texas.",
  );
  assert.match(api, /41\.8781[^\n]*-87\.6298/);
  assert.doesNotMatch(
    publicProduct,
    /\b787\d{2}\b|Colorado River|North Lamar|East Riverside|McKinney Falls|East Austin\b/i,
    "Texas-specific fixtures would conflict with the Chicago data/model/API.",
  );
});

test("official NWS evidence stays authoritative and ahead of derived lanes", async () => {
  const [dashboard, api, readme, modelCard] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/api/forecast/route.ts"),
    source("README.md"),
    source("MODEL_CARD.md"),
  ]);

  assertBefore(
    dashboard,
    'className="evidence-card official-card"',
    'className="evidence-card experimental-card"',
    "The official forecast must be presented before the experimental estimate.",
  );
  assertBefore(
    dashboard,
    'className="evidence-card experimental-card"',
    'className="evidence-card context-card"',
    "The experimental estimate must remain separate from neighborhood context.",
  );
  assertBefore(
    dashboard,
    'className="evidence-card context-card"',
    'className="evidence-card access-card"',
    "Neighborhood context must remain separate from cooling access.",
  );
  assert.match(dashboard, /Experimental estimates never inherit the authority of the forecast/i);
  assert.match(dashboard, /Live NWS status stays separate/i);
  assert.match(dashboard, /Planning scores are demonstration fixtures/i);
  assert.match(dashboard, /TEMPORAL HOLDOUT[^<\n]*NOT AN OFFICIAL FORECAST/i);
  assert.match(dashboard, /production source:\s*weather\.gov/i);
  assert.match(dashboard, /fetch\("\/api\/forecast"/);
  assert.match(dashboard, /new AbortController\(\)/);
  assert.match(dashboard, /Loading the authoritative National Weather Service lane/i);
  assert.match(dashboard, /Active alerts[\s\S]{0,100}liveForecast\.alerts\.length/i);
  assert.match(modelCard, /Official NWS forecasts and alerts\s+remain[\s\S]{0,80}authoritative operational source/i);
  assert.match(readme, /Official evidence first/i);

  const planningScoreBlock = dashboard.match(
    /const durationAdjustment[\s\S]*?const planningScore = clamp\(([\s\S]*?)\n\s*\);/,
  );
  assert.ok(planningScoreBlock, "Expected an inspectable planning-score calculation.");
  assert.doesNotMatch(
    planningScoreBlock[0],
    /liveForecast|livePeriod|checkedAt|\bNWS\b/i,
    "Live NWS observations must not silently drive the fictional planning score.",
  );

  assert.match(api, /source:\s*"National Weather Service"/);
  assert.match(api, /https:\/\/api\.weather\.gov\/points/);
  assert.match(api, /https:\/\/api\.weather\.gov\/alerts\/active/);
  assert.match(api, /"User-Agent"/);
  assert.match(api, /if \(!response\.ok\)/);
  assert.match(api, /checkedAt:\s*new Date\(\)\.toISOString\(\)/);
  assert.match(api, /status:\s*"unavailable"[\s\S]*periods:\s*\[\][\s\S]*alerts:\s*\[\]/);
});

test("the product describes environmental planning, not personal medical risk", async () => {
  const [dashboard, data, readme, modelCard] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
    source("README.md"),
    source("MODEL_CARD.md"),
  ]);
  const userFacing = `${dashboard}\n${data}`;

  const compactDashboard = compact(dashboard);
  assert.match(compactDashboard, /does not assess a person or predict an outcome/i);
  assert.match(compactDashboard, /not that a person has been assessed/i);
  assert.match(compactDashboard, /area context[^.]{0,80}never becomes a claim about a person/i);
  assert.match(readme, /model estimates environmental heat,[\s\S]{0,100}not illness, hospitalization, mortality, or individual danger/i);
  assert.match(modelCard, /individual illness, mortality, hospitalization, or emergency prediction/i);
  assert.match(modelCard, /diagnosis, treatment, or medical triage/i);
  assert.doesNotMatch(
    userFacing,
    /health risk score|illness probability|medical diagnosis|you (?:are|have) (?:at )?(?:high|medium|low) risk/i,
  );
});

test("methodology copy matches the planner's actual data boundary", async () => {
  const dashboard = await source("app/components/HeatShieldDashboard.tsx");
  const methodologyMatch = dashboard.match(
    /<article>\s*<span>Methodology<\/span>([\s\S]*?)<\/article>/,
  );
  assert.ok(methodologyMatch, "Expected a visible methodology card.");
  const methodology = compact(methodologyMatch[1]);

  assert.match(methodology, /(?:demo|demonstration|fixture|planning score)/i);
  assert.match(methodology, /(?:live NWS|official forecast)/i);
  assert.match(
    methodology,
    /(?:does not|never)[^.]{0,100}(?:enter|drive|change|adjust|influence)[^.]{0,80}(?:planning )?score/i,
    "Methodology must say that live NWS evidence does not drive the demo planning score.",
  );
  assert.doesNotMatch(
    methodology,
    /area-context inputs can add caution|neighborhood context[^.]{0,80}(?:drives?|adjusts?|changes?|adds?)[^.]{0,40}(?:score|caution)/i,
    "Demographic area context is for access auditing, not score adjustment.",
  );
});

test("facility and emergency actions use unambiguous 311 and 911 wording", async () => {
  const [dashboard, data, readme] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
    source("README.md"),
  ]);
  const product = compact(`${dashboard}\n${data}\n${readme}`);

  assert.match(product, /facility hours\/activation can change[^.]{0,20}call 311 before traveling/i);
  assert.match(product, /confusion\/fainting\/loss of consciousness can be emergency[^.]{0,20}call 911/i);
  assert.match(data, /Confirma un lugar fresco y una alternativa antes de salir/i);
  assert.match(data, /La confusión, el desmayo o la pérdida del conocimiento pueden ser una emergencia; llama al 911/i);
});

test("audited facility listings use a semantic table before a non-routing map", async () => {
  const [dashboard, data] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
  ]);

  assertBefore(
    dashboard,
    "<table>",
    'className="css-map"',
    "The semantic table must precede the supplemental visual map.",
  );
  assert.match(dashboard, /The table is the primary accessible view/i);
  assert.match(dashboard, /visual orientation[\s\S]{0,40}not a route or availability service/i);
  assert.match(
    dashboard,
    /<caption>[\s\S]{0,200}Listed Chicago cooling resources; activation, hours, and access must be confirmed[\s\S]{0,40}<\/caption>/i,
  );
  assert.match(dashboard, /<th scope="col">/);
  assert.match(dashboard, /<th scope="row">/);
  assert.match(dashboard, /role="img"/);
  assert.match(dashboard, /Stylized non-navigational orientation/i);
  assert.match(dashboard, /Straight-line distances[^.]{0,100}not routes/i);
  assert.match(dashboard, /No turn-by-turn directions, traffic state, hours, capacity, or activation status is inferred/i);
  assert.match(data, /const routeNotInferred:[\s\S]{0,220}Route not inferred/i);
  assert.match(data, /Address listed/);
  assert.match(data, /Call to verify/);
  assert.doesNotMatch(data, /\b\d+\s*(?:–|-)\s*\d+\s*min\b/i);
});

test("source freshness and provenance are visible for every evidence layer", async () => {
  const [dashboard, data, api, readme] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
    source("app/api/forecast/route.ts"),
    source("README.md"),
  ]);
  const freshness = data.slice(data.indexOf("export const sourceFreshness"));

  assert.match(dashboard, /Source freshness/i);
  assert.match(dashboard, /Every layer carries its own clock/i);
  for (const lane of [
    "Official forecast",
    "Environmental model",
    "Neighborhood context",
    "Cooling access",
  ]) {
    assert.match(freshness, new RegExp(`lane:\\s*"${lane}"`));
  }
  assert.equal((freshness.match(/\bsource:\s*"/g) ?? []).length, 4);
  assert.equal((freshness.match(/\bfreshness:\s*"/g) ?? []).length, 4);
  assert.equal((freshness.match(/\bnote:\s*"/g) ?? []).length, 4);
  assert.match(freshness, /National Weather Service API through \/api\/forecast/);
  assert.match(freshness, /Runtime request[^"\n]*15-minute cache/);
  assert.match(freshness, /NOAA O’Hare \+ Midway hourly observations/);
  assert.match(freshness, /CDC\/ATSDR SVI 2022 \+ Census TIGER\/Line 2022/);
  assert.match(freshness, /City of Chicago cooling-center directory/);
  assert.doesNotMatch(
    compact(dashboard),
    /These labels describe the fictional demonstration fixtures/i,
    "Freshness copy must distinguish live and audited sources from demo fixtures.",
  );
  assert.match(api, /generatedAt:/);
  assert.match(api, /sourceUrl:\s*forecastHourly/);
  assert.match(api, /s-maxage=900, stale-while-revalidate=3600/);
  assert.match(readme, /retrieval time/i);
  assert.match(readme, /checksum|SHA-256/i);
});

test("demographic context is reserved for access fairness, never prediction", async () => {
  const [dashboard, data, readme, modelCard] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
    source("README.md"),
    source("MODEL_CARD.md"),
  ]);

  assert.match(dashboard, /Context changes resources, not people/i);
  assert.match(dashboard, /must not be used to rank a resident, infer identity, or reduce service eligibility/i);
  assert.match(modelCard, /No demographic variable is a model input/i);
  assert.match(readme, /cooling-resource coverage gaps across SVI, no-vehicle, limited-English/i);

  const factorBlocks = [...data.matchAll(/factors:\s*\[([\s\S]*?)\]\s*,\s*facilities:/g)];
  assert.ok(factorBlocks.length > 0, "Expected scenario factor blocks.");
  for (const [, factors] of factorBlocks) {
    assert.doesNotMatch(
      factors,
      /older adult|no vehicle|limited English|race|ethnicity|disabil|\bSVI\b|demographic/i,
      "Sensitive neighborhood context must not become a planning-score factor.",
    );
  }
});

test("critical guidance is available in English and Spanish", async () => {
  const [dashboard, data] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
  ]);

  assert.match(data, /en:\s*\{[\s\S]*label:\s*"English"/);
  assert.match(data, /es:\s*\{[\s\S]*label:\s*"Español"/);
  assert.match(data, /escenario de demostración/i);
  assert.match(data, /Convierte la señal en un plan más seguro/i);
  assert.match(data, /sombra y agua/i);
  assert.match(data, /alerta traducida/i);
  assert.match(dashboard, /Object\.keys\(actionCopy\)/);
  assert.match(dashboard, /aria-label="Checklist language"/);
  assert.match(dashboard, /aria-pressed=\{language === key\}/);
  assert.match(
    dashboard,
    /lang=\{language\}/,
    "The active checklist language must be exposed to assistive technology.",
  );
});

test("published model metrics are derived from the versioned holdout artifact", async () => {
  const [dashboard, data, artifactText] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/lib/demo-data.ts"),
    source("model/artifacts/heatshield-model-evaluation.json"),
  ]);
  const artifact = JSON.parse(artifactText);
  const model = artifact.holdout.model;
  const baselines = artifact.holdout.baselines;

  assert.ok(Number.isInteger(artifact.rows.holdout) && artifact.rows.holdout > 0);
  assert.ok(model.regression.mae_f < baselines.persistence.mae_f);
  assert.ok(model.regression.mae_f < baselines.climatology_regression.mae_f);
  assert.ok(
    model.classifier.average_precision >
      baselines.climatology_classifier.average_precision,
  );
  assert.ok(model.regression.quantile.central_80_coverage > 0);
  assert.ok(model.regression.quantile.central_80_coverage < 1);

  assert.match(data, /import modelEvaluation from "\.\.\/\.\.\/model\/artifacts\/heatshield-model-evaluation\.json"/);
  for (const field of [
    "modelEvaluation.rows.holdout",
    "modelEvaluation.holdout.model.regression.mae_f",
    "modelEvaluation.holdout.baselines.persistence.mae_f",
    "modelEvaluation.holdout.baselines.climatology_regression.mae_f",
    "modelEvaluation.holdout.model.classifier.average_precision",
    "modelEvaluation.holdout.baselines.climatology_classifier.average_precision",
    "modelEvaluation.holdout.model.regression.quantile.central_80_coverage",
    "modelEvaluation.holdout.model.regression.quantile.mean_interval_width_f",
  ]) {
    assert.ok(data.includes(field), `Missing artifact-derived field: ${field}`);
  }
  assert.match(dashboard, /\{modelMetrics\.holdoutRows\} untouched 2024–2025 station-days/);
  assert.match(
    dashboard,
    /NOAA\/NCEI warm seasons 2015–2025[^<\n]*\{modelMetrics\.holdoutRows\} untouched holdout rows/,
    "Holdout-row claims should stay bound to the artifact instead of being duplicated as a literal.",
  );
});

test("core keyboard, document, motion, and print accessibility remains intact", async () => {
  const [dashboard, css, layout] = await Promise.all([
    source("app/components/HeatShieldDashboard.tsx"),
    source("app/globals.css"),
    source("app/layout.tsx"),
  ]);

  assertBefore(dashboard, 'href="#main-content"', 'id="main-content"', "Skip link must precede main content.");
  assert.match(layout, /<html lang="en">/);
  assert.match(dashboard, /<main id="main-content">/);
  assert.match(dashboard, /<nav[^>]*aria-label=/);
  assert.match(dashboard, /<fieldset>/);
  assert.match(dashboard, /<legend>/);
  assert.match(dashboard, /htmlFor="scenario-select"/);
  assert.match(dashboard, /aria-live="polite"/);
  assert.match(dashboard, /role="alert"/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /@media\s+print/);
});

test("starter UI, preview scaffolding, and mojibake cannot reach the product", async () => {
  const appFiles = await collectTextFiles(new URL("app/", projectRoot));
  const packageJson = await source("package.json");
  const joined = appFiles.map(({ path, text }) => `${path}\n${text}`).join("\n");

  try {
    const previewEntries = await readdir(new URL("app/_sites-preview/", projectRoot));
    assert.deepEqual(previewEntries, [], "The disposable preview directory must contain no files.");
  } catch (error) {
    assert.equal(error?.code, "ENOENT");
  }
  assert.doesNotMatch(joined, /Your site is taking shape|Building your site|codex-preview|SkeletonPreview/i);
  assert.doesNotMatch(joined, /(?:Â|Ã.|â€|â€™|â€“|â€”|â€¢|â†’|âœ“)/);
  assert.doesNotMatch(packageJson, /site-creator-vinext-starter|react-loading-skeleton/i);
  assert.match(joined, /HeatShield AI/i);
});

test("the production render carries the same public trust contract", async (context) => {
  try {
    await access(new URL("dist/server/index.js", projectRoot));
  } catch {
    context.skip("Build output is absent; `npm test` creates it before this test runs.");
    return;
  }

  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  const rendered = compact(html);
  assert.match(rendered, /<title>[^<]*HeatShield AI/i);
  assert.match(rendered, /Fictional Chicago planner/i);
  assert.match(rendered, /Live NWS status stays separate/i);
  assert.match(rendered, /Planning scores are demonstration fixtures/i);
  assert.match(rendered, /TEMPORAL HOLDOUT[^<]*NOT AN OFFICIAL FORECAST/i);
  assert.match(rendered, /facility hours\/activation can change[^<]*call 311 before traveling/i);
  assert.match(rendered, /confusion\/fainting\/loss of consciousness can be emergency[^<]*call 911/i);
  assert.match(rendered, /English/);
  assert.match(rendered, /Español/);
  assert.match(rendered, /<table/);
  assert.match(rendered, /<caption/);
  assert.match(rendered, /scope="col"/);
  assert.match(rendered, /scope="row"/);
  assertBefore(rendered, "<table", 'class="css-map"', "Rendered table must precede the map.");
  assertBefore(
    rendered,
    'class="evidence-card official-card"',
    'class="evidence-card experimental-card"',
    "Official evidence must render first.",
  );
  assert.doesNotMatch(rendered, /Your site is taking shape|Building your site|react-loading-skeleton|codex-preview/i);
  assert.doesNotMatch(rendered, /(?:Â|Ã.|â€|â€™|â€“|â€”|â€¢|â†’|âœ“)/);
});
