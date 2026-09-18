"""The only network code: three free feeds, bounded downloads, no credentials.

Each provider is normalised here. The model never needs to know CSV column names
or API URLs. Adding another feed starts with another normaliser in this module.
"""

import hashlib
import io
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

from .storage import save_snapshot

CATALOGUE = "https://api.neso.energy/api/3/action/datapackage_show"
DEMAND = "https://api.neso.energy/dataset/633daec6-3e70-444a-88b0-c4cef9419d40/resource/7c0411cd-2714-4bb5-a408-adb065edf34d/download/ng-demand-14da-hh.csv"
PRODUCT = "AGILE-24-10-01"
# NESO sometimes redirects downloads to its own public object store. This is
# provider infrastructure, not our private R2 bucket. Never expose signed URLs.
NESO_DOWNLOAD_HOST = "83025b28472d6aa2bf5ae59f3724aa78.eu.r2.cloudflarestorage.com"


class Downloads:
    def __init__(self):
        self.calls = 0
        self.records = []

    def get(self, name, url, params=None):
        source_url = url
        body, modified = self.download(url, params)
        now = pd.Timestamp.now(tz="UTC")
        if modified and name != "Feed catalogue":
            age = (
                now - pd.Timestamp(parsedate_to_datetime(modified))
            ).total_seconds() / 3600
            if age > 48 or age < -1:
                raise ValueError(
                    f"{name}: provider file timestamp is stale or in the future."
                )
        self.records.append(
            {
                "name": name,
                "url": source_url,
                "retrieved_at": now.isoformat(),
                "provider_updated_at": modified,
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        return body

    def download(self, url, params=None, redirects=0):
        if self.calls >= 8:
            raise ValueError("Collection request budget exhausted.")
        allowed = {"api.neso.energy", "api.octopus.energy", NESO_DOWNLOAD_HOST}
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in allowed:
            raise ValueError("Unexpected provider download URL.")
        self.calls += 1
        with requests.get(
            url, params=params, timeout=(10, 30), stream=True, allow_redirects=False
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                if redirects >= 2 or "Location" not in response.headers:
                    raise ValueError("Too many or invalid provider redirects.")
                destination = urljoin(url, response.headers["Location"])
                response.close()
                return self.download(destination, redirects=redirects + 1)
            if response.status_code != 200:
                raise ValueError(f"Provider returned HTTP {response.status_code}.")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError(
                        "Provider response exceeds the 2 MB collection limit."
                    )
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("Last-Modified")


def demand_rows(body):
    f = pd.read_csv(io.BytesIO(body))
    # The research clock audit treats GDATETIME as a UTC interval END.
    return pd.DataFrame(
        {
            "target_start": pd.to_datetime(f.GDATETIME, utc=True)
            - pd.Timedelta(minutes=30),
            "demand_mw": pd.to_numeric(f.NATIONALDEMAND, errors="raise"),
        }
    )


def renewable_rows(body):
    f = pd.read_csv(io.BytesIO(body))
    return pd.DataFrame(
        {
            "target_start": pd.to_datetime(
                f.DATE_GMT.str[:10] + " " + f.TIME_GMT, utc=True
            ),
            "wind_mw": pd.to_numeric(f.EMBEDDED_WIND_FORECAST, errors="raise"),
            "solar_mw": pd.to_numeric(f.EMBEDDED_SOLAR_FORECAST, errors="raise"),
        }
    )


def collect(state, product=PRODUCT):
    import json

    client = Downloads()
    catalogue = json.loads(
        client.get(
            "Feed catalogue", CATALOGUE, {"id": "embedded-wind-and-solar-forecasts"}
        )
    )
    # Use the small CURRENT forecast, never the enormous annual CSV archive.
    matches = [
        r
        for r in catalogue["result"]["resources"]
        if r["name"] == "embedded_solar_and_wind_forecast"
    ]
    if len(matches) != 1:
        raise ValueError(
            "NESO changed its current forecast catalogue; review the feed adapter."
        )
    renewables = renewable_rows(client.get("NESO wind and solar", matches[0]["path"]))
    demand = demand_rows(client.get("NESO demand", DEMAND))
    inputs = demand.merge(
        renewables, on="target_start", how="outer", validate="one_to_one"
    )
    today = pd.Timestamp.now(tz="Europe/London").normalize()
    url = f"https://api.octopus.energy/v1/products/{product}/electricity-tariffs/E-1R-{product}-G/standard-unit-rates/"
    payload = json.loads(
        client.get(
            "Octopus prices",
            url,
            {
                "period_from": today.isoformat(),
                "period_to": (today + pd.DateOffset(days=3)).isoformat(),
                "page_size": 1500,
            },
        )
    )
    if payload.get("next") or not payload.get("results"):
        raise ValueError(
            "Unexpected paginated/empty Octopus price response. Check the tariff product."
        )
    prices = pd.DataFrame(payload["results"])
    prices = pd.DataFrame(
        {
            "target_start": pd.to_datetime(prices.valid_from, utc=True),
            "price_p_kwh": pd.to_numeric(prices.value_inc_vat),
        }
    )
    if prices.target_start.duplicated().any():
        raise ValueError("Duplicate official price intervals.")
    as_of = pd.Timestamp.now(tz="UTC")
    inputs["issued_at"] = as_of
    inputs["inputs_available_at"] = as_of
    notes = [
        "Early linear model. Live half-hourly demand differs from the reconstructed demand curves used in historical training; this transfer is not yet validated."
    ]
    save_snapshot(
        state,
        inputs,
        prices,
        {
            "mode": "live",
            "as_of": as_of.isoformat(),
            "region": "G",
            "product": product,
            "sources": [r for r in client.records if r["name"] != "Feed catalogue"],
            "notes": notes,
        },
    )
