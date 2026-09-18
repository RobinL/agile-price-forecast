import type { VisualizationSpec } from "vega-embed";
import type { Slot } from "./data";

import type { CheapPeriod } from "./cheap-periods";

// Fixed colour anchors, smoothly interpolated and shared by all days and the key.
export const PRICE_COLOURS = [
  { price: -5, label: "≤−5", color: "#538daf" },
  { price: 5, label: "5", color: "#529b95" },
  { price: 15, label: "15", color: "#659c65" },
  { price: 25, label: "25", color: "#c3a350" },
  { price: 35, label: "35", color: "#d47b65" },
  { price: 45, label: "≥45", color: "#b74465" },
];
const PRICE_COLOUR_SCALE = {
  type: "linear" as const,
  domain: PRICE_COLOURS.map((stop) => stop.price),
  range: PRICE_COLOURS.map((stop) => stop.color),
  interpolate: "rgb" as const,
  clamp: true,
  nice: false,
  zero: false,
};

export function chartBars(slots: Slot[]) {
  const counts = new Map<number, number>();
  const seen = new Map<number, number>();
  slots.forEach((s) => counts.set(s.minute, (counts.get(s.minute) ?? 0) + 1));
  return slots.flatMap((slot) => {
    // Autumn's repeated half-hours share a clock position side by side, so
    // neither real interval is hidden by the other. Tooltips retain BST/GMT.
    const index = seen.get(slot.minute) ?? 0;
    seen.set(slot.minute, index + 1);
    const width = 30 / counts.get(slot.minute)!;
    const start = slot.minute + index * width;
    return slot.price === null
      ? []
      : [
          {
            minute: start + 1,
            end_minute: start + width - 1,
            band_start: start,
            band_end: start + width,
            start: slot.start,
            end: slot.end,
            price: slot.price,
            clock: slot.clock,
            status:
              slot.status === "published"
                ? "Published price"
                : "Model estimate",
          },
        ];
  });
}

// Join each period's touching half-hours for one pair of edges and one badge.
// Keep different period numbers separate even when their edges touch. Split a
// period where the visible clock positions are disjoint (for example at DST).
export function highlightRegions(slots: Slot[], periods: CheapPeriod[]) {
  const bars = chartBars(slots);
  return periods.flatMap((period, index) => {
    const selected = bars
      .filter(
        (bar) =>
          Date.parse(bar.start) >= Date.parse(period.start) &&
          Date.parse(bar.end) <= Date.parse(period.end),
      )
      .sort((a, b) => a.band_start - b.band_start);
    const regions: {
      minute: number;
      end_minute: number;
      rank: number;
      label: string;
    }[] = [];
    for (const bar of selected) {
      const previous = regions[regions.length - 1];
      if (previous && bar.band_start <= previous.end_minute) {
        previous.end_minute = Math.max(previous.end_minute, bar.band_end);
      } else
        regions.push({
          minute: bar.band_start,
          end_minute: bar.band_end,
          rank: index + 1,
          label: `Cheapest period ${index + 1}`,
        });
    }
    return regions.map((region) => ({
      ...region,
      midpoint: (region.minute + region.end_minute) / 2,
    }));
  });
}

export function priceDomain(slots: Slot[]): [number, number] {
  const values = slots.flatMap((s) => (s.price === null ? [] : [s.price]));
  if (!values.length) return [0, 40];
  return [
    Math.floor(Math.min(0, ...values) / 5) * 5,
    Math.ceil((Math.max(5, ...values) + 2) / 5) * 5,
  ];
}

