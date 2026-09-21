import { test, expect } from "@playwright/test";
for (const width of [375, 1280]) {
  test(`price scale toggle at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.locator(".price-chart svg")).toHaveCount(7);
    const toggle = page.getByLabel("Normalise prices");
    await expect(toggle).toBeChecked();
    const axes = () =>
      page
        .locator('.price-chart svg g[aria-label^="Y-axis"]')
        .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("aria-label")));
    const shared = await axes();
    expect(new Set(shared).size).toBe(1);
    await toggle.uncheck();
    await expect
      .poll(async () => new Set(await axes()).size)
      .toBeGreaterThan(1);
    await expect(page.locator(".price-chart svg")).toHaveCount(7);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({ path: `/tmp/agile-normalise-${width}.png` });
    await toggle.check();
    await expect.poll(axes).toEqual(shared);
  });
}
