import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
const fixture = JSON.parse(
  readFileSync("fixtures/site/data/forecast.json", "utf8"),
);

test.use({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
});

test("touch reveals a price per chart, dragging updates it and edge labels stay inside", async ({
  page,
}) => {
  await page.goto("/");
  const sliders = page.locator(".price-scrubber");
  await expect(sliders).toHaveCount(7);
  await expect(page.locator(".scrubber-price:visible")).toHaveCount(0);
  const slider = sliders.first();
  await expect(slider).toHaveCSS("touch-action", "pan-y");
  const box = (await slider.boundingBox())!;
  expect(box.width).toBeGreaterThan(250);
  expect(box.height).toBe(110);
  await page.touchscreen.tap(box.x + box.width * 0.26, box.y + 60);
  const slot = fixture.slots.filter(
    (slot: any) => slot.day === fixture.slots[0].day,
  )[12];
  await expect(slider).toHaveAttribute("data-start", slot.start);
  await expect(slider.locator(".scrubber-price")).toHaveText(
    `6am: ${slot.price.toFixed(1)}p/kWh`,
  );
  await expect(sliders.nth(1).locator(".scrubber-price")).toBeHidden();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: box.x + box.width * 0.26, y: box.y + 60 }],
  });
  for (const fraction of [0.4, 0.6, 0.8, 0.99])
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: box.x + box.width * fraction, y: box.y + 60 }],
    });
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await expect(slider).toHaveAttribute("aria-valuenow", "47");
  const labelBox = (await slider.locator(".scrubber-price").boundingBox())!;
  expect(labelBox.x + labelBox.width).toBeLessThanOrEqual(
    box.x + box.width + 1,
  );
  await expect(page.locator("#vg-tooltip-element")).not.toBeVisible();
  await page.screenshot({
    path: "test-results/mobile-scrubber.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(sliders).toHaveCount(0);
});

test("vertical touch scrolling is preserved without revealing the marker", async ({
  page,
}) => {
  await page.goto("/");
  const slider = page.locator(".price-scrubber").first();
  await expect(page.locator(".price-scrubber")).toHaveCount(7);
  const box = (await slider.boundingBox())!;
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: box.x + box.width / 2, y: box.y + 90 }],
  });
  for (const dy of [20, 40, 60, 80])
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: box.x + box.width / 2, y: box.y + 90 - dy }],
    });
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(20);
  await expect(slider.locator(".scrubber-price")).toBeHidden();
});

test("missing and negative prices are honest and keyboard controls work", async ({
  page,
}) => {
  const data = structuredClone(fixture);
  data.slots[0] = {
    ...data.slots[0],
    price: null,
    status: "unavailable",
    policy: "unavailable",
  };
  data.slots[1].price = -5.6;
  await page.route("**/data/forecast.json", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  const slider = page.locator(".price-scrubber").first();
  await expect(page.locator(".price-scrubber")).toHaveCount(7);
  await slider.focus();
  await page.keyboard.press("Home");
  await expect(slider.locator(".scrubber-price")).toHaveText(
    "12am: Unavailable",
  );
  await page.keyboard.press("ArrowRight");
  await expect(slider.locator(".scrubber-price")).toHaveText(
    "12:30am: -5.6p/kWh",
  );
  await page.keyboard.press("Escape");
  await expect(slider.locator(".scrubber-price")).toBeHidden();
});
