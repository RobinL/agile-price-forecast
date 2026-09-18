import { expect, test } from "@playwright/test";
import { chartBars } from "../../web/src/chart";
import { chartDays, dayTitle, type Slot } from "../../web/src/data";

test.use({ timezoneId: "America/Los_Angeles" });

test("seven days ahead in aligned daily charts, explicit demo status, local requests only", async ({
  page,
}) => {
  const external: string[] = [];
  page.on("request", (request) => {
    if (!request.url().startsWith("http://127.0.0.1:5174/"))
      external.push(request.url());
  });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(7);
  await expect(page.locator(".day-card").last()).toContainText(
    "Thursday 24th September",
  );
  await expect(
    page.getByRole("heading", {
      name: "Agile price forecast (beta)",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".day-card").last()).not.toContainText(
    "Clock change",
  );
  await expect(
    page.getByRole("heading", { name: "Today - Friday 18th September" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Tomorrow - Saturday 19th September" }),
  ).toBeVisible();
  await expect(page.locator("#notice")).toContainText("Made-up data");
  for (const chart of await page.locator(".price-chart").all()) {
    await expect(chart.getByText("12am", { exact: true })).toHaveCount(2);
    await expect(chart.getByText("12pm", { exact: true })).toBeVisible();
    await expect(chart.getByText("0p/kWh", { exact: true })).toBeVisible();
    await expect(chart.getByText("Pence/kWh", { exact: true })).toHaveCount(0);
  }
  expect(external).toEqual([]);
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
});

test("mobile charts fit without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(7);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
});

test("a missing forecast is reported instead of showing invented data", async ({
  page,
}) => {
  await page.route("**/data/forecast.json", (route) =>
    route.fulfill({ status: 404, body: "missing" }),
  );
  await page.goto("/");
  await expect(page.locator("#notice")).toContainText("not available");
  await expect(page.locator(".day-card")).toHaveCount(0);
});

test("repeated clock intervals get distinct bars and missing prices stay blank", () => {
  const base: Slot = {
    start: "2026-10-25T00:00:00Z",
    end: "2026-10-25T00:30:00Z",
    day: "2026-10-25",
    minute: 60,
    clock: "01:00 BST",
    utc_offset_minutes: 60,
    price: 10,
    status: "predicted",
    policy: "ensemble-experimental",
  };
  const bars = chartBars([
    base,
    { ...base, minute: 90 },
    { ...base, utc_offset_minutes: 0, clock: "01:00 GMT" },
    { ...base, price: null, status: "unavailable", minute: 90 },
    { ...base, minute: 120, utc_offset_minutes: 0 },
  ]);
  expect(bars).toHaveLength(4);
  expect(new Set(bars.map((b) => b.minute)).size).toBe(4);
  expect(bars[0].end_minute).toBeLessThan(bars[2].minute);
  expect(dayTitle("2026-10-26", "2026-10-25")).toBe(
    "Tomorrow - Monday 26th October",
  );
});

test("the development server cannot serve repository internals", async ({
  request,
}) => {
  const path = `${process.cwd()}/.git/HEAD`;
  const response = await request.get(`/@fs/${path}`);
  expect(response.status()).toBe(403);
});

test("today marks the London time at load and refresh, with gaps only where missing", async ({
  page,
}) => {
  // Browser runs in a different timezone; the marker must still use London time.
  await page.clock.setFixedTime(new Date("2026-09-18T12:17:30Z"));
  await page.route("**/data/forecast.json", async (route) => {
    const response = await route.fetch();
    const f = await response.json();
    f.mode = "live";
    f.slots[0] = {
      ...f.slots[0],
      price: null,
      status: "unavailable",
      policy: "unavailable",
    };
    await route.fulfill({ json: f });
  });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(7);
  const today = page.locator(".day-card").first();
  await expect(today.getByText("Now 13:17", { exact: true })).toBeVisible();
  await expect(page.locator(".day-coverage")).toHaveCount(1);
  await expect(today).toContainText("1 half-hour unavailable");
  await expect(
    page.getByText(
      /Shown range|Forecast notes and accuracy comparison|half-hours ·/,
    ),
  ).toHaveCount(0);
  const rule = today.locator(".current_time_marks line");
  await expect(rule).toHaveCount(1);
  // This is the London clock minute, not the browser timezone or issue time.
  await expect(rule).toHaveAttribute("aria-label", "minute: 797.5");
  await page.clock.setFixedTime(new Date("2026-09-18T13:42:00Z"));
  await page.reload();
  await expect(today.getByText("Now 14:42", { exact: true })).toBeVisible();
  await expect(page.locator(".day-card").nth(1).getByText(/^Now /)).toHaveCount(
    0,
  );
});

test("full clock-change days stay visible and partial final dates are omitted", () => {
  for (const [start, count] of [
    ["2026-03-29T00:00:00Z", 46],
    ["2026-10-24T23:00:00Z", 50],
  ] as const) {
    const first = new Date(start);
    const slots: Slot[] = Array.from({ length: count }, (_, i) => {
      const date = new Date(first.getTime() + i * 1800000);
      const parts = new Intl.DateTimeFormat("en-GB", {
        timeZone: "Europe/London",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(date);
      const part = (type: string) =>
        Number(parts.find((p) => p.type === type)!.value);
      return {
        start: date.toISOString(),
        end: new Date(date.getTime() + 1800000).toISOString(),
        day: count === 46 ? "2026-03-29" : "2026-10-25",
        minute: part("hour") * 60 + part("minute"),
        clock: "",
        utc_offset_minutes: 0,
        price: null,
        status: "unavailable",
        policy: "unavailable",
      };
    });
    expect(chartDays(slots)).toEqual([slots[0].day]);
    expect(chartDays(slots.slice(0, -1))).toEqual([]);
  }
});

test("cheapest-period controls update bars across the whole forecast without fetching again", async ({
  page,
}) => {
  let fetches = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("data/forecast.json")) fetches++;
  });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(7);
  await expect(
    page.getByRole("checkbox", { name: "Highlight cheapest periods" }),
  ).not.toBeChecked();
  await expect(page.locator("#period-count")).toBeHidden();
  await expect(page.locator("#period-hours")).toBeHidden();
  await expect(page.locator(".period-choice")).toHaveCount(0);
  await page
    .getByRole("checkbox", { name: "Highlight cheapest periods" })
    .check();
  await expect(
    page.getByRole("combobox", { name: "Number of cheapest periods" }),
  ).toHaveValue("2");
  await expect(page.locator("#period-hours")).toHaveValue("3");
  await expect(page.locator(".period-choice")).toHaveCount(2);
  // Retain the overnight rendering check using one two-hour period.
  await page.locator("#period-count").selectOption("1");
  await page.locator("#period-hours").selectOption("2");
  await expect(page.locator(".period-choice")).toHaveCount(1);
  // The cheapest fixture period straddles midnight: each day needs its own
  // boundaries and badge, with the same rank on both charts.
  await expect(page.locator(".cheap_periods_marks path")).toHaveCount(2);
  await expect(page.locator(".highlight_badges_marks path")).toHaveCount(2);
  await expect(page.locator(".highlight_edges_marks line")).toHaveCount(4);
  await expect(page.locator(".highlight_numbers_marks text")).toHaveText([
    "1",
    "1",
  ]);
  await expect(page.locator(".price_bars_marks path").first()).toBeVisible();
  await page
    .getByRole("combobox", { name: "Number of cheapest periods" })
    .selectOption("5");
  await expect(page.locator(".period-choice")).toHaveCount(5);
  const numbers = page.locator(".highlight_numbers_marks text");
  await expect
    .poll(async () => [...new Set(await numbers.allTextContents())].sort())
    .toEqual(["1", "2", "3", "4", "5"]);
  const regions = await numbers.count();
  await expect(page.locator(".cheap_periods_marks path")).toHaveCount(regions);
  await expect(page.locator(".highlight_badges_marks path")).toHaveCount(
    regions,
  );
  await expect(page.locator(".highlight_edges_marks line")).toHaveCount(
    2 * regions,
  );
  const previousPeriods = await page
    .locator(".period-choice")
    .allTextContents();
  await page.getByRole("combobox", { name: "Period length" }).selectOption("3");
  await expect
    .poll(() => page.locator(".period-choice").allTextContents())
    .not.toEqual(previousPeriods);
  await expect
    .poll(async () => [...new Set(await numbers.allTextContents())].sort())
    .toEqual(["1", "2", "3", "4", "5"]);
  await page
    .getByRole("checkbox", { name: "Highlight cheapest periods" })
    .uncheck();
  await expect(page.locator(".cheap_periods_marks path")).toHaveCount(0);
  await expect(page.locator(".highlight_edges_marks line")).toHaveCount(0);
  await expect(page.locator(".highlight_numbers_marks text")).toHaveCount(0);
  await expect(page.locator(".period-choice")).toHaveCount(0);
  await expect(page.locator("#period-count")).toBeHidden();
  await expect(page.locator("#period-hours")).toBeHidden();
  expect(fetches).toBe(1);
});

test("am/pm labels adapt on resize, stay aligned and do not overlap", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(7);
  const labels = page
    .locator(".price-chart")
    .first()
    .locator(".role-axis-label text")
    .filter({ hasText: /(?:am|pm)$/ });
  await expect(labels).toHaveCount(25);
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(labels).toHaveCount(
      width === 1280 ? 25 : width === 768 ? 13 : width === 320 ? 5 : 9,
    );
    // Each of the seven Vega views handles the resize independently.
    await expect(
      page
        .locator(".price-chart .role-axis-label text")
        .filter({ hasText: /(?:am|pm)$/ }),
    ).toHaveCount(
      (width === 1280 ? 25 : width === 768 ? 13 : width === 320 ? 5 : 9) * 7,
    );
    const charts = await page.locator(".price-chart").evaluateAll((charts) =>
      charts.map((chart) => {
        const labels = [
          ...chart.querySelectorAll(".role-axis-label text"),
        ].filter((label) => /(?:am|pm)$/.test(label.textContent ?? ""));
        const bounds = labels.map((label) => label.getBoundingClientRect());
        return {
          labels: labels.map((label) => label.textContent),
          overlap: bounds
            .slice(1)
            .some((box, index) => bounds[index].right > box.left),
        };
      }),
    );
    for (const chart of charts) {
      expect(chart.overlap).toBe(false);
      expect(chart.labels).toEqual(charts[0].labels);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
});
