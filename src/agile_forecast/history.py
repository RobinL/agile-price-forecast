"""Explicitly seed private history from compact research outputs, never research imports."""

import hashlib
from pathlib import Path

import pandas as pd

from .archive import append_months
from .ensemble import BASELINE_ID
from .storage import read_json, save_json, save_snapshot


def import_research(source, state):
    source, state = Path(source).resolve(), Path(state)
    files = {
        name: source / "artifacts/deployment" / name
        for name in [
            "daily_features_400d.parquet",
            "labels_400d.parquet",
            "daily_forecasts_365d.parquet",
        ]
    }
    hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in files.items()
    }
    manifest = state / "history" / "research_import.json"
    if manifest.exists():
        if read_json(manifest)["sha256"] != hashes:
            raise ValueError(
                "Research seed differs from the recorded import. Use a separate state directory."
            )
        return
    f = pd.read_parquet(files["daily_features_400d.parquet"])
    labels = pd.read_parquet(files["labels_400d.parquet"])
    forecasts = pd.read_parquet(files["daily_forecasts_365d.parquet"])
    state.mkdir(parents=True, exist_ok=True)
    # Keep the small linear baseline's original, readable training file.
    simple = f.rename(
        columns={
            "cutoff": "issued_at",
            "demand_hh": "demand_mw",
            "emb_wind": "wind_mw",
            "solar": "solar_mw",
            "price": "price_p_kwh",
        }
    ).copy()
    simple["inputs_available_at"] = simple[
        ["wind_available_at", "profile_available_at"]
    ].max(axis=1)
    columns = [
        "issued_at",
        "target_start",
        "demand_mw",
        "wind_mw",
        "solar_mw",
        "inputs_available_at",
    ]
    if not (state / "history.csv").exists():
        simple[simple.lead_hours.between(48, 72, inclusive="left")][
            columns + ["price_p_kwh", "price_available_at"]
        ].to_csv(state / "history.csv", index=False)
        save_json(
            state / "history.json",
            {
                "mode": "research",
                "region": "G",
                "source": str(source),
                "note": "Archived forecasts, including conservative historical publication-time assumptions.",
            },
        )
    elif read_json(state / "history.json")["mode"] != "research":
        raise ValueError(
            "Do not add real research data to a synthetic history directory."
        )
    # Prices are separate so unknown outcomes can be attached when first observed.
    append_months(
        state,
        "features",
        f.drop(columns=["price", "price_available_at"]),
        "cutoff",
        ["cutoff", "target_start"],
    )
    append_months(
        state, "prices", labels, "target_start", ["target_start", "price_available_at"]
    )
    forecasts["baseline_id"] = BASELINE_ID
    forecasts["model_id"] = "archived-out-of-sample-reference"
    append_months(
        state,
        "predictions",
        forecasts,
        "cutoff",
        ["cutoff", "target_start", "model_id"],
    )
    save_json(
        manifest,
        {
            "sha256": hashes,
            "source": str(source),
            "feature_rows": len(f),
            "price_rows": len(labels),
            "baseline_id": BASELINE_ID,
            "note": "Research uses reconstructed cardinal demand; historical availability includes conservative assumptions. No week-ahead evaluation archive is supplied.",
        },
    )
    if not (state / "latest_snapshot.json").exists():
        as_of = f.cutoff.max()
        prices = labels[
            (labels.price_available_at <= as_of)
            & (labels.target_start >= as_of.tz_convert("Europe/London").normalize())
        ].rename(columns={"price": "price_p_kwh"})
        save_snapshot(
            state,
            simple[simple.issued_at == as_of][columns],
            prices[["target_start", "price_p_kwh"]],
            {
                "as_of": as_of.isoformat(),
                "mode": "replay",
                "region": "G",
                "sources": [
                    {"name": "Archived Octopus prices"},
                    {"name": "Archived NESO and Elexon forecasts"},
                ],
                "notes": [
                    "Historical replay. This compact research snapshot contains only 72 hours of input coverage; later dates remain unavailable."
                ],
            },
            features=f[f.cutoff == as_of].drop(columns=["price", "price_available_at"]),
        )
