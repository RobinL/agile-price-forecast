import { expect, test } from "@playwright/test";

const ID = "G-94373ZKHEE";

test("local development does not load Google Analytics", async ({ page }) => {
  const requests: string[] = [];
  await page.route(/googletagmanager\.com|google-analytics\.com/, (route) => {
    requests.push(route.request().url());
    return route.abort();
  });
  await page.goto("/");
  await expect(page.locator(".price-chart svg")).toHaveCount(7);
  expect(requests).toEqual([]);
  await expect(page.locator("#google-analytics")).toHaveCount(0);
});

test("production analytics loads once without a prompt and does not block charts", async ({
  page,
}) => {
  const requests: string[] = [];
  await page.route(/googletagmanager\.com|google-analytics\.com/, (route) => {
    requests.push(route.request().url());
    // No test visit ever reaches the real Analytics property.
    return route.abort();
  });
  await page.goto("/");
  await page.evaluate(async () => {
    history.replaceState(
      null,
      "",
      "/agile-price-forecast/?private=test#selection",
    );
    const { setupAnalytics } = await import("/src/analytics.ts");
    setupAnalytics(true);
    setupAnalytics(true);
  });
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toBe(`https://www.googletagmanager.com/gtag/js?id=${ID}`);
  const commands = await page.evaluate(() =>
    Array.from((window as any).dataLayer, (entry: any) => Array.from(entry)),
  );
  const config = commands.find((entry: any) => entry[0] === "config") as any[];
  expect(config[1]).toBe(ID);
  expect(config[2]).toMatchObject({
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    cookie_prefix: "agile_forecast",
    cookie_path: "/agile-price-forecast/",
    page_location: "http://127.0.0.1:5174/agile-price-forecast/",
  });
  await expect(page.locator("#analytics-choice")).toHaveCount(0);
  await expect(page.locator(".price-chart svg")).toHaveCount(7);
});
