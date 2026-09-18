import { expect, test } from "@playwright/test";
import { chartPoints } from "../../web/src/chart";
import { dayTitle, type Slot } from "../../web/src/data";

test("seven days ahead in aligned daily charts, explicit demo status, local requests only", async ({
  page,
}) => {
  const external: string[] = [];
  page.on("request", (request) => {
    if (!request.url().startsWith("http://127.0.0.1:5174/"))
      external.push(request.url());
  });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(8);
  await expect(page.locator(".day-card").last()).toContainText(
    "Partial final day",
  );
  await expect(page.locator(".day-card").last()).not.toContainText(
    "Clock change",
  );
  await expect(
    page.getByRole("heading", { name: "Today — Friday" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Tomorrow — Saturday" }),
  ).toBeVisible();
  await expect(page.locator("#notice")).toContainText("Made-up data");
  for (const chart of await page.locator(".price-chart").all()) {
    await expect(chart.getByText("00:00", { exact: true })).toBeVisible();
    await expect(chart.getByText("24:00", { exact: true })).toBeVisible();
  }
  expect(external).toEqual([]);
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
});

test("mobile charts fit without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(8);
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

test("clock changes and missing intervals do not get joined across a gap", () => {
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
  const points = chartPoints([
    base,
    { ...base, minute: 90 },
    { ...base, utc_offset_minutes: 0, clock: "01:00 GMT" },
    { ...base, price: null, status: "unavailable", minute: 90 },
    { ...base, minute: 120, utc_offset_minutes: 0 },
  ]);
  expect(new Set(points.map((p) => p.series)).size).toBe(3);
  expect(dayTitle("2026-10-26", "2026-10-25")).toBe("Tomorrow — Monday");
});

test("the development server cannot serve repository internals", async ({
  request,
}) => {
  const path = `${process.cwd()}/.git/HEAD`;
  const response = await request.get(`/@fs/${path}`);
  expect(response.status()).toBe(403);
});

test("research comparison renders on mobile with its limited evaluation scope", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/data/forecast.json", async (route) => {
    const response = await route.fetch();
    const f = await response.json();
    f.model.recipe_id = "level-shape-v1";
    f.model.name = "Research ensemble";
    f.accuracy = {
      kind: "research-comparison",
      recipe_id: "level-shape-v1",
      recipe_fingerprint: "synthetic-test",
      evaluated_as_of: f.issued_at,
      target_start: f.issued_at,
      target_end: f.horizon_end,
      issue_days: 1,
      description:
        "Synthetic comparison only; not the live AgilePredict service.",
      comparison: [
        { model: "AP0_60", mae_p_kwh: 5, slots: 48 },
        { model: "candidate", mae_p_kwh: 6, slots: 48 },
      ],
      by_horizon: [],
    };
    await route.fulfill({ json: f });
  });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(8);
  await page
    .getByText("Forecast notes and accuracy comparison", { exact: true })
    .click();
  await expect(page.locator(".accuracy-table")).toContainText(
    "AgilePredict recipe · 60 days",
  );
  await expect(page.locator("#details")).toContainText(
    "do not measure accuracy across the full seven days",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