export function chartSpec(
  slots: Slot[],
  domain: [number, number],
  now?: { minute: number; label: string },
  periods: CheapPeriod[] = [],
): VisualizationSpec {
  const bars = chartBars(slots);
  const published: { minute: number; end_minute: number }[] = [];
  for (const bar of bars
    .filter((bar) => bar.status === "Published price")
    .sort((a, b) => a.band_start - b.band_start)) {
    const previous = published.at(-1);
    if (previous && previous.end_minute === bar.band_start)
      previous.end_minute = bar.band_end;
    else published.push({ minute: bar.band_start, end_minute: bar.band_end });
  }
  const publishedLabel = published.length
    ? [{ minute: Math.max(...published.map((bar) => bar.end_minute)) }]
    : [];
  const highlights = highlightRegions(slots, periods);
  const edges = highlights.flatMap((region) => [
    { minute: region.minute, label: region.label },
    { minute: region.end_minute, label: region.label },
  ]);
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v6.json",
    width: "container",
    // Fit the width only: annotations above the plot must not shrink the bars.
    height: 110,
    autosize: { type: "fit-x", contains: "padding" },
    padding: { left: 6, right: 12, top: 8, bottom: 5 },
    // Every day uses a full London clock day and the same global price range.
    encoding: {
      x: {
        field: "minute",
        type: "quantitative",
        scale: { domain: [0, 1440], nice: false },
        axis: {
          title: null,
          // Keep at least 28px per label. Vega updates these ticks whenever the
          // plot resizes, from hourly on desktop to wider intervals on phones.
          values: {
            expr: "sequence(0, 1441, width >= 672 ? 60 : width >= 336 ? 120 : width >= 224 ? 180 : width >= 168 ? 240 : 360)",
          },
          labelExpr:
            "datum.value === 1440 ? '12am' : (datum.value % 720 === 0 ? '12' : format((datum.value / 60) % 12, 'd')) + (datum.value < 720 ? 'am' : 'pm')",
          labelAngle: 0,
          labelOverlap: false,
          labelFlush: false,
          grid: false,
          labelPadding: 8,
        },
      },
    },
    layer: [
      {
        name: "published_background",
        data: { values: published },
        mark: { type: "rect", color: "#eeeeec", clip: true },
        encoding: {
          x2: { field: "end_minute" },
          y: { value: 0 },
          y2: { value: { expr: "height" } },
        },
      },
      {
        name: "cheap_periods",
        data: { values: highlights },
        mark: { type: "rect", color: "#ffe77a", clip: true },
        encoding: {
          opacity: {
            field: "rank",
            type: "quantitative",
            scale: { domain: [1, 5], range: [0.55, 0.04], clamp: true },
            legend: null,
          },
          x2: { field: "end_minute" },
          y: { value: 0 },
          y2: { value: { expr: "height" } },
          tooltip: [{ field: "label", title: "Selected period" }],
        },
      },
      {
        name: "price_bars",
        data: { values: bars },
        mark: { type: "bar", clip: true, strokeWidth: 0.8 },
        encoding: {
          x2: { field: "end_minute" },
          y2: { datum: 0 },
          y: {
            field: "price",
            type: "quantitative",
            scale: { domain, nice: false, zero: false },
            axis: {
              title: null,
              labelExpr: "format(datum.value, '~g') + 'p/kWh'",
              tickCount: 4,
              minExtent: 72,
              maxExtent: 72,
              labelPadding: 8,
            },
          },
          color: {
            field: "price",
            type: "quantitative",
            scale: PRICE_COLOUR_SCALE,
            legend: null,
          },
          stroke: {
            field: "price",
            type: "quantitative",
            scale: PRICE_COLOUR_SCALE,
            legend: null,
          },
          tooltip: [
            { field: "clock", title: "Half-hour starting" },
            { field: "price", title: "Pence/kWh", format: ".2f" },
            { field: "status", title: "Type" },
          ],
        },
      },
      {
        name: "highlight_edges",
        data: { values: edges },
        mark: { type: "rule", color: "#e4cc5c", strokeWidth: 1.6 },
        encoding: {
          y: { value: 0 },
          y2: { value: { expr: "height" } },
          tooltip: [{ field: "label", title: "Selected period" }],
        },
      },
      {
        name: "highlight_badges",
        data: { values: highlights },
        mark: {
          type: "circle",
          size: 400,
          color: "#ffe77a",
          opacity: 1,
          stroke: "#e4cc5c",
          strokeWidth: 1,
        },
        encoding: {
          x: { field: "midpoint", type: "quantitative" },
          // Radius 10 plus the half-pixel border: the bottom touches y = 0.
          y: { value: -10.5 },
          tooltip: [{ field: "label", title: "Selected period" }],
        },
      },
      {
        name: "highlight_numbers",
        data: { values: highlights },
        mark: {
          type: "text",
          color: "#746024",
          font: "system-ui",
          fontSize: 11,
          fontWeight: 600,
          baseline: "middle",
        },
        encoding: {
          x: { field: "midpoint", type: "quantitative" },
          y: { value: -10.5 },
          text: { field: "rank" },
          tooltip: [{ field: "label", title: "Selected period" }],
        },
      },
      {
        name: "published_label",
        data: { values: publishedLabel },
        mark: {
          type: "text",
          text: "published prices ←",
          align: "right",
          baseline: "bottom",
          color: "#555555",
          font: "system-ui",
          fontSize: 11,
        },
        encoding: {
          x: { value: { expr: "clamp(scale('x', datum.minute), 110, width)" } },
          y: { value: highlights.length ? -30 : -8 },
        },
      },
      // Captured once at page load/refresh, never from the forecast issue time.
      ...(now
        ? [
            {
              name: "current_time",
              data: { values: [now] },
              mark: {
                type: "rule" as const,
                color: "#73816e",
                strokeWidth: 1.5,
              },
            },
            {
              data: { values: [now] },
              mark: {
                type: "text" as const,
                align:
                  now.minute > 1200 ? ("right" as const) : ("left" as const),
                baseline: "top" as const,
                dx: now.minute > 1200 ? -5 : 5,
                dy: 1,
                color: "#53654c",
                font: "system-ui",
                fontSize: 11,
              },
              encoding: { y: { value: 0 }, text: { field: "label" } },
            },
          ]
        : []),
    ],
    config: {
      background: "transparent",
      view: { stroke: null },
      axis: {
        labelFont: "system-ui",
        labelFontSize: 11,
        labelColor: "#737871",
        titleFont: "system-ui",
        titleFontSize: 11,
        titleFontWeight: "normal",
        titleColor: "#737871",
        domain: false,
        tickColor: "#cbd1c6",
        gridColor: "#e7e9e0",
        gridDash: [3, 3],
      },
    },
  };
}
