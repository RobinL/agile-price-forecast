"""Regional retail conversion, independent of the trained North West model.

Octopus: https://octopus.energy/blog/agile-pricing-explained/
Multipliers/peak adders: https://docs.octopus.energy/rest/guides/endpoints/
Current AGILE-24-10-01 rates checked against all 14 regions, September 2026.
Published rates always come directly from the regional API, never conversion.
"""

import pandas as pd

# Multiplier on wholesale p/kWh, then evening addition excluding VAT.
REGIONS = {
    "A": ("Eastern England", 2.1, 13),
    "B": ("East Midlands", 2.0, 14),
    "C": ("London", 2.0, 12),
    "D": ("Merseyside & North Wales", 2.2, 13),
    "E": ("West Midlands", 2.1, 12),
    "F": ("North East England", 2.1, 12),
    "G": ("North West England", 2.1, 12),
    "H": ("Southern England", 2.1, 12),
    "J": ("South East England", 2.2, 12),
    "K": ("South Wales", 2.2, 12),
    "L": ("South West England", 2.3, 11),
    "M": ("Yorkshire", 2.0, 13),
    "N": ("South Scotland", 2.1, 13),
    "P": ("North Scotland", 2.4, 12),
}


def convert(price, start, region):
    """Convert an uncapped G prediction, keeping negative rates and London DST."""
    local = pd.Timestamp(start).tz_convert("Europe/London")
    peak = 16 <= local.hour < 19
    reduction = 3.5 if local >= pd.Timestamp("2026-04-01", tz="Europe/London") else 0
    _, multiplier, adder = REGIONS[region]
    common = (price + reduction - (12 * 1.05 if peak else 0)) / 2.1
    return round(
        min(100, common * multiplier + (adder * 1.05 if peak else 0) - reduction), 3
    )


def forecasts(slots, published):
    result = {}
    for code, (name, _, _) in REGIONS.items():
        if code != "G" and code not in published:
            continue  # Old snapshots remain usable, without invented published rates.
        prices = []
        for slot in slots:
            if code == "G" or slot["price"] is None:
                price = slot["price"]
            elif slot["status"] == "published":
                price = published[code].get(slot["start"])
            else:
                price = convert(slot["price"], slot["start"], code)
            prices.append(price)
        result[code] = {"name": name, "prices": prices}
    return result
