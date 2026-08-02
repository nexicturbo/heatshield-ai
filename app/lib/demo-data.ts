import modelEvaluation from "../../model/artifacts/heatshield-model-evaluation.json";

export type DurationKey = "15" | "45" | "90";
export type TimeKey = "morning" | "afternoon" | "evening";
export type TransportKey = "walk" | "transit" | "car";

export type CoolingFacility = {
  id: string;
  name: string;
  area: string;
  distance: string;
  travel: Record<TransportKey, string>;
  features: string[];
  verification: string;
  mapPosition: { x: number; y: number };
};

export type Scenario = {
  id: string;
  label: string;
  zip: string;
  place: string;
  summary: string;
  context: {
    olderAdults: string;
    noVehicle: string;
    limitedEnglish: string;
    disability: string;
    note: string;
  };
  factors: Array<{
    label: string;
    contribution: number;
    explanation: string;
  }>;
  facilities: CoolingFacility[];
};

const routeNotInferred: Record<TransportKey, string> = {
  walk: "Route not inferred",
  transit: "Route not inferred",
  car: "Route not inferred",
};

const facility = (
  id: string,
  name: string,
  area: string,
  distance: string,
  siteType: string,
  mapPosition: { x: number; y: number },
): CoolingFacility => ({
  id,
  name,
  area,
  distance,
  travel: routeNotInferred,
  features: [siteType, "Address listed", "Call to verify"],
  verification: "City listing · current activation, hours, capacity, and access not verified",
  mapPosition,
});

const austinFacilities = [
  facility(
    "austin-library",
    "Austin",
    "5615 W. Race Avenue",
    "0.82 km straight-line",
    "Library",
    { x: 49, y: 35 },
  ),
  facility(
    "west-chicago-library",
    "West Chicago Avenue",
    "4856 W. Chicago Avenue",
    "0.84 km straight-line",
    "Library",
    { x: 63, y: 45 },
  ),
  facility(
    "ohio-spray-feature",
    "Ohio",
    "4712 W. Ohio St",
    "1.18 km straight-line",
    "Park District spray feature",
    { x: 72, y: 65 },
  ),
];

const humboldtFacilities = [
  facility(
    "kedvale-spray-feature",
    "Kedvale",
    "4140 W. Hirsch St",
    "0.55 km straight-line",
    "Park District spray feature",
    { x: 54, y: 35 },
  ),
  facility(
    "north-pulaski-library",
    "North Pulaski",
    "4300 W. North Avenue",
    "1.01 km straight-line",
    "Library",
    { x: 66, y: 53 },
  ),
  facility(
    "trina-davila-center",
    "Trina Davila Center",
    "4312 W. North Avenue",
    "1.03 km straight-line",
    "Community service center",
    { x: 74, y: 70 },
  ),
];

const northLawndaleFacilities = [
  facility(
    "tenth-district",
    "10th District",
    "3315 W. Ogden Ave",
    "0.46 km straight-line",
    "Police district",
    { x: 52, y: 38 },
  ),
  facility(
    "park-534",
    "Park No. 534",
    "1301 S. St Louis Ave",
    "0.67 km straight-line",
    "Park District spray feature",
    { x: 64, y: 52 },
  ),
  facility(
    "douglass-library",
    "Douglass",
    "3353 W. 13th Street",
    "0.81 km straight-line",
    "Library",
    { x: 73, y: 68 },
  ),
];

