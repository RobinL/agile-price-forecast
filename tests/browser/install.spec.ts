import { test, expect } from "@playwright/test";

test("manifest and icons support installation within the site subdirectory", async ({
  request,
}) => {
  const response = await request.get("/manifest.webmanifest");
  expect(response.ok()).toBeTruthy();
  const manifest = await response.json();
  const url = new URL(
    "https://www.robinlinacre.com/agile-price-forecast/manifest.webmanifest",
  );
  expect(new URL(manifest.start_url, url).pathname).toBe(
    "/agile-price-forecast/",
  );
  expect(new URL(manifest.scope, url).pathname).toBe("/agile-price-forecast/");
  expect(manifest.display).toBe("standalone");
  for (const icon of manifest.icons) {
    const png = await request.get("/" + icon.src);
    expect(png.ok()).toBeTruthy();
    const bytes = await png.body();
    expect(bytes.subarray(1, 4).toString()).toBe("PNG");
    expect(`${bytes.readUInt32BE(16)}x${bytes.readUInt32BE(20)}`).toBe(
      icon.sizes,
    );
  }
});

test("install control is opt-in and only visible when the browser offers it", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".price-chart svg").first()).toBeVisible();
  const button = page.getByRole("button", { name: "Install app" });
  await expect(button).toBeHidden();
  await page.evaluate(() => {
    const event = new Event("beforeinstallprompt", { cancelable: true });
    Object.assign(event, {
      prompt: async () => {
        document.body.dataset.prompted = "yes";
      },
      userChoice: Promise.resolve({ outcome: "dismissed" }),
    });
    window.dispatchEvent(event);
  });
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.locator("body")).toHaveAttribute("data-prompted", "yes");
  await expect(button).toBeHidden();
});
