"""Use published prices first, then model estimates; export a small public contract."""

import jsonschema
import numpy as np
import pandas as pd

from . import archive, ensemble, model_store, regions
from .features import future_intervals
from .model import INPUTS, predict
from .storage import ROOT, load_snapshot, read_json, read_table, save_json


def display_intervals(as_of):
    start = (
        pd.Timestamp(as_of).tz_convert("Europe/London").normalize().tz_convert("UTC")
    )
    end = future_intervals(as_of)[-1] + pd.Timedelta(minutes=30)
    # Today so far plus the next 336 settlement intervals. The final local date
    # is partial; daylight-saving days still contain their 46 or 50 real slots.
    return pd.date_range(start, end, freq="30min", inclusive="left")


def build(model, inputs, prices, metadata, accuracy=None, predictions=None, bias=None):
    as_of = pd.Timestamp(metadata["as_of"])
    if pd.Timestamp(model["trained_as_of"]) > as_of:
        raise ValueError(
            "This model was trained after the snapshot. Train with the snapshot cutoff."
        )
    if (model["data_mode"] == "demo") != (metadata["mode"] == "demo"):
        raise ValueError("Do not mix a synthetic model and real inputs.")
    if (
        inputs.inputs_available_at.isna().any()
        or (inputs.inputs_available_at > as_of).any()
    ):
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
    published = np.isfinite(frame.price_p_kwh)
    frame["status"] = np.where(published, "published", "unavailable")
    frame["policy"] = np.where(published, "published", "unavailable")
    if model["kind"] == model_store.KIND:
        if predictions is None:
            raise ValueError("Research model requires its full feature snapshot.")
        frame = frame.merge(
            predictions[["target_start", "candidate", "policy"]].rename(
                columns={"policy": "model_policy"}
            ),
            on="target_start",
            how="left",
            validate="one_to_one",
        )
        valid = (
            ~published & (frame.target_start >= as_of) & np.isfinite(frame.candidate)
        )
        frame.loc[valid, "price_p_kwh"] = frame.loc[valid, "candidate"]
        frame.loc[valid, "policy"] = frame.loc[valid, "model_policy"]
        name = "Research ensemble with level and shape adjustment"
    else:
        valid = (
            ~published
            & (frame.target_start >= as_of)
            & np.isfinite(frame[INPUTS]).all(axis=1)
            & (frame[INPUTS] >= 0).all(axis=1)
        )
        frame.loc[valid, "price_p_kwh"] = predict(model, frame.loc[valid])
        frame.loc[valid, "policy"] = "linear-baseline"
        name = "Simple linear baseline"
    frame.loc[valid, "status"] = "predicted"
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
                "policy": row.policy,
            }
        )
    notes = list(metadata["notes"])
    if model["kind"] == model_store.KIND:
        notes.append(
            "Days beyond the research window are experimental. Missing required inputs leave gaps; no measured seven-day accuracy is claimed."
        )
        if bias and bias["warming_up"]:
            notes.append(
                "Recent-error correction is warming up: fewer than three reference issue days have completed outcomes. The level correction is currently zero."
            )
    return {
        "schema_version": 2,
        "mode": metadata["mode"],
        "issued_at": as_of.isoformat(),
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "timezone": "Europe/London",
        "region": "G",
        "unit": "p/kWh including VAT",
        "horizon_hours": 168,
        "horizon_end": slots[-1]["end"],
        "model": {
            "name": name,
            "id": model["id"],
            "recipe_id": model.get("recipe_id", model["kind"]),
            "trained_as_of": model["trained_as_of"],
            "training_rows": model["training_rows"],
        },
        "sources": metadata["sources"],
        "notes": notes,
        "accuracy": accuracy if metadata["mode"] != "demo" else None,
        "calibration": bias,
        "slots": slots,
        "regions": regions.forecasts(slots, metadata.get("regional_prices", {})),
    }


def export(state, site):
    model = read_json(state / "model.json")
    inputs, prices, metadata = load_snapshot(state)
    as_of = pd.Timestamp(metadata["as_of"])
    if metadata["mode"] == "live":
        age = pd.Timestamp.now(tz="UTC") - as_of
        if age < pd.Timedelta(0) or age > pd.Timedelta(hours=2):
            raise ValueError(
                "Live snapshot is stale. Run collect explicitly before forecasting."
            )
        if as_of - pd.Timestamp(model["trained_as_of"]) > pd.Timedelta(days=35):
            raise ValueError(
                "The model is over 35 days old; refresh training history and refit."
            )
        if as_of - pd.Timestamp(model["training_end"]) > pd.Timedelta(days=35):
            raise ValueError(
                "Training history is over 35 days old; refitting old history cannot make it fresh."
            )
    accuracy_path = state / "accuracy.json"
    accuracy = read_json(accuracy_path) if accuracy_path.exists() else None
    # Scores belong to the recipe and evaluation protocol, never whichever
    # model happens to be in this directory after an experiment.
    if model["kind"] == model_store.KIND:
        if accuracy and (
            accuracy.get("recipe_id") != model["recipe_id"]
            or accuracy.get("recipe_fingerprint") != model["recipe_fingerprint"]
        ):
            accuracy = None
    elif accuracy and accuracy.get("recipe_id") != model["kind"]:
        accuracy = None
    predictions, bias = None, None
    if model["kind"] == model_store.KIND:
        folder = state / read_json(state / "latest_snapshot.json")["directory"]
        if not (folder / "features.csv").exists():
            raise ValueError(
                "This older snapshot has no research features. Run collect, or import into a new state directory for a historical replay."
            )
        features = read_table(folder / "features.csv")
        if not features.cutoff.eq(as_of).all():
            raise ValueError("Feature snapshot has the wrong issue timestamp.")
        for column in features:
            if (
                column.endswith("_available_at")
                and (features[column].dropna() > as_of).any()
            ):
                raise ValueError(
                    f"{column} includes information unavailable at issue time."
                )
        bias = archive.recent_bias(state, as_of)
        predictions = ensemble.predict(
            model_store.load_research(state, model), features, bias=bias["value"]
        )
    payload = build(model, inputs, prices, metadata, accuracy, predictions, bias)
    jsonschema.validate(
        payload,
        read_json(ROOT / "schemas/forecast.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    )
    # Persist private predictions BEFORE publishing. Keep model outputs even for
    # already-published slots, solely for the research's matured bias calculation.
    if predictions is not None and metadata["mode"] == "live":
        archive.record_predictions(state, predictions, model["id"])
    issue = as_of.strftime("%Y%m%dT%H%M%S%fZ")
    destination = state / "forecasts" / f"{issue}-{model['id']}.json"
    if not destination.exists():
        save_json(destination, payload)
    save_json(site / "data/forecast.json", payload)
    return payload
