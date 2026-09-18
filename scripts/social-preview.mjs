// Capture the real public UI once, for a stable, dated social-sharing image.
// This is deliberately separate from the hourly forecast workflow.
import { resolve } from "node:path";
import { existsSync } from "node:fs";

const cachedBrowsers = resolve(".cache/ms-playwright");
if (!process.env.PLAYWRIGHT_BROWSERS_PATH && existsSync(cachedBrowsers)) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = cachedBrowsers;
}
const url =
  process.argv[2] ?? "https://www.robinlinacre.com/agile-price-forecast/";
const { chromium } = await import("@playwright/test");
const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1200, height: 630 },
    deviceScaleFactor: 1,
    timezoneId: "Europe/London",
  });
  // Capturing an image must never opt in to analytics or record a Google visit.
  await page.route(/googletagmanager\.com|google-analytics\.com/, (route) =>
    route.abort(),
  );
  const response = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/data/forecast.json"),
  );
  await page.goto(url);
  const forecast = await (await response).json();
  if (forecast.mode !== "live")
    throw new Error("Use the real live forecast, not a fictional fixture.");
  await page.locator(".day-card .price-chart svg").nth(6).waitFor();
  const shownDays = await page
    .locator(".day-card")
    .evaluateAll((cards) => cards.map((card) => card.id.slice(4)));
  const forecastDays = shownDays
    .filter((day) =>
      forecast.slots.some(
        (slot) => slot.day === day && slot.status === "predicted",
      ),
    )
    .slice(0, 2);
  if (forecastDays.length !== 2)
    throw new Error("Need two complete displayed days containing predictions.");
  await page.addStyleTag({
    content: `
    main { max-width: 1160px; padding: 0 32px; }
    .intro { padding: 14px 0 8px; }
    h1 { margin: 10px 0; font-size: 38px; }
    .period-controls, footer { display: none !important; }
    #notice { margin-bottom: 16px; font-size: 13px; }
    .day-card { padding: 14px 18px 10px; margin-bottom: 12px; }
    .price-chart { min-height: 0; }
    .chart-toolbar { padding: 8px 0; }
    .social-attribution { font-size: 10px; color: #737871; margin-top: 7px; }
  `,
  });
  await page.evaluate(
    ({ days, issued }) => {
      for (const card of document.querySelectorAll(".day-card"))
        card.hidden = !days.includes(card.id.slice(4));
      const date = new Intl.DateTimeFormat("en-GB", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Europe/London",
      }).format(new Date(issued));
      document.getElementById("notice").textContent =
        `Example forecast · Issued ${date} London`;
      const attribution = document.createElement("div");
      attribution.className = "social-attribution";
      attribution.textContent =
        "Supported by National Energy SO Open Data · Contains BMRS data © Elexon Limited copyright and database right 2024–2026";
      document.querySelector("main").append(attribution);
    },
    { days: forecastDays, issued: forecast.issued_at },
  );
  await page.evaluate(() => document.fonts.ready);
  // Vega reacts to window resizes, not capture-only changes to container CSS.
  await page.evaluate(() => window.dispatchEvent(new Event("resize")));
  await page.waitForFunction(() =>
    [
      ...document.querySelectorAll(".day-card:not([hidden]) .price-chart svg"),
    ].every((svg) => svg.getBoundingClientRect().width > 950),
  );
  const bottom = await page
    .locator(".social-attribution")
    .evaluate((element) => element.getBoundingClientRect().bottom);
  if (bottom > 630)
    throw new Error(
      `The preview would crop content (${bottom}px). Review the capture layout.`,
    );
  await page.screenshot({ path: "web/preview.png", animations: "disabled" });
  console.log(
    JSON.stringify({
      image: "web/preview.png",
      width: 1200,
      height: 630,
      issued_at: forecast.issued_at,
      days: forecastDays,
    }),
  );
} finally {
  await browser.close();
}
