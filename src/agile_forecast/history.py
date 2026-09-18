"""One explicit import of private research tables; no imports from research code."""

from pathlib import Path

import pandas as pd

from .storage import save_json, save_snapshot


def import_research(source, state):
    source, state = Path(source), Path(state)
    if (state / "history.csv").exists():
        raise ValueError(
            "This state directory already has history. Use a new directory for an import."
        )
    f = pd.read_parquet(source / "artifacts/deployment/daily_features_400d.parquet")
    prices = pd.read_parquet(source / "artifacts/deployment/labels_400d.parquet")
    f = f.rename(
        columns={
            "cutoff": "issued_at",
            "demand_hh": "demand_mw",
            "emb_wind": "wind_mw",
            "solar": "solar_mw",
            "price": "price_p_kwh",
        }
    )
    f["inputs_available_at"] = f[["wind_available_at", "profile_available_at"]].max(
        axis=1
    )
    columns = [
        "issued_at",
        "target_start",
        "demand_mw",
        "wind_mw",
        "solar_mw",
        "inputs_available_at",
    ]
    # These are old forecasts of demand/wind/solar, never their eventual actuals.
    history = f[f.lead_hours.between(48, 72, inclusive="left")][
        columns + ["price_p_kwh", "price_available_at"]
    ]
    state.mkdir(parents=True, exist_ok=True)
    history.to_csv(state / "history.csv", index=False)
    save_json(
        state / "history.json",
        {
            "mode": "research",
            "region": "G",
            "source": str(source.resolve()),
            "note": "Historical demand is reconstructed from NESO cardinal forecasts. Historical publication times include conservative assumptions; this is not a complete first-seen archive.",
        },
    )
    as_of = f.issued_at.max()
    inputs = f[f.issued_at == as_of][columns]
    prices = prices.rename(columns={"price": "price_p_kwh"})
    prices = prices[prices.price_available_at <= as_of][["target_start", "price_p_kwh"]]
    save_snapshot(
        state,
        inputs,
        prices,
        {
            "as_of": as_of.isoformat(),
            "mode": "replay",
            "region": "G",
            "sources": [
                {"name": "Archived Octopus prices"},
                {"name": "Archived NESO demand forecasts"},
                {"name": "Archived NESO wind and solar forecasts"},
            ],
            "notes": [
                "Historical replay: day labels are relative to the original issue date, not today. Published-price availability uses the research's conservative delivered-only rule."
            ],
        },
    )
