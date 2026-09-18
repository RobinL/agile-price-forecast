export type Slot = {
  start: string;
  end: string;
  day: string;
  minute: number;
  clock: string;
  utc_offset_minutes: number;
  price: number | null;
  status: "published" | "predicted" | "unavailable";
  policy:
    | "published"
    | "unavailable"
    | "research-48-72"
    | "ensemble-experimental"
    | "linear-baseline";
};
export type Score = { model: string; mae_p_kwh: number | null; slots: number };
export type ResearchAccuracy = {
  kind: "research-comparison";
  recipe_id: string;
  recipe_fingerprint: string;
  evaluated_as_of: string;
  target_start: string;
  target_end: string;
  issue_days: number;
  description: string;
  comparison: Score[];
  by_horizon: { day_ahead: number; comparison: Score[] }[];
};
export type LinearAccuracy = {
  recipe_id: "linear-ridge-v1";
  model_mae_p_kwh: number;
  week_earlier_mae_p_kwh: number;
  slots: number;
  description: string;
};
export type Forecast = {
  schema_version: 2;
  mode: "demo" | "replay" | "live";
  issued_at: string;
  generated_at: string;
  timezone: "Europe/London";
  region: "G";
  unit: string;
  horizon_hours: 168;
  horizon_end: string;
  slots: Slot[];
  notes: string[];
  model: {
    name: string;
    id: string;
    recipe_id: string;
    trained_as_of: string;
    training_rows: number;
  };
  sources: { name: string; retrieved_at?: string }[];
  calibration: null | {
    value: number;
    samples: number;
    issue_days: number;
    warming_up: boolean;
  };
  accuracy: null | ResearchAccuracy | LinearAccuracy;
};

export function parseForecast(value: unknown): Forecast {
  const f = value as Forecast;
  if (
    !f ||
    f.schema_version !== 2 ||
    !["demo", "replay", "live"].includes(f.mode) ||
    !Number.isFinite(Date.parse(f.issued_at)) ||
    f.timezone !== "Europe/London" ||
    f.horizon_hours !== 168 ||
    !Number.isFinite(Date.parse(f.horizon_end)) ||
    f.region !== "G" ||
    !f.model ||
    !Number.isFinite(f.model.training_rows) ||
    !Number.isFinite(Date.parse(f.model.trained_as_of)) ||
    !Array.isArray(f.notes) ||
    !f.notes.every((n) => typeof n === "string") ||
    !Array.isArray(f.slots) ||
    !f.slots.length
  ) {
    throw new Error(
      "The forecast file is missing or uses an unsupported format.",
    );
  }
  for (const s of f.slots) {
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(s.day) ||
      !Number.isFinite(Date.parse(s.start)) ||
      !Number.isFinite(Date.parse(s.end)) ||
      !Number.isFinite(s.minute) ||
      s.minute < 0 ||
      s.minute >= 1440 ||
      !["published", "predicted", "unavailable"].includes(s.status) ||
      ![
        "published",
        "unavailable",
        "research-48-72",
        "ensemble-experimental",
        "linear-baseline",
      ].includes(s.policy) ||
      (s.status === "unavailable"
        ? s.price !== null
        : !Number.isFinite(s.price))
    ) {
      throw new Error("The forecast contains an invalid half-hour interval.");
    }
  }
  if (f.accuracy) {
    const a = f.accuracy;
    const valid =
      "comparison" in a
        ? Array.isArray(a.comparison) &&
          a.comparison.every(
            (s) =>
              Number.isFinite(s.slots) &&
              (s.mae_p_kwh === null || Number.isFinite(s.mae_p_kwh)),
          )
        : Number.isFinite(a.model_mae_p_kwh) &&
          Number.isFinite(a.week_earlier_mae_p_kwh) &&
          Number.isFinite(a.slots);
    if (!valid)
      throw new Error("The forecast contains invalid accuracy information.");
  }
  return f;
}

export function londonDay(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}
export function dayTitle(day: string, reference: string): string {
  const difference = Math.round(
    (Date.parse(day) - Date.parse(reference)) / 86400000,
  );
  const weekday = new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    timeZone: "Europe/London",
  }).format(new Date(`${day}T12:00:00Z`));
  return difference === 0
    ? `Today — ${weekday}`
    : difference === 1
      ? `Tomorrow — ${weekday}`
      : weekday;
}
