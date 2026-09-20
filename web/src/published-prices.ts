import type { Forecast } from "./data";

// Public, VAT-inclusive tariff rates. No credentials or private backend needed.
const product = "AGILE-24-10-01";
export type Rates = Map<number, number>;
export async function fetchPublishedPrices(region: string): Promise<Rates> {
  if (!/^[A-HJ-NP]$/.test(region)) throw new Error("Invalid region");
  const url = new URL(
    `https://api.octopus.energy/v1/products/${product}/electricity-tariffs/E-1R-${product}-${region}/standard-unit-rates/`,
  );
  url.searchParams.set("page_size", "200");
  const response = await fetch(url, {
    credentials: "omit",
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error("Published prices unavailable");
  const payload = await response.json();
  if (!Array.isArray(payload.results)) throw new Error("Invalid prices");
  const rates: Rates = new Map();
  for (const row of payload.results) {
    const start = Date.parse(row.valid_from);
    const end = Date.parse(row.valid_to);
    if (
      !Number.isFinite(start) ||
      end - start !== 1800000 ||
      typeof row.value_inc_vat !== "number" ||
      !Number.isFinite(row.value_inc_vat) ||
      rates.has(start)
    )
      throw new Error("Invalid price interval");
    rates.set(start, row.value_inc_vat);
  }
  return rates;
}

// Apply after regional selection: never borrow published prices from another region.
export function withPublishedPrices(f: Forecast, rates?: Rates): Forecast {
  if (f.mode !== "live" || !rates) return f;
  return {
    ...f,
    slots: f.slots.map((slot) => {
      const price = rates.get(Date.parse(slot.start));
      return price === undefined
        ? slot
        : {
            ...slot,
            price,
            status: "published" as const,
            policy: "published" as const,
          };
    }),
  };
}
