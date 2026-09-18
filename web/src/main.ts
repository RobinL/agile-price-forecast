import embed, { type Result } from "vega-embed";
import { chartSpec, priceDomain } from "./chart";
import { dayTitle, londonDay, parseForecast, type Forecast } from "./data";
import "./style.css";

const views: Result[] = [];
let current: Forecast | undefined;
const byId = (id: string) => document.getElementById(id)!;
const formatDate = (value: string) =>
  new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/London",
  }).format(new Date(value));
function element(tag: string, className: string, text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

function updateNotice(f: Forecast) {
  const notice = byId("notice");
  const ageHours = (Date.now() - Date.parse(f.issued_at)) / 3600000;
  notice.className =
    "notice" + (f.mode !== "live" || ageHours > 2 ? " caution" : "");
  const label =
    f.mode === "demo"
      ? "DEMONSTRATION"
      : f.mode === "replay"
        ? "HISTORICAL REPLAY"
        : ageHours > 2
          ? "STALE FORECAST"
          : "LATEST FORECAST";
  const description =
    f.mode === "demo"
      ? "Made-up data to explore the site. Day labels refer to the example date."
      : f.mode === "replay"
        ? "A saved historical example. Day labels refer to its original issue date."
        : ageHours > 2
          ? "The last successful update is over two hours old. Treat estimates as stale."
          : "Published prices are confirmed; the dashed lines are estimates.";
  notice.replaceChildren(
    element("strong", "notice-label", label),
    element("span", "notice-copy", description),
    element("time", "issue-time", `Issued ${formatDate(f.issued_at)} London`),
  );
}

async function render(f: Forecast) {
  views.forEach((view) => view.finalize());
  views.length = 0;
  updateNotice(f);
  const reference = londonDay(
    f.mode === "live" ? new Date() : new Date(f.issued_at),
  );
  const domain = priceDomain(f.slots);
  const days = [...new Set(f.slots.map((s) => s.day))];
  byId("days").replaceChildren();
  for (const day of days) {
    const slots = f.slots.filter((s) => s.day === day);
    const section = element("section", "day-card");
    const heading = element("div", "day-heading");
    heading.append(element("h2", "day-title", dayTitle(day, reference)));
    heading.append(
      element(
        "span",
        "day-date",
        new Intl.DateTimeFormat("en-GB", {
          day: "numeric",
          month: "long",
          timeZone: "Europe/London",
        }).format(new Date(`${day}T12:00:00Z`)),
      ),
    );
    section.append(heading);
    const chart = element("div", "price-chart");
    chart.setAttribute(
      "aria-label",
      `${dayTitle(day, reference)} electricity prices`,
    );
    section.append(chart);
    const values = slots.flatMap((s) => (s.price === null ? [] : [s.price]));
    const missing = slots.filter((s) => s.status === "unavailable").length;
    const bottom = element("div", "day-bottom");
    bottom.append(
      element(
        "span",
        "day-range",
        values.length
          ? `Shown range  ${Math.min(...values).toFixed(1)}–${Math.max(...values).toFixed(1)} p/kWh`
          : "No prices available",
      ),
    );
    bottom.append(
      element(
        "span",
        "day-coverage",
        missing
          ? `${missing} half-hours unavailable — gaps are left blank`
          : `${slots.length} half-hours · ${slots.filter((s) => s.status === "predicted").length} estimated`,
      ),
    );
    section.append(bottom);
    if (new Set(slots.map((s) => s.utc_offset_minutes)).size > 1)
      section.append(
        element(
          "p",
          "clock-note",
          "Clocks change on this day. Hover to distinguish BST and GMT; the line breaks at the clock change.",
        ),
      );
    if (slots[slots.length - 1].minute < 1410)
      section.append(
        element(
          "p",
          "clock-note",
          "Partial final day: the seven-day forecast ends here.",
        ),
      );
    byId("days").append(section);
    views.push(
      await embed(chart, chartSpec(slots, domain), {
        actions: false,
        renderer: "svg",
      }),
    );
  }
  const details = byId("details");
  details.replaceChildren(...f.notes.map((note) => element("p", "", note)));
  details.append(
    element(
      "p",
      "",
      `${f.model.name}; ${f.model.training_rows.toLocaleString()} training intervals. Training cutoff: ${formatDate(f.model.trained_as_of)} London.`,
    ),
  );
  byId("model-summary").textContent =
    f.model.recipe_id === "level-shape-v1"
      ? "Several tree models combine demand, renewable generation, available capacity and calendar patterns. A separate adjustment refines hours 48–72 ahead. Later days remain experimental."
      : "This example uses a small linear model: demand, wind, solar and the daily pattern each add or subtract an adjustment.";
  if (f.accuracy && "comparison" in f.accuracy) {
    const labels: Record<string, string> = {
      linear: "Linear baseline",
      AP0_60: "AgilePredict recipe · 60 days",
      AP0_90: "AgilePredict recipe · 90 days",
      prediction: "Underlying ensemble",
      candidate: "Research model",
    };
    details.append(
      element(
        "p",
        "",
        "Historical comparison for unknown prices 48–72 hours ahead. Lower average error is better.",
      ),
    );
    const table = element("table", "accuracy-table");
    const head = element("tr", "");
    head.append(
      element("th", "", "Model"),
      element("th", "", "Error · p/kWh"),
      element("th", "", "Matched slots"),
    );
    table.append(head);
    for (const row of f.accuracy.comparison) {
      const tr = element("tr", "");
      tr.append(
        element("td", "", labels[row.model] ?? row.model),
        element(
          "td",
          "",
          row.mae_p_kwh === null ? "Not measured" : row.mae_p_kwh.toFixed(2),
        ),
        element("td", "", row.slots.toLocaleString()),
      );
      table.append(tr);
    }
    details.append(table, element("p", "", f.accuracy.description));
    details.append(
      element(
        "p",
        "",
        `Evaluation targets: ${formatDate(f.accuracy.target_start)} to ${formatDate(f.accuracy.target_end)} London. These scores do not measure accuracy across the full seven days.`,
      ),
    );
  } else if (f.accuracy) {
    details.append(
      element(
        "p",
        "",
        `Linear baseline: average absolute error ${f.accuracy.model_mae_p_kwh.toFixed(2)} p/kWh, compared with ${f.accuracy.week_earlier_mae_p_kwh.toFixed(2)} p/kWh for the week-earlier price (${f.accuracy.slots.toLocaleString()} matched slots). ${f.accuracy.description}`,
      ),
    );
  } else {
    details.append(
      element(
        "p",
        "",
        "No matching measured accuracy is attached to this model.",
      ),
    );
  }
}

async function load() {
  try {
    const response = await fetch(
      `${import.meta.env.BASE_URL}data/forecast.json`,
    );
    if (!response.ok)
      throw new Error("The forecast file is not available yet.");
    const next = parseForecast(await response.json());
    await render(next);
    current = next;
  } catch (error) {
    byId("notice").className = "notice caution";
    byId("notice").textContent =
      `${error instanceof Error ? error.message : "Unable to load forecast."} Please try again later.`;
  }
}

void load();
setInterval(
  () => {
    if (current) updateNotice(current);
    if (current?.mode === "live" && document.visibilityState === "visible")
      void load();
  },
  10 * 60 * 1000,
);
