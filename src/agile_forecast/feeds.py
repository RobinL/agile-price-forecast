"""Provider network code: five free feeds, bounded downloads, no credentials.

Each provider is normalised here. The model never needs to know CSV column names
or API URLs. Adding another feed starts with another normaliser in this module.
"""

import hashlib
import io
import json
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

from .features import OPMR, attach_profiles, engineer, future_intervals
from .storage import read_json, read_table, save_snapshot

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
        if self.calls >= 16:
            raise ValueError("Collection request budget exhausted.")
        allowed = {
            "api.neso.energy",
            "api.octopus.energy",
            "data.elexon.co.uk",
            NESO_DOWNLOAD_HOST,
        }
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


def current_resource(client, package, resource_name):
    catalogue = json.loads(client.get("Feed catalogue", CATALOGUE, {"id": package}))
    matches = [
        r for r in catalogue["result"]["resources"] if r["name"] == resource_name
    ]
    if len(matches) != 1:
        raise ValueError("NESO changed its current catalogue. Review the feed adapter.")
    return matches[0]["path"]


def source_clock(record):
    # Current files do not always include the model-run timestamp. Preserve the
    # HTTP clock as a documented proxy rather than inventing a historical issue.
    value = record.get("provider_updated_at")
    return (
        pd.Timestamp(parsedate_to_datetime(value))
        if value
        else pd.Timestamp(record["retrieved_at"])
    )


def capacity_rows(payload, observed):
    f = pd.DataFrame(payload["result"]["records"])
    f.columns = f.columns.str.strip()
    aliases = {"Maximum I/C Import": "Maximum IC Import"}
    f = f.rename(columns=aliases)
    if not set(OPMR).issubset(f):
        raise ValueError("Unrecognised capacity feed columns.")
    f["capacity_issue_at"] = (
        pd.to_datetime(f["Publish Date"].str[:10])
        .dt.tz_localize("Europe/London")
        .dt.tz_convert("UTC")
    )
    f["target_date"] = pd.to_datetime(f.Date.str[:10]).dt.strftime("%Y-%m-%d")
    f = (
        f[f.capacity_issue_at <= observed]
        .sort_values("capacity_issue_at")
        .drop_duplicates("target_date", keep="last")
    )
    for source, name in OPMR.items():
        f[name] = pd.to_numeric(f[source], errors="raise")
    f["dispatchable_capacity"] = (
        f.generator_available
        + f.maximum_import
        - f.reserve_requirement
        - f.constrained_plant
    )
    f["capacity_available_at"] = observed
    f["extra_capacity_available_at"] = observed
    return f[
        [
            "target_date",
            "dispatchable_capacity",
            "capacity_issue_at",
            "capacity_available_at",
            "extra_capacity_available_at",
        ]
        + list(OPMR.values())
    ]


def daily_demand_rows(payload, observed):
    f = pd.DataFrame(payload["data"])
    f["demand_issue_at"] = pd.to_datetime(f.publishTime, utc=True)
    f["target_date"] = pd.to_datetime(f.forecastDate).dt.strftime("%Y-%m-%d")
    f["demand_peak"] = pd.to_numeric(f.demand, errors="raise")
    f["demand_available_at"] = observed
    f = (
        f[f.demand_issue_at <= observed]
        .sort_values("demand_issue_at")
        .drop_duplicates("target_date", keep="last")
    )
    return f[["target_date", "demand_peak", "demand_issue_at", "demand_available_at"]]


def attach_previous_wind(state, frame, as_of):
    # One snapshot observed at or before yesterday's cutoff. Never treat a
    # download made today as yesterday's forecast revision.
    candidates = []
    for path in (state / "snapshots").glob("*/metadata.json"):
        meta = read_json(path)
        cutoff = pd.Timestamp(meta["as_of"])
        if meta["mode"] == "live" and as_of - pd.Timedelta(
            hours=144
        ) <= cutoff <= as_of - pd.Timedelta(hours=24):
            candidates.append((cutoff, path.parent))
    f = frame.copy()
    f["wind_revision_24"] = float("nan")
    f["solar_revision_24"] = float("nan")
    f["previous_available_at"] = pd.NaT
    if candidates:
        cutoff, folder = max(candidates)
        previous = read_table(folder / "inputs.csv").set_index("target_start")
        f["wind_revision_24"] = (
            f.emb_wind.to_numpy() - previous.wind_mw.reindex(f.target_start).to_numpy()
        )
        f["solar_revision_24"] = (
            f.solar.to_numpy() - previous.solar_mw.reindex(f.target_start).to_numpy()
        )
        f["previous_available_at"] = cutoff
    return f


