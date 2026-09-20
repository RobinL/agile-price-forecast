import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { withPublishedPrices } from "../../web/src/published-prices";
import { parseForecast } from "../../web/src/data";
const fixture = JSON.parse(
  fs.readFileSync("fixtures/site/data/forecast.json", "utf8"),
);

test("official overlays preserve forecasts, timestamps, zero and negative prices", () => {
  const f = parseForecast(structuredClone(fixture));
  f.mode = "live";
  const rates = new Map([
    [Date.parse(f.slots[0].start), 0],
    [Date.parse(f.slots[1].start), -2],
  ]);
  const result = withPublishedPrices(f, rates);
  expect(result.slots[0].price).toBe(0);
  expect(result.slots[1].price).toBe(-2);
  expect(result.slots[1].status).toBe("published");
  expect(result.slots[2]).toEqual(f.slots[2]);
  expect(result.issued_at).toBe(f.issued_at);
  expect(withPublishedPrices({ ...f, mode: "demo" }, rates).slots).toEqual(
    f.slots,
  );
});

test("live page independently retrieves selected-region prices and survives API failure", async ({
  page,
}) => {
  const f = structuredClone(fixture);
  f.mode = "live";
  f.regions = {
    G: { name: "North West", prices: f.slots.map((s: any) => s.price) },
    C: { name: "London", prices: f.slots.map((s: any) => s.price) },
  };
  await page.route("**/data/forecast.json", (route) =>
    route.fulfill({ json: f }),
  );
  let calls = 0;
  await page.route("https://api.octopus.energy/**", async (route) => {
    calls++;
    if (route.request().url().includes("-C/"))
      return route.fulfill({ status: 503 });
    await route.fulfill({
      json: {
        results: f.slots.map((s: any) => ({
          valid_from: s.start,
          valid_to: s.end,
          value_inc_vat: 1.23,
        })),
      },
    });
  });
  await page.goto("/");
  await expect.poll(() => calls).toBe(1);
  await expect(page.locator(".price-chart svg").first()).toBeVisible();
  await expect(page.locator("#days")).toContainText("published prices");
  await page.getByLabel("Select region").selectOption("C");
  await expect.poll(() => calls).toBe(2);
  await expect(page.locator(".price-chart svg").first()).toBeVisible();
  await expect(page.locator("#notice")).not.toContainText("Unable");
});
