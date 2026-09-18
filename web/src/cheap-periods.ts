import type { Slot } from "./data";

export type CheapPeriod = {
  start: string;
  end: string;
  meanPrice: number;
  includesPredictions: boolean;
};

// Compare equal-duration periods by their average p/kWh. Select the cheapest
// combination of up to n non-overlapping periods across the whole supplied
// forecast, not n per day. UTC timestamps allow windows across midnight/DST.
export function cheapestPeriods(
  slots: Slot[],
  count: number,
  hours: number,
  from: Date,
): CheapPeriod[] {
  if (
    !Number.isInteger(count) ||
    count < 1 ||
    count > 5 ||
    hours < 2 ||
    hours > 24 ||
    !Number.isInteger(hours * 2) ||
    !Number.isFinite(from.getTime())
  ) {
    throw new Error(
      "Choose 1–5 periods, each 2–24 hours in half-hour increments.",
    );
  }
  const rows = [...slots].sort(
    (a, b) => Date.parse(a.start) - Date.parse(b.start),
  );
  const length = hours * 2;
  // Each entry is the cheapest selection using only rows before this index.
  type Selection = { cost: number; periods: CheapPeriod[] };
  const best: (Selection | undefined)[][] = Array.from(
    { length: rows.length + 1 },
    () => Array(count + 1).fill(undefined),
  );
  best[0][0] = { cost: 0, periods: [] };
  for (let end = 1; end <= rows.length; end++) {
    best[end] = [...best[end - 1]];
    if (end < length) continue;
    const window = rows.slice(end - length, end);
    const valid =
      Date.parse(window[0].start) >= from.getTime() &&
      window.every(
        (slot, i) =>
          slot.price !== null &&
          Number.isFinite(slot.price) &&
          slot.status !== "unavailable" &&
          Date.parse(slot.end) - Date.parse(slot.start) === 30 * 60 * 1000 &&
          (i === 0 || Date.parse(slot.start) === Date.parse(window[i - 1].end)),
      );
    if (!valid) continue;
    const period: CheapPeriod = {
      start: window[0].start,
      end: window[window.length - 1].end,
      meanPrice: window.reduce((sum, s) => sum + s.price!, 0) / length,
      includesPredictions: window.some((s) => s.status === "predicted"),
    };
    for (let k = 1; k <= count; k++) {
      const previous = best[end - length][k - 1];
      if (!previous) continue;
      const cost = previous.cost + period.meanPrice;
      if (!best[end][k] || cost < best[end][k]!.cost - 1e-9) {
        best[end][k] = { cost, periods: [...previous.periods, period] };
      }
    }
  }
  for (let k = count; k > 0; k--) {
    if (best[rows.length][k])
      return best[rows.length][k]!.periods.sort(
        (a, b) =>
          a.meanPrice - b.meanPrice ||
          Date.parse(a.start) - Date.parse(b.start),
      );
  }
  return [];
}
