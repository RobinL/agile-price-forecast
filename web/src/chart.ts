import type { VisualizationSpec } from "vega-embed";
import type { Slot } from "./data";

// Break the line at missing data, publication boundaries and clock changes.
// Each half-hour price is flat until its interval ends (a step line).
export function chartPoints(slots: Slot[]) {
  const points: {
    minute: number;
    price: number;
    status: string;
    series: number;
    clock: string;
  }[] = [];
  let series = 0;
  let previous: Slot | undefined;
  for (const slot of slots) {
    if (slot.price === null) {
      previous = undefined;
      continue;
    }
    if (
      !previous ||
      previous.status !== slot.status ||
      previous.minute + 30 !== slot.minute ||
      previous.utc_offset_minutes !== slot.utc_offset_minutes
    )
      series++;
    const status =
      slot.status === "published" ? "Published price" : "Model estimate";
    points.push({
      minute: slot.minute,
      price: slot.price,
      status,
      series,
      clock: slot.clock,
    });
    points.push({
      minute: Math.min(slot.minute + 30, 1440),
      price: slot.price,
      status,
      series,
      clock: slot.clock,
    });
    previous = slot;
  }
  return points;
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
): VisualizationSpec {
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v6.json",
    width: "container",
    height: 155,
    autosize: { type: "fit", contains: "padding" },
    padding: { left: 6, right: 12, top: 8, bottom: 5 },
    data: { values: chartPoints(slots) },
    mark: {
      type: "line",
      interpolate: "step-after",
      strokeWidth: 2.5,
      clip: true,
    },
    encoding: {
      x: {
        field: "minute",
        type: "quantitative",
        scale: { domain: [0, 1440], nice: false },
        axis: {
          title: null,
          values: [0, 360, 720, 1080, 1440],
          labelExpr:
            "datum.value === 1440 ? '24:00' : format(floor(datum.value / 60), '02') + ':00'",
          grid: false,
          labelPadding: 9,
        },
      },
      y: {
        field: "price",
        type: "quantitative",
        scale: { domain, nice: false, zero: false },
        axis: {
          title: null,
          tickCount: 4,
          minExtent: 35,
          maxExtent: 35,
          labelPadding: 8,
        },
      },
      color: {
        field: "status",
        type: "nominal",
        scale: {
          domain: ["Published price", "Model estimate"],
          range: ["#215c52", "#b36132"],
        },
        legend: null,
      },
      strokeDash: {
        field: "status",
        type: "nominal",
        scale: {
          domain: ["Published price", "Model estimate"],
          range: [
            [1, 0],
            [6, 4],
          ],
        },
        legend: null,
      },
      detail: { field: "series", type: "nominal" },
      order: { field: "minute", type: "quantitative" },
      tooltip: [
        { field: "clock", title: "Half-hour starting" },
        { field: "price", title: "p/kWh", format: ".2f" },
        { field: "status", title: "Type" },
      ],
    },
    config: {
      background: "transparent",
      view: { stroke: null },
      axis: {
        labelFont: "system-ui",
        labelFontSize: 11,
        labelColor: "#737871",
        domain: false,
        tickColor: "#cbd1c6",
        gridColor: "#e7e9e0",
        gridDash: [3, 3],
      },
    },
  };
}