export const scenarios: Scenario[] = [
  {
    id: "chicago-austin-25",
    label: "Austin (Community Area 25)",
    zip: "60644",
    place: "Austin · Chicago Community Area 25",
    summary:
      "A West Side demonstration grounded in audited community-level cooling-access aggregates.",
    context: {
      olderAdults: "14.9%",
      noVehicle: "29.9%",
      limitedEnglish: "3.5%",
      disability: "17.6%",
      note: "Population-weighted 2022 SVI estimates describe the community area, never a person.",
    },
    factors: [
      {
        label: "Scenario heat reference",
        contribution: 28,
        explanation: "A transparent fixture drives the demo planner; live NWS data stays separate.",
      },
      {
        label: "Warm overnight reference",
        contribution: 14,
        explanation: "Less nighttime cooling can reduce recovery time in the scenario.",
      },
      {
        label: "Model uncertainty",
        contribution: 10,
        explanation: "Experimental and shown with a wide uncertainty band.",
      },
      {
        label: "Cooling access friction",
        contribution: 8,
        explanation: "The audited mean nearest-center distance is 642 metres for this area.",
      },
    ],
    facilities: austinFacilities,
  },
  {
    id: "humboldt-park-23",
    label: "Humboldt Park (Community Area 23)",
    zip: "60651",
    place: "Humboldt Park · Chicago Community Area 23",
    summary:
      "A West Side comparison with seven listed resources and an estimated 86.8% one-kilometre coverage rate.",
    context: {
      olderAdults: "9.4%",
      noVehicle: "24.7%",
      limitedEnglish: "9.5%",
      disability: "13.2%",
      note: "These population-weighted area estimates support access auditing only.",
    },
    factors: [
      {
        label: "Scenario heat reference",
        contribution: 26,
        explanation: "The demonstration value is not presented as a live forecast.",
      },
      {
        label: "Unshaded waiting",
        contribution: 12,
        explanation: "Waiting can lengthen outdoor exposure; no route is inferred here.",
      },
      {
        label: "Model uncertainty",
        contribution: 8,
        explanation: "Experimental estimate, not a measured temperature.",
      },
      {
        label: "Cooling access distance",
        contribution: 7,
        explanation: "The audited mean nearest-center distance is 628 metres for this area.",
      },
    ],
    facilities: humboldtFacilities,
  },
  {
    id: "north-lawndale-29",
    label: "North Lawndale (Community Area 29)",
    zip: "60623",
    place: "North Lawndale · Chicago Community Area 29",
    summary:
      "A West Side comparison with the shortest audited mean nearest-center distance of the three examples.",
    context: {
      olderAdults: "12.3%",
      noVehicle: "36.5%",
      limitedEnglish: "2.2%",
      disability: "19.6%",
      note: "Area context guides service design and must not be used to rank residents.",
    },
    factors: [
      {
        label: "Scenario heat reference",
        contribution: 30,
        explanation: "The transparent fixture dominates the demo planning signal.",
      },
      {
        label: "Warm overnight reference",
        contribution: 15,
        explanation: "The scenario offers less nighttime relief.",
      },
      {
        label: "Model uncertainty",
        contribution: 12,
        explanation: "Experimental and intentionally uncertainty-bounded.",
      },
      {
        label: "Cooling access distance",
        contribution: 10,
        explanation: "The audited mean nearest-center distance is 550 metres for this area.",
      },
    ],
    facilities: northLawndaleFacilities,
  },
];

export const actionCopy = {
  en: {
    label: "English",
    heading: "Turn the signal into a safer plan",
    intro: "Check off the actions that fit this demonstration scenario.",
    actions: [
      "Move strenuous outdoor activity before 11 AM when possible.",
      "Pair every 20 minutes outside with a shade and water pause.",
      "Confirm a cooling destination and a backup before leaving.",
      "Arrange a ride or translated alert for someone who may need one.",
    ],
    emergency:
      "confusion/fainting/loss of consciousness can be emergency—call 911",
  },
  es: {
    label: "Español",
    heading: "Convierte la señal en un plan más seguro",
    intro: "Marca las acciones que sirvan para este escenario de demostración.",
    actions: [
      "Mueve la actividad intensa al aire libre antes de las 11 AM cuando sea posible.",
      "Por cada 20 minutos afuera, haz una pausa con sombra y agua.",
      "Confirma un lugar fresco y una alternativa antes de salir.",
      "Organiza transporte o una alerta traducida para quien pueda necesitarla.",
    ],
    emergency:
      "La confusión, el desmayo o la pérdida del conocimiento pueden ser una emergencia; llama al 911.",
  },
} as const;

export const sourceFreshness = [
  {
    lane: "Official forecast",
    source: "National Weather Service API through /api/forecast · central Chicago reference point",
    freshness: "Runtime request · 15-minute cache",
    note: "A value appears only after the response passes strict shape validation.",
  },
  {
    lane: "Environmental model",
    source: "NOAA O’Hare + Midway hourly observations",
    freshness: "Warm seasons · 2015–2025",
    note: "Forward validation and a held-out 2024–2025 test period prevent future leakage.",
  },
  {
    lane: "Neighborhood context",
    source: "CDC/ATSDR SVI 2022 + Census TIGER/Line 2022",
    freshness: "Retrieved and validated · Aug 2, 2026",
    note: "Sentinel values are null; population is allocated by projected intersection area.",
  },
  {
    lane: "Cooling access",
    source: "City of Chicago cooling-center directory",
    freshness: "Source last-modified · Jul 24, 2026",
    note: "Listed location never implies current activation, hours, capacity, or accessibility.",
  },
];

export const modelMetrics = {
  holdoutRows: modelEvaluation.rows.holdout,
  mae: modelEvaluation.holdout.model.regression.mae_f.toFixed(2),
  persistenceMae:
    modelEvaluation.holdout.baselines.persistence.mae_f.toFixed(2),
  climatologyMae:
    modelEvaluation.holdout.baselines.climatology_regression.mae_f.toFixed(2),
  prAuc:
    modelEvaluation.holdout.model.classifier.average_precision.toFixed(3),
  climatologyPrAuc:
    modelEvaluation.holdout.baselines.climatology_classifier.average_precision.toFixed(3),
  intervalCoverage:
    (modelEvaluation.holdout.model.regression.quantile.central_80_coverage * 100).toFixed(1),
  intervalWidth:
    modelEvaluation.holdout.model.regression.quantile.mean_interval_width_f.toFixed(2),
} as const;
