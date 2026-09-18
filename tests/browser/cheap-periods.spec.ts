import { expect, test } from "@playwright/test";
import { highlightRegions } from "../../web/src/chart";
import { cheapestPeriods } from "../../web/src/cheap-periods";
import type { Slot } from "../../web/src/data";

function slots(
  prices: (number | null)[],
  start = "2026-09-18T22:00:00Z",
): Slot[] {
  return prices.map((price, i) => {
    const date = new Date(Date.parse(start) + i * 1800000);
    return {
      start: date.toISOString(),
      end: new Date(date.getTime() + 1800000).toISOString(),
      price,
      status: price === null ? "unavailable" : "predicted",
      policy: "ensemble-experimental",
      day: date.toISOString().slice(0, 10),
      minute: date.getUTCHours() * 60 + date.getUTCMinutes(),
      clock: "",
      utc_offset_minutes: 0,
    };
  });
}
const from = new Date("2026-09-18T00:00:00Z");

test("finds the cheapest combination instead of greedily blocking a second period", () => {
  const data = slots([10, 10, 0, 0, 0, 0, 10, 10]);
  expect(cheapestPeriods(data, 1, 2, from)[0].meanPrice).toBe(0);
  const result = cheapestPeriods(data, 2, 2, from);
  expect(result).toHaveLength(2);
  expect(result.map((r) => r.meanPrice)).toEqual([5, 5]);
  expect(result[0].end).toBe(result[1].start);
});

test("selection spans days, excludes elapsed slots, and preserves negative prices", () => {
  const data = slots([0, 0, 0, 0, 10, 10, 10, 10, -2, -2, -2, -2]);
  const result = cheapestPeriods(data, 1, 2, new Date(data[2].start));
  expect(result[0].start).toBe(data[8].start);
  expect(result[0].meanPrice).toBe(-2);
  const midnight = cheapestPeriods(slots([1, 1, 1, 1]), 1, 2, from)[0];
  expect(midnight.start.slice(0, 10)).not.toBe(midnight.end.slice(0, 10));
});

test("does not bridge missing prices or timestamps and returns only feasible periods", () => {
  expect(cheapestPeriods(slots([1, 1, null, 1, 1]), 5, 2, from)).toEqual([]);
  const hole = slots([1, 1, 1, 1, 1]);
  hole.splice(2, 1);
  expect(cheapestPeriods(hole, 1, 2, from)).toEqual([]);
  expect(cheapestPeriods(slots([1, 1, 1, 1]), 5, 2, from)).toHaveLength(1);
  expect(
    cheapestPeriods(slots([1, 1, 1, 1]), 1, 2, new Date("2027-01-01")),
  ).toEqual([]);
});

test("two hours means four real intervals even across the autumn clock change", () => {
  const data = slots([1, 1, 1, 1], "2026-10-25T00:00:00Z");
  const result = cheapestPeriods(data, 1, 2, from)[0];
  expect(Date.parse(result.end) - Date.parse(result.start)).toBe(7200000);
});

test("ties prefer earlier periods and controls cannot select less than two hours", () => {
  const data = slots([1, 1, 1, 1, 1, 1, 1, 1]);
  expect(cheapestPeriods(data, 1, 2, from)[0].start).toBe(data[0].start);
  expect(() => cheapestPeriods(data, 1, 1, from)).toThrow();
  expect(() => cheapestPeriods(data, 6, 2, from)).toThrow();
});

test("adjacent highlighted periods keep separate edges and centred numbers", () => {
  const data = slots(Array(8).fill(1), "2026-09-18T10:00:00Z");
  const periods = cheapestPeriods(data, 2, 2, from);
  const regions = highlightRegions(data, periods);
  expect(
    regions.map((r) => [r.minute, r.end_minute, r.midpoint, r.rank]),
  ).toEqual([
    [600, 720, 660, 1],
    [720, 840, 780, 2],
  ]);
});

test("a period crossing midnight keeps its number on both daily charts", () => {
  const data = slots([1, 1, 1, 1], "2026-09-18T23:00:00Z");
  const periods = cheapestPeriods(data, 1, 2, from);
  expect(
    highlightRegions(data.slice(0, 2), periods).map((r) => [
      r.minute,
      r.end_minute,
      r.rank,
    ]),
  ).toEqual([[1380, 1440, 1]]);
  expect(
    highlightRegions(data.slice(2), periods).map((r) => [
      r.minute,
      r.end_minute,
      r.rank,
    ]),
  ).toEqual([[0, 60, 1]]);
});
