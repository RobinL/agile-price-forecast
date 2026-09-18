import embed, { type Result } from "vega-embed";
import { chartSpec, priceDomain, PRICE_COLOURS } from "./chart";
import { cheapestPeriods, type CheapPeriod } from "./cheap-periods";
import {
  chartDays,
  dayTitle,
  londonDay,
  londonTime,
  parseForecast,
  type Forecast,
} from "./data";
import "./style.css";
import { attachPriceScrubber } from "./price-scrubber";
import { setupAnalytics } from "./analytics";

setupAnalytics();

const compactLayout = window.matchMedia("(max-width: 600px)");
const views: Result[] = [];
const scrubberCleanups: (() => void)[] = [];
let current: Forecast | undefined;
let currentLoadedAt: Date | undefined;
let renderVersion = 0;
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
      ? "Demonstration"
      : f.mode === "replay"
        ? "Historical replay"
        : ageHours > 2
          ? "Stale forecast"
          : "Latest forecast";
  const description =
    f.mode === "demo"
      ? "Made-up data"
      : f.mode === "replay"
        ? "Saved historical example"
        : "";
  notice.replaceChildren(
    element("strong", "notice-label", label),
    document.createTextNode(description ? ` · ${description} · ` : " · "),
    element("time", "issue-time", `Issued ${formatDate(f.issued_at)} London`),
  );
}

function showPeriods(
  periods: CheapPeriod[],
  enabled: boolean,
  count: number,
  days: string[],
) {
  const results = byId("period-results");
  results.replaceChildren();
  if (!enabled) return;
  if (periods.length < count)
    results.append(
      element(
        "p",
        "period-help",
        periods.length
          ? `Only ${periods.length} complete periods available.`
          : "No complete future periods are available for this length.",
      ),
    );
  const weekday = (day: string) =>
    new Intl.DateTimeFormat("en-GB", {
      weekday: "short",
      timeZone: "Europe/London",
    }).format(new Date(`${day}T12:00:00Z`));
  // Include overnight endpoints when deciding whether a weekday is ambiguous.
  const mentionedDays = [
    ...new Set([
      ...days,
      ...periods.flatMap((period) => [
        londonDay(new Date(period.start)),
        londonDay(new Date(period.end)),
      ]),
    ]),
  ].sort();
  const dayName = (day: string) => {
    const name = weekday(day);
    const matches = mentionedDays.filter((date) => weekday(date) === name);
    return matches.length > 1
      ? `${day === matches[0] ? "This" : "Next"} ${name}`
      : name;
  };
  const clock = (value: string) =>
    new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/London",
      hourCycle: "h23",
    }).format(new Date(value));
  for (const [index, period] of periods.entries()) {
    const startDay = londonDay(new Date(period.start));
    const endDay = londonDay(new Date(period.end));
    const timeRange = `${dayName(startDay)} ${clock(period.start)}–${startDay === endDay ? "" : `${dayName(endDay)} `}${clock(period.end)}`;
    const link = document.createElement("a");
    link.className = "period-choice";
    link.href = `#day-${startDay}`;
    link.title = `Average price: ${period.meanPrice.toFixed(2)}p/kWh`;
    link.append(element("span", "period-rank", String(index + 1)));
    const text = element("span", "");
    text.append(
      element("span", "period-time", timeRange),
      document.createTextNode(" · "),
    );
    text.append(
      element(
        "span",
        "period-price",
        `${period.meanPrice.toFixed(2)}p/kWh${period.includesPredictions ? " (est.)" : ""}`,
      ),
    );
    link.append(text);
    results.append(link);
  }
}

