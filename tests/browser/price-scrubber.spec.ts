import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { chartDays, type Slot } from "../../web/src/data";
const fixture = JSON.parse(
  readFileSync("fixtures/site/data/forecast.json", "utf8"),
);
const daySlots = (day: string): Slot[] =>
  fixture.slots.filter((slot: Slot) => slot.day === day);
const cheapestSlot = (slots: Slot[]) =>
  slots
    .filter((slot) => slot.price !== null)
    .reduce((best, slot) => (slot.price! < best.price! ? slot : best));

test.use({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
});

test("each chart starts at its minimum; touch scans prices and edge labels stay inside", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Show past prices").check();
  const sliders = page.locator(".price-scrubber");
  await expect(sliders).toHaveCount(7);
  await expect(page.locator(".scrubber-price:not([hidden])")).toHaveCount(7);
  const days = chartDays(fixture.slots);
  for (const [index, day] of days.entries()) {
    const cheapest =
      index === 0
        ? daySlots(day).find(
            (s) =>
              Date.parse(s.start) <= Date.parse(fixture.issued_at) &&
              Date.parse(s.end) > Date.parse(fixture.issued_at),
          )!
        : cheapestSlot(daySlots(day));
    await expect(sliders.nth(index)).toHaveAttribute(
      "data-start",
      cheapest.start,
    );
    await expect(sliders.nth(index).locator(".scrubber-price")).toContainText(
      `${cheapest.price!.toFixed(1)}p/kWh`,
    );
  }
  await page.screenshot({
    path: "test-results/mobile-price-readouts.png",
  });
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
  await expect(sliders.nth(1)).toHaveAttribute(
    "data-start",
    cheapestSlot(daySlots(days[1])).start,
  );
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
  await expect(sliders).toHaveCount(7);
  await expect(sliders.first().locator(".scrubber-price")).toContainText("–");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(sliders.first().locator(".scrubber-price")).not.toContainText(
    "–",
  );
});

test("vertical touch scrolling preserves the initial minimum", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Show past prices").check();
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
  await expect(slider).toHaveAttribute(
    "data-start",
    daySlots(fixture.slots[0].day).find(
      (s) => Date.parse(s.start) === Date.parse(fixture.issued_at),
    )!.start,
  );
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
  await page.getByLabel("Show past prices").check();
  const slider = page.locator(".price-scrubber").first();
  await expect(page.locator(".price-scrubber")).toHaveCount(7);
  await expect(slider).toHaveAttribute("data-start", data.slots[20].start);
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
  await expect(slider).toHaveAttribute("data-start", data.slots[20].start);
  await expect(slider.locator(".scrubber-price")).toBeVisible();
});

test("a day with no prices starts with an unavailable readout", async ({
  page,
}) => {
  const data = structuredClone(fixture);
  for (const slot of data.slots.filter(
    (slot: Slot) => slot.day === data.slots[0].day,
  )) {
    slot.price = null;
    slot.status = slot.policy = "unavailable";
  }
  await page.route("**/data/forecast.json", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  const slider = page.locator(".price-scrubber").first();
  await expect(slider).toHaveAttribute("data-start", data.slots[20].start);
  await expect(slider.locator(".scrubber-price")).toHaveText(
    "Now: 10am: Unavailable",
  );
});

test.describe("desktop readouts", () => {
  test.use({
    viewport: { width: 1280, height: 1000 },
    isMobile: false,
    hasTouch: false,
    timezoneId: "America/Los_Angeles",
  });

  test("defaults to each day's minimum and mouse hover shows the full time slot", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByLabel("Show past prices").check();
    const sliders = page.locator(".price-scrubber");
    await expect(sliders).toHaveCount(7);
    const days = chartDays(fixture.slots);
    for (const [index, day] of days.entries()) {
      const cheapest =
        index === 0
          ? daySlots(day).find(
              (s) =>
                Date.parse(s.start) <= Date.parse(fixture.issued_at) &&
                Date.parse(s.end) > Date.parse(fixture.issued_at),
            )!
          : cheapestSlot(daySlots(day));
      await expect(sliders.nth(index)).toHaveAttribute(
        "data-start",
        cheapest.start,
      );
      await expect(sliders.nth(index).locator(".scrubber-price")).toContainText(
        `${cheapest.price!.toFixed(1)}p/kWh`,
      );
    }
    await page.screenshot({
      path: "test-results/desktop-price-readouts.png",
    });
    const slider = sliders.first();
    const box = (await slider.boundingBox())!;
    const slot = daySlots(days[0])[12];
    await page.mouse.move(box.x + box.width * 0.26, box.y + 60);
    await expect(slider).toHaveAttribute("data-start", slot.start);
    await expect(slider.locator(".scrubber-price")).toHaveText(
      `6am–6:30am: ${slot.price!.toFixed(1)}p/kWh`,
    );
    await expect(page.locator("#vg-tooltip-element")).not.toBeVisible();
    for (const fraction of [0.001, 0.999]) {
      await page.mouse.move(box.x + box.width * fraction, box.y + 60);
      const label = (await slider.locator(".scrubber-price").boundingBox())!;
      expect(label.x).toBeGreaterThanOrEqual(box.x - 1);
      expect(label.x + label.width).toBeLessThanOrEqual(box.x + box.width + 1);
    }
    await expect(slider.locator(".scrubber-price")).toContainText(
      "11:30pm–12am:",
    );
    await page.getByLabel("Normalise prices").uncheck();
    await expect(sliders.first()).toHaveAttribute(
      "data-start",
      daySlots(days[0]).find(
        (s) => Date.parse(s.start) === Date.parse(fixture.issued_at),
      )!.start,
    );
    await expect(page.locator(".scrubber-price:not([hidden])")).toHaveCount(7);
  });

  test("repeated autumn half-hours retain their BST and GMT time slots", async ({
    page,
  }) => {
    const data = structuredClone(fixture);
    delete data.regions;
    const midnight = Date.parse("2026-10-24T23:00:00Z");
    data.issued_at = new Date(midnight).toISOString();
    data.slots = Array.from({ length: 50 }, (_, index) => ({
      ...fixture.slots[0],
      start: new Date(midnight + index * 1800000).toISOString(),
      end: new Date(midnight + (index + 1) * 1800000).toISOString(),
      day: "2026-10-25",
      minute: (index < 4 ? index : index - 2) * 30,
      utc_offset_minutes: index < 4 ? 60 : 0,
      price: index === 4 ? -6 : 10,
      status: "predicted",
      policy: "ensemble-experimental",
    }));
    await page.route("**/data/forecast.json", (route) =>
      route.fulfill({ json: data }),
    );
    await page.goto("/");
    const slider = page.locator(".price-scrubber");
    await page.getByLabel("Show past prices").check();
    await slider.focus();
    await page.keyboard.press("End");
    for (let i = 0; i < 45; i++) await page.keyboard.press("ArrowLeft");
    await expect(slider).toHaveAttribute("data-start", data.slots[4].start);
    await expect(slider.locator(".scrubber-price")).toHaveText(
      "1am GMT–1:30am GMT: -6.0p/kWh",
    );
    await slider.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(slider.locator(".scrubber-price")).toHaveText(
      "1:30am BST–1am GMT: 10.0p/kWh",
    );
    await page.keyboard.press("ArrowLeft");
    await expect(slider.locator(".scrubber-price")).toHaveText(
      "1am BST–1:30am BST: 10.0p/kWh",
    );
  });
});
