"""Deterministic made-up data so a fresh checkout needs no accounts or private files."""

import numpy as np
import pandas as pd

from .storage import save_json, save_snapshot


def create_demo(state):
    if (state / "history.csv").exists():
        raise ValueError(
            "Demo will not overwrite existing history. Use a separate demo state directory."
        )
    as_of = pd.Timestamp("2026-09-18T09:00:00Z")
    targets = pd.date_range(
        as_of.normalize() - pd.Timedelta(days=120), periods=129 * 48, freq="30min"
    )
    local = targets.tz_convert("Europe/London")
    hour = local.hour + local.minute / 60
    day = np.arange(len(targets)) / 48
    rng = np.random.default_rng(17)
    demand = 24000 + 4500 * np.sin((hour - 7) * np.pi / 12) + 1200 * np.cos(day / 6)
    wind = 3000 + 1600 * np.sin(day / 3) + 400 * np.cos(hour / 4)
    solar = np.maximum(0, np.sin((hour - 6) * np.pi / 12)) * (
        6500 + 1800 * np.cos(day / 4)
    )
    price = (
        7
        + demand / 2000
        - wind / 1300
        - solar / 1800
        + ((hour >= 16) & (hour < 19)) * 12
        + rng.normal(0, 1.4, len(targets))
    )
    f = pd.DataFrame(
        {
            "target_start": targets,
            "issued_at": targets - pd.Timedelta(hours=60),
            "inputs_available_at": targets - pd.Timedelta(hours=61),
            "demand_mw": demand,
            "wind_mw": wind,
            "solar_mw": solar,
            "price_p_kwh": price,
            "price_available_at": targets + pd.Timedelta(minutes=30),
        }
    )
    state.mkdir(parents=True, exist_ok=True)
    f[f.price_available_at <= as_of].to_csv(state / "history.csv", index=False)
    save_json(
        state / "history.json",
        {
            "mode": "demo",
            "region": "G",
            "note": "Synthetic data: no real price or accuracy claim.",
        },
    )
    start = as_of.tz_convert("Europe/London").normalize().tz_convert("UTC")
    inputs = f[f.target_start >= start].copy()
    inputs["issued_at"] = as_of
    inputs["inputs_available_at"] = as_of
    prices = inputs[inputs.target_start < as_of.normalize() + pd.Timedelta(hours=23)][
        ["target_start", "price_p_kwh"]
    ]
    save_snapshot(
        state,
        inputs,
        prices,
        {
            "as_of": as_of.isoformat(),
            "mode": "demo",
            "region": "G",
            "sources": [
                {"name": "Example Octopus prices"},
                {"name": "Example demand forecast"},
                {"name": "Example wind and solar forecast"},
            ],
            "notes": [
                "Made-up demonstration data for 18–25 September 2026. These are not actual prices or measured forecasting accuracy."
            ],
        },
    )
