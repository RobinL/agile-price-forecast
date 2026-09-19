"""Isolated TabPFN shadow trial: immutable outputs, never production writes."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, ensemble
from .r2 import Store
from .storage import read_json, save_json

FEATURES = [
    "solar",
    "emb_wind",
    "demand_peak",
    "dispatchable_capacity",
    "demand_hh",
    "generator_available",
    "maximum_import",
    "constrained_plant",
    "reserve_requirement",
    "national_surplus",
    "minimum_demand",
    "opmr_peak_demand",
    "negative_reserve",
    "wind_revision_24",
    "solar_revision_24",
    "wind_ramp",
    "solar_ramp",
    "demand_hh_ramp",
    "profile_range",
    "wind_age_hours",
    "demand_age_hours",
    "capacity_age_hours",
    "time",
    "peak",
    "weekend",
    "bank_holiday",
    "dow",
    "month",
    "sin_hour",
    "cos_hour",
    "sin_year",
    "cos_year",
    "lead_hours",
    "last_day_mean",
    "level_3d",
    "level_14d",
    "level_change_1d",
    "level_change_7d",
    "recent_volatility",
    "lag_7",
    "lag_14",
]


PREFIX = "shadow/tabpfn/v1/"
PROTOCOL = {
    "id": "tabpfn-level50-v1",
    "context_rows": 960,
    "horizon": [48, 72],
    "weight": 0.5,
    "seed": 271828,
    "estimators": 2,
    "region": "G",
    "note": "Daily observed 16:30–17:30 London production issue; direct TabPFN v2 median, capped at100, constant level adjustment. Freeze before prospective scoring.",
}


def records(f):
    return json.loads(f.to_json(orient="records", date_format="iso"))


def prepare(state, output, now=None, smoke=False):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    all_features = archive.read_months(state, "features")
    choices = (
        list(all_features.cutoff.unique())
        if smoke
        else ensemble.reference_issues(all_features)
    )
    choices = [pd.Timestamp(t) for t in choices]
    choices = [
        t
        for t in choices
        if t.tz_convert("Europe/London").date()
        == now.tz_convert("Europe/London").date()
        and pd.Timedelta(0) <= now - t <= pd.Timedelta(hours=6)
    ]
    if not choices:
        raise ValueError(
            "No fresh daily reference issue: skip rather than use stale inputs."
        )
    cutoff = max(choices)
    f = archive.history_as_of(state, cutoff)
    f = f[
        f.cutoff.isin(ensemble.reference_issues(f))
        & f.lead_hours.ge(48)
        & f.lead_hours.lt(72)
    ]
    f = f[
        (f.price_available_at <= cutoff)
        & (f.target_end <= cutoff)
        & np.isfinite(f.price)
    ]
    f = (
        f.sort_values(["target_start", "cutoff"])
        .drop_duplicates("target_start", keep="last")
        .tail(960)
    )
    if len(f) != 960:
        raise ValueError("Need960 distinct delivered training intervals.")
    target = all_features[
        all_features.cutoff.eq(cutoff)
        & all_features.lead_hours.ge(48)
        & all_features.lead_hours.lt(72)
    ].sort_values("target_start")
    for frame in [f, target]:
        for col in frame:
            if col.endswith("_available_at") and col != "price_available_at":
                assert not (
                    frame[col].dropna() > frame.loc[frame[col].notna(), "cutoff"]
                ).any(), col
    predictions = archive.read_months(state, "predictions")
    predictions = (
        predictions[predictions.cutoff.eq(cutoff)]
        .sort_values("model_id")
        .drop_duplicates("target_start", keep="first")
    )
    target = target.merge(
        predictions[["target_start", "candidate", "model_id"]],
        on="target_start",
        validate="one_to_one",
    ).rename(columns={"candidate": "current"})
    if len(target) != 48 or not np.isfinite(target.current).all():
        raise ValueError("Incomplete production comparison window.")
    assert target.target_start.diff().dropna().eq(pd.Timedelta(minutes=30)).all()
    if target.target_start.isin(archive.prices_as_of(state, cutoff).target_start).any():
        raise ValueError("Comparison requires unknown prices at issue.")
    if now >= target.target_start.min():
        raise ValueError("Cannot record a retrospective shadow forecast.")
    cols = ["cutoff", "target_start", "target_end"] + FEATURES
    payload = {
        "protocol": PROTOCOL,
        "smoke_only": smoke,
        "git_commit": os.environ.get("GITHUB_SHA", "local"),
        "features": FEATURES,
        "cutoff": cutoff.isoformat(),
        "prepared_at": now.isoformat(),
        "production_model_ids": target.model_id.unique().tolist(),
        "context": records(f[cols + ["price", "price_available_at"]]),
        "target": records(target[cols + ["current"]]),
        "production_model": read_json(Path(state) / "model.json"),
    }
    save_json(Path(output) / "input.json", payload)
    # Actuals are separate from predictor inputs; inference never reads this file.
    labels = archive.prices_as_of(state, now)
    labels = labels[labels.target_start >= now - pd.Timedelta(days=120)]
    save_json(
        Path(output) / "outcomes.json",
        {
            "observed_as_of": now.isoformat(),
            "prices": records(labels[["target_start", "price", "price_available_at"]]),
        },
    )
    print("Prepared960 historical rows and48 paired target intervals.")


def package(output):
    root = Path(output)
    data = read_json(root / "input.json")
    pred = read_json(root / "prediction.json")
    assert data["protocol"] == PROTOCOL
    assert len(pred["slots"]) == 48
    for t, p in zip(data["target"], pred["slots"], strict=True):
        assert t["target_start"] == p["target_start"] and t["current"] == p["current"]
        assert np.isfinite([p["tabpfn"], p["adjusted"]]).all()
        assert abs(p["adjusted"] - p["current"] - pred["adjustment"]) < 1e-8
    expected = 0.5 * (
        np.mean([p["tabpfn"] for p in pred["slots"]])
        - np.mean([p["current"] for p in pred["slots"]])
    )
    assert abs(pred["adjustment"] - expected) < 1e-8
    body = {
        "input": data,
        "prediction": pred,
        "outcomes": read_json(root / "outcomes.json"),
        "recorded_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    raw = json.dumps(body, allow_nan=False).encode()
    assert len(raw) < 5_000_000
    packed = gzip.compress(raw, mtime=0)
    assert len(packed) < 1_000_000
    return data, packed


def upload(output, store):
    data, packed = package(output)
    if data.get("smoke_only"):
        raise ValueError("Smoke tests cannot enter the prospective archive.")
    if pd.Timestamp.now(tz="UTC") >= min(
        pd.Timestamp(t["target_start"]) for t in data["target"]
    ):
        raise ValueError("Shadow recording is too late.")
    date = pd.Timestamp(data["cutoff"]).tz_convert("Europe/London").strftime("%Y-%m-%d")
    key = PREFIX + date + ".json.gz"
    inventory = store.request("list_objects_v2", Prefix=PREFIX, MaxKeys=181)
    items = inventory.get("Contents", [])
    if any(x["Key"] == key for x in items):
        print("Daily record already exists; preserving the first forecast.")
        return
    if (
        inventory.get("IsTruncated")
        or len(items) >= 180
        or sum(x["Size"] for x in items) + len(packed) > 100_000_000
    ):
        raise ValueError("Shadow trial storage limit reached; review before extending.")
    store.request(
        "put_object",
        Key=key,
        Body=packed,
        ContentType="application/gzip",
        IfNoneMatch="*",
    )
    print("Saved immutable shadow record. Production state and website unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "validate", "upload"])
    parser.add_argument(
        "--state", type=Path, default=Path("runtime_state/shadow-source")
    )
    parser.add_argument("--output", type=Path, default=Path("runtime_state/shadow"))
    parser.add_argument(
        "--smoke-latest",
        action="store_true",
        help="Dry run on latest issue; cannot be uploaded.",
    )
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.state, args.output, smoke=args.smoke_latest)
    elif args.command == "validate":
        package(args.output)
        print("Shadow package validated; no upload.")
    else:
        upload(args.output, Store.from_environment())


if __name__ == "__main__":
    main()
