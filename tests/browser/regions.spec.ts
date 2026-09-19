import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { forRegion, parseForecast } from "../../web/src/data";
const fixture = JSON.parse(
  fs.readFileSync("fixtures/site/data/forecast.json", "utf8"),
);
for (const width of [375, 1280]) {
  test(`region selection and compact status at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const f = structuredClone(fixture);
    f.regions = {
      G: {
        name: "North West England",
        prices: f.slots.map((s: any) => s.price),
      },
      C: {
        name: "London",
        prices: f.slots.map((s: any) =>
          s.price === null ? null : s.price + 2,
        ),
      },
    };
    await page.route("**/data/forecast.json", (route) =>
      route.fulfill({ json: f }),
    );
    await page.goto("/");
    await expect(page.locator(".price-chart svg").first()).toBeVisible();
    await expect(page.locator("#notice")).toContainText("issued");
    await page.getByLabel("Select region").selectOption("C");
    await expect(page.locator(".price-chart svg").first()).toBeVisible();
    await expect(page.getByLabel("Select region")).toHaveValue("C");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({ path: `/tmp/agile-regions-${width}.png` });
    await page.reload();
    await expect(page.getByLabel("Select region")).toHaveValue("C");
  });
}

test("regional prices drive slots and do not inherit regional accuracy claims", () => {
  const f = parseForecast(structuredClone(fixture));
  f.regions = {
    C: {
      name: "London",
      prices: f.slots.map((s) => (s.price === null ? null : s.price + 2)),
    },
  };
  const changed = forRegion(f, "C");
  const i = f.slots.findIndex((s) => s.price !== null);
  expect(changed.slots[i].price).toBe(f.slots[i].price! + 2);
  expect(changed.accuracy).toBeNull();
  expect(f.region).toBe("G");
  f.regions.C.prices[i] = null;
  expect(forRegion(f, "C").slots[i].status).toBe("unavailable");
});