async function render(f: Forecast, loadedAt: Date) {
  const version = ++renderVersion;
  scrubberCleanups.splice(0).forEach((cleanup) => cleanup());
  views.forEach((view) => view.finalize());
  views.length = 0;
  updateNotice(f);
  const reference = londonDay(
    f.mode === "live" ? loadedAt : new Date(f.issued_at),
  );
  const domain = priceDomain(f.slots);
  const days = chartDays(f.slots);
  const enabled = (byId("highlight-enabled") as HTMLInputElement).checked;
  const countControl = byId("period-count") as HTMLSelectElement;
  const hoursControl = byId("period-hours") as HTMLSelectElement;
  countControl.disabled = hoursControl.disabled = !enabled;
  byId("highlight-legend").hidden = !enabled;
  byId("period-count-field").hidden = !enabled;
  byId("period-hours-field").hidden = !enabled;
  const count = Number(countControl.value);
  const periods = enabled
    ? cheapestPeriods(
        f.slots.filter((s) => days.includes(s.day)),
        count,
        Number(hoursControl.value),
        f.mode === "live" ? loadedAt : new Date(f.issued_at),
      )
    : [];
  showPeriods(periods, enabled, count, days);
  byId("days").replaceChildren();
  for (const day of days) {
    const slots = f.slots.filter((s) => s.day === day);
    const section = element("section", "day-card");
    section.id = `day-${day}`;
    const heading = element("div", "day-heading");
    heading.append(element("h2", "day-title", dayTitle(day, reference)));
    section.append(heading);
    const chart = element("div", "price-chart");
    chart.setAttribute(
      "aria-label",
      `${dayTitle(day, reference)} electricity prices`,
    );
    section.append(chart);
    const missing = slots.filter((s) => s.status === "unavailable").length;
    if (missing)
      section.append(
        element(
          "p",
          "day-coverage",
          `${missing} ${missing === 1 ? "half-hour" : "half-hours"} unavailable — gaps are left blank`,
        ),
      );
    if (new Set(slots.map((s) => s.utc_offset_minutes)).size > 1)
      section.append(
        element(
          "p",
          "clock-note",
          "Clocks change on this day. Repeated times share a half-hour position side by side; hover to distinguish BST and GMT.",
        ),
      );
    byId("days").append(section);
    const result = await embed(
      chart,
      chartSpec(
        slots,
        domain,
        f.mode === "live" && day === londonDay(loadedAt)
          ? londonTime(loadedAt)
          : undefined,
        periods,
        compactLayout.matches,
      ),
      {
        actions: false,
        renderer: "svg",
        ...(compactLayout.matches ? { tooltip: false } : {}),
      },
    );
    if (version !== renderVersion) {
      result.finalize();
      return;
    }
    views.push(result);
    if (compactLayout.matches)
      scrubberCleanups.push(attachPriceScrubber(chart, result.view, slots));
  }
}

async function load() {
  const loadedAt = new Date();
  try {
    const response = await fetch(
      `${import.meta.env.BASE_URL}data/forecast.json`,
    );
    if (!response.ok)
      throw new Error("The forecast file is not available yet.");
    const next = parseForecast(await response.json());
    current = next;
    currentLoadedAt = loadedAt;
    await render(next, loadedAt);
  } catch (error) {
    byId("notice").className = "notice caution";
    byId("notice").textContent =
      `${error instanceof Error ? error.message : "Unable to load forecast."} Please try again later.`;
  }
}

const gradient = element("div", "price-gradient");
const firstPrice = PRICE_COLOURS[0].price;
const lastPrice = PRICE_COLOURS[PRICE_COLOURS.length - 1].price;
gradient.style.backgroundImage = `linear-gradient(to right, ${PRICE_COLOURS.map(
  (stop) =>
    `${stop.color} ${(100 * (stop.price - firstPrice)) / (lastPrice - firstPrice)}%`,
).join(", ")})`;
const colourLabels = element("div", "price-scale-labels");
colourLabels.append(
  ...PRICE_COLOURS.map((stop) => element("span", "", stop.label)),
);
byId("price-legend").replaceChildren(gradient, colourLabels);
for (const id of ["highlight-enabled", "period-count", "period-hours"]) {
  byId(id).addEventListener("change", () => {
    if (current && currentLoadedAt) void render(current, currentLoadedAt);
  });
}

compactLayout.addEventListener("change", () => {
  if (current && currentLoadedAt) void render(current, currentLoadedAt);
});

void load();
setInterval(
  () => {
    if (current) updateNotice(current);
    if (current?.mode === "live" && document.visibilityState === "visible")
      void load();
  },
  10 * 60 * 1000,
);
