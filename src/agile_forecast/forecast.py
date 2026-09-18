"""Combine official prices and predictions; export only the small public contract."""

import jsonschema
import numpy as np
import pandas as pd

from .model import INPUTS, predict
from .storage import ROOT, load_snapshot, read_json, save_json


def display_intervals(as_of):
    start = pd.Timestamp(as_of).tz_convert("Europe/London").normalize()
    # Calendar days: 46/48/50 intervals on clock-change days, not always 48.
    end = start + pd.DateOffset(days=3)
    return pd.date_range(start, end, freq="30min", inclusive="left").tz_convert("UTC")


def build(model, inputs, prices, metadata, accuracy=None):
    as_of = pd.Timestamp(metadata["as_of"])
    if pd.Timestamp(model["trained_as_of"]) > as_of:
        raise ValueError(
            "This model was trained after the snapshot. Train with the snapshot cutoff."
        )
    if (model["data_mode"] == "demo") != (metadata["mode"] == "demo"):
        raise ValueError("Do not mix a synthetic model and real inputs.")
    if (inputs.inputs_available_at > as_of).any():
        raise ValueError("Input data were not available at the snapshot cutoff.")
    if inputs.target_start.duplicated().any() or prices.target_start.duplicated().any():
        raise ValueError("Duplicate input or price intervals.")
    frame = pd.DataFrame({"target_start": display_intervals(as_of)})
    frame = frame.merge(
        inputs[["target_start"] + INPUTS],
        on="target_start",
        how="left",
        validate="one_to_one",
    )
    frame = frame.merge(
        prices[["target_start", "price_p_kwh"]],
        on="target_start",
        how="left",
        validate="one_to_one",
    )
    valid_price = np.isfinite(frame.price_p_kwh)
    frame["status"] = np.where(valid_price, "published", "unavailable")
    can_predict = (
        (~valid_price)
        & (frame.target_start >= as_of)
        & np.isfinite(frame[INPUTS]).all(axis=1)
        & (frame[INPUTS] >= 0).all(axis=1)
    )
    frame.loc[can_predict, "price_p_kwh"] = predict(model, frame.loc[can_predict])
    frame.loc[can_predict, "status"] = "predicted"
    slots = []
    for row in frame.itertuples():
        local = row.target_start.tz_convert("Europe/London")
        slots.append(
            {
                "start": row.target_start.isoformat(),
                "end": (row.target_start + pd.Timedelta(minutes=30)).isoformat(),
                "day": local.strftime("%Y-%m-%d"),
                "minute": local.hour * 60 + local.minute,
                "clock": local.strftime("%H:%M %Z"),
                "utc_offset_minutes": int(local.utcoffset().total_seconds() / 60),
                "price": round(float(row.price_p_kwh), 3)
                if np.isfinite(row.price_p_kwh)
                else None,
                "status": row.status,
            }
        )
    return {
        "schema_version": 1,
        "mode": metadata["mode"],
        "issued_at": as_of.isoformat(),
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "timezone": "Europe/London",
        "region": "G",
        "unit": "p/kWh including VAT",
        "model": {
            "name": "Simple linear model",
            "id": model["id"],
            "trained_as_of": model["trained_as_of"],
            "training_rows": model["training_rows"],
        },
        "sources": metadata["sources"],
        "notes": metadata["notes"],
        "accuracy": accuracy if metadata["mode"] != "demo" else None,
        "slots": slots,
    }


def export(state, site):
    model = read_json(state / "model.json")
    inputs, prices, metadata = load_snapshot(state)
    if metadata["mode"] == "live":
        age = pd.Timestamp.now(tz="UTC") - pd.Timestamp(metadata["as_of"])
        if age < pd.Timedelta(0) or age > pd.Timedelta(hours=2):
            raise ValueError(
                "Live snapshot is stale. Run collect explicitly before forecasting."
            )
        if pd.Timestamp(metadata["as_of"]) - pd.Timestamp(
            model["trained_as_of"]
        ) > pd.Timedelta(days=35):
            raise ValueError(
                "The model is over 35 days old; refresh training history and refit."
            )
        if pd.Timestamp(metadata["as_of"]) - pd.Timestamp(
            model["training_end"]
        ) > pd.Timedelta(days=35):
            raise ValueError(
                "Training history is over 35 days old; refitting old history cannot make it fresh."
            )
    accuracy_path = state / "accuracy.json"
    accuracy = read_json(accuracy_path) if accuracy_path.exists() else None
    payload = build(model, inputs, prices, metadata, accuracy)
    schema = read_json(ROOT / "schemas/forecast.schema.json")
    jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())
    # Keep the original public forecast for evaluation. Never overwrite an issue.
    issue = pd.Timestamp(metadata["as_of"]).strftime("%Y%m%dT%H%M%S%fZ")
    archive = state / "forecasts" / f"{issue}-{model['id']}.json"
    if not archive.exists():
        save_json(archive, payload)
    save_json(site / "data/forecast.json", payload)
    return payload
