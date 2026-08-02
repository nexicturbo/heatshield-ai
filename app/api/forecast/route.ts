import { NextResponse } from "next/server";

const CHICAGO_POINT = { latitude: 41.8781, longitude: -87.6298 } as const;
const NWS_HEADERS = {
  Accept: "application/geo+json, application/json",
  "User-Agent":
    "HeatShieldAI/1.0 (student civic-technology project; https://github.com/nexicturbo/heatshield-ai)",
} as const;

type NwsPeriod = {
  number: number;
  name: string;
  startTime: string;
  endTime: string;
  isDaytime: boolean;
  temperature: number;
  temperatureUnit: string;
  windSpeed: string;
  windDirection: string;
  shortForecast: string;
  probabilityOfPrecipitation?: { value?: number | null };
  relativeHumidity?: { value?: number | null };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nwsPeriod(value: unknown): value is NwsPeriod {
  if (!isRecord(value)) return false;
  return (
    typeof value.number === "number" &&
    typeof value.name === "string" &&
    typeof value.startTime === "string" &&
    typeof value.endTime === "string" &&
    typeof value.isDaytime === "boolean" &&
    typeof value.temperature === "number" &&
    typeof value.temperatureUnit === "string" &&
    typeof value.windSpeed === "string" &&
    typeof value.windDirection === "string" &&
    typeof value.shortForecast === "string"
  );
}

async function nwsJson(url: string): Promise<unknown> {
  const response = await fetch(url, {
    headers: NWS_HEADERS,
    next: { revalidate: 900 },
  });
  if (!response.ok) {
    throw new Error(`NWS request failed with ${response.status}`);
  }
  return response.json();
}

function unavailable(reason: string) {
  return NextResponse.json(
    {
      status: "unavailable",
      source: "National Weather Service",
      checkedAt: new Date().toISOString(),
      reason,
      message:
        "Live forecast data is unavailable. Follow current National Weather Service alerts and call 311 for cooling resources.",
      periods: [],
      alerts: [],
    },
    {
      status: 503,
      headers: {
        "Cache-Control": "public, s-maxage=60, stale-while-revalidate=300",
      },
    },
  );
}

export async function GET() {
  try {
    const pointUrl = `https://api.weather.gov/points/${CHICAGO_POINT.latitude},${CHICAGO_POINT.longitude}`;
    const point = await nwsJson(pointUrl);
    if (!isRecord(point) || !isRecord(point.properties)) {
      return unavailable("NWS point metadata did not match the expected shape.");
    }

    const forecastHourly = point.properties.forecastHourly;
    if (typeof forecastHourly !== "string") {
      return unavailable("NWS point metadata did not include an hourly forecast.");
    }

    const alertUrl = `https://api.weather.gov/alerts/active?point=${CHICAGO_POINT.latitude},${CHICAGO_POINT.longitude}`;
    const [forecast, alertsResult] = await Promise.all([
      nwsJson(forecastHourly),
      nwsJson(alertUrl).catch(() => null),
    ]);

    if (!isRecord(forecast) || !isRecord(forecast.properties)) {
      return unavailable("NWS hourly forecast did not match the expected shape.");
    }
    const rawPeriods = forecast.properties.periods;
    if (!Array.isArray(rawPeriods)) {
      return unavailable("NWS hourly forecast did not include periods.");
    }
    const periods = rawPeriods.filter(nwsPeriod).slice(0, 24).map((period) => ({
      number: period.number,
      name: period.name,
      startTime: period.startTime,
      endTime: period.endTime,
      isDaytime: period.isDaytime,
      temperature: period.temperature,
      temperatureUnit: period.temperatureUnit,
      windSpeed: period.windSpeed,
      windDirection: period.windDirection,
      shortForecast: period.shortForecast,
      precipitationProbability:
        period.probabilityOfPrecipitation?.value ?? null,
      relativeHumidity: period.relativeHumidity?.value ?? null,
    }));
    if (periods.length === 0) {
      return unavailable("NWS returned no valid hourly periods.");
    }

    const alerts =
      isRecord(alertsResult) && Array.isArray(alertsResult.features)
        ? alertsResult.features.flatMap((feature) => {
            if (!isRecord(feature) || !isRecord(feature.properties)) return [];
            const properties = feature.properties;
            if (
              typeof properties.event !== "string" ||
              typeof properties.headline !== "string"
            ) {
              return [];
            }
            return [
              {
                event: properties.event,
                headline: properties.headline,
                severity:
                  typeof properties.severity === "string"
                    ? properties.severity
                    : "Unknown",
                urgency:
                  typeof properties.urgency === "string"
                    ? properties.urgency
                    : "Unknown",
                effective:
                  typeof properties.effective === "string"
                    ? properties.effective
                    : null,
                expires:
                  typeof properties.expires === "string"
                    ? properties.expires
                    : null,
              },
            ];
          })
        : [];

    return NextResponse.json(
      {
        status: "available",
        source: "National Weather Service",
        sourceUrl: forecastHourly,
        checkedAt: new Date().toISOString(),
        generatedAt:
          typeof forecast.properties.generatedAt === "string"
            ? forecast.properties.generatedAt
            : null,
        point: CHICAGO_POINT,
        periods,
        alerts,
      },
      {
        headers: {
          "Cache-Control": "public, s-maxage=900, stale-while-revalidate=3600",
        },
      },
    );
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Unknown NWS failure.";
    return unavailable(reason);
  }
}