def collect(state, product=PRODUCT):
    client = Downloads()
    wind_url = current_resource(
        client, "embedded-wind-and-solar-forecasts", "embedded_solar_and_wind_forecast"
    )
    renewables = renewable_rows(client.get("NESO wind and solar", wind_url))
    wind_record = client.records[-1]
    points_url = current_resource(
        client,
        "2-14-days-ahead-national-demand-forecast",
        "2-14_days_ahead_cardinal_point_forecast",
    )
    points = pd.read_csv(io.BytesIO(client.get("NESO cardinal demand", points_url)))
    profile_record = client.records[-1]
    capacity_payload = json.loads(
        client.get(
            "NESO capacity",
            "https://api.neso.energy/api/3/action/datastore_search",
            {
                "resource_id": "0eede912-8820-4c66-a58a-f7436d36b95f",
                "limit": 150,
                "sort": "Publish Date desc, Date asc",
            },
        )
    )
    capacity_observed = pd.Timestamp(client.records[-1]["retrieved_at"])
    now = pd.Timestamp.now(tz="UTC")
    demand_payload = json.loads(
        client.get(
            "Elexon daily peak demand",
            "https://data.elexon.co.uk/bmrs/api/v1/datasets/NDFD",
            {
                "publishDateTimeFrom": (now - pd.Timedelta(days=5)).isoformat(),
                "publishDateTimeTo": now.isoformat(),
                "format": "json",
            },
        )
    )
    demand_observed = pd.Timestamp(client.records[-1]["retrieved_at"])
    today = now.tz_convert("Europe/London").normalize()
    url = f"https://api.octopus.energy/v1/products/{product}/electricity-tariffs/E-1R-{product}-G/standard-unit-rates/"
    payload = json.loads(
        client.get(
            "Octopus prices",
            url,
            {
                "period_from": (today - pd.DateOffset(days=14)).isoformat(),
                "period_to": (today + pd.DateOffset(days=8)).isoformat(),
                "page_size": 1500,
            },
        )
    )
    if payload.get("next") or not payload.get("results"):
        raise ValueError(
            "Unexpected paginated/empty price response. Check the tariff product."
        )
    raw_prices = pd.DataFrame(payload["results"])
    prices = pd.DataFrame(
        {
            "target_start": pd.to_datetime(raw_prices.valid_from, utc=True),
            "price_p_kwh": pd.to_numeric(raw_prices.value_inc_vat),
        }
    )
    if prices.target_start.duplicated().any():
        raise ValueError("Duplicate official price intervals.")
    as_of = pd.Timestamp.now(tz="UTC")
    f = pd.DataFrame({"target_start": future_intervals(as_of)})
    f["target_end"] = f.target_start + pd.Timedelta(minutes=30)
    f["cutoff"] = as_of
    f = attach_profiles(
        f,
        points,
        pd.Timestamp(profile_record["retrieved_at"]),
        source_clock(profile_record),
    )
    f = f.merge(
        renewables.rename(columns={"wind_mw": "emb_wind", "solar_mw": "solar"}),
        on="target_start",
        how="left",
        validate="one_to_one",
    )
    f["wind_available_at"], f["wind_issue_at"] = (
        pd.Timestamp(wind_record["retrieved_at"]),
        source_clock(wind_record),
    )
    f = f.merge(
        capacity_rows(capacity_payload, capacity_observed),
        on="target_date",
        how="left",
        validate="many_to_one",
    )
    f = f.merge(
        daily_demand_rows(demand_payload, demand_observed),
        on="target_date",
        how="left",
        validate="many_to_one",
    )
    for name, fields in [
        ("wind", ["emb_wind", "solar"]),
        ("demand", ["demand_peak"]),
        ("capacity", ["dispatchable_capacity"] + list(OPMR.values())),
        (
            "profile",
            [
                "demand_hh",
                "profile_peak",
                "profile_min",
                "profile_mean",
                "profile_range",
                "demand_hh_ramp",
            ],
        ),
    ]:
        age = (as_of - f[f"{name}_issue_at"]).dt.total_seconds() / 3600
        f.loc[(age > 120) | (age < -1), fields] = float("nan")
        if name != "profile":
            f[f"{name}_age_hours"] = age
    f = attach_previous_wind(state, f, as_of)
    f["status_at_issue"] = f.target_start.isin(prices.target_start).map(
        {True: "known", False: "unknown"}
    )
    f["long_training_eligible"] = True
    f = engineer(f)
    inputs = f[["target_start", "demand_hh", "emb_wind", "solar"]].rename(
        columns={"demand_hh": "demand_mw", "emb_wind": "wind_mw", "solar": "solar_mw"}
    )
    inputs["issued_at"], inputs["inputs_available_at"] = as_of, as_of
    notes = [
        "Seven-day experimental forecast. The selected research adjustment applies only to a complete unknown 48–72h window; other horizons use the underlying ensemble.",
        "Demand is reconstructed from current NESO cardinal points using the same interpolation as historical training. Live collection times are observed; file modification times substitute for absent provider run timestamps.",
        "Historical research used daily 16:30 London issues. Other issue times and horizons beyond 72h do not inherit its accuracy claims.",
    ]
    if f.wind_revision_24.isna().any():
        notes.append(
            "Some 24-hour forecast revisions are not yet available; those optional features use the training medians."
        )
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
        features=f,
    )
