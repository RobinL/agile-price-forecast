"""An additive price model. The only learned state is an intercept and coefficients.

Calendar columns describe the usual daily pattern. Demand, wind and solar adjust
it. Ridge regression discourages very large coefficients when inputs overlap.
The adjustments are associations learned from data, not causal estimates.
"""

import hashlib
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

INPUTS = ["demand_mw", "wind_mw", "solar_mw"]
HISTORY_DAYS = 180


def features(frame):
    local = pd.to_datetime(frame.target_start, utc=True).dt.tz_convert("Europe/London")
    hour = local.dt.hour + local.dt.minute / 60
    # Two smooth waves allow both a morning and an evening pattern.
    return pd.DataFrame(
        {
            "demand_gw": frame.demand_mw.to_numpy() / 1000,
            "wind_gw": frame.wind_mw.to_numpy() / 1000,
            "solar_gw": frame.solar_mw.to_numpy() / 1000,
            "daily_sine": np.sin(2 * np.pi * hour / 24).to_numpy(),
            "daily_cosine": np.cos(2 * np.pi * hour / 24).to_numpy(),
            "twice_daily_sine": np.sin(4 * np.pi * hour / 24).to_numpy(),
            "twice_daily_cosine": np.cos(4 * np.pi * hour / 24).to_numpy(),
            "evening_peak": ((hour >= 16) & (hour < 19)).astype(float).to_numpy(),
            "weekend": (local.dt.dayofweek >= 5).astype(float).to_numpy(),
        }
    )


def eligible_history(history, as_of):
    """Never learn from an outcome or an input that was unavailable at the cutoff."""
    as_of = pd.Timestamp(as_of)
    f = history.copy()
    good = (
        (f.price_available_at <= as_of)
        & (f.target_start + pd.Timedelta(minutes=30) <= as_of)
        & (f.issued_at < f.target_start)
        & (f.inputs_available_at <= f.issued_at)
        & (f.target_start >= as_of - pd.Timedelta(days=HISTORY_DAYS))
    )
    f = f.loc[good].dropna(subset=INPUTS + ["price_p_kwh"])
    f = f[np.isfinite(f[INPUTS + ["price_p_kwh"]]).all(axis=1)]
    f = f[(f[INPUTS] >= 0).all(axis=1)]
    # One answer per target, not 24 near-identical hourly observations.
    return f.sort_values("issued_at").drop_duplicates("target_start", keep="last")


def fit(history, as_of, data_mode):
    rows = eligible_history(history, as_of)
    if len(rows) < 48 * 14:
        raise ValueError(
            "Training needs at least 14 complete days of eligible history."
        )
    x = features(rows)
    estimator = Ridge(alpha=10.0).fit(x, rows.price_p_kwh)
    result = {
        "kind": "linear-ridge-v1",
        "data_mode": data_mode,
        "trained_as_of": pd.Timestamp(as_of).isoformat(),
        "training_rows": len(rows),
        "training_start": rows.target_start.min().isoformat(),
        "training_end": rows.target_start.max().isoformat(),
        "intercept": float(estimator.intercept_),
        "coefficients": dict(zip(x.columns, estimator.coef_.tolist())),
    }
    result["id"] = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode()
    ).hexdigest()[:12]
    return result


def predict(model, frame):
    x = features(frame)
    if list(x.columns) != list(model["coefficients"]):
        raise ValueError(
            "The saved model uses a different feature definition. Refit it."
        )
    return model["intercept"] + x.to_numpy() @ np.array(
        list(model["coefficients"].values())
    )


def evaluate(history, as_of, data_mode):
    """One fixed chronological check, not tuning or an AgilePredict comparison."""
    boundary = pd.Timestamp(as_of) - pd.Timedelta(days=28)
    test = eligible_history(history, as_of)
    test = test[test.issued_at >= boundary]
    model = fit(history, boundary, data_mode)
    # Exactly 168 hours earlier is unambiguous across daylight-saving changes.
    previous = history.drop_duplicates("target_start").set_index("target_start")
    keys = test.target_start - pd.Timedelta(days=7)
    baseline = previous.reindex(keys).price_p_kwh.to_numpy()
    available = previous.reindex(keys).price_available_at.to_numpy()
    valid = np.isfinite(baseline) & (available <= test.issued_at.to_numpy())
    test = test.loc[valid]
    if test.empty:
        raise ValueError("No matched chronological evaluation rows.")
    return {
        "description": "Last 28 days of eligible issues; one model fitted before them. Exploratory, not an independent accuracy guarantee.",
        "slots": len(test),
        "issue_days": int(test.issued_at.dt.date.nunique()),
        "model_mae_p_kwh": float(
            np.mean(np.abs(predict(model, test) - test.price_p_kwh))
        ),
        "week_earlier_mae_p_kwh": float(
            np.mean(np.abs(baseline[valid] - test.price_p_kwh))
        ),
        "baseline": "Price 168 hours earlier",
        "data_mode": data_mode,
        "evaluated_as_of": pd.Timestamp(as_of).isoformat(),
        "model_trained_as_of": boundary.isoformat(),
        "target_start": test.target_start.min().isoformat(),
        "target_end": (test.target_start.max() + pd.Timedelta(minutes=30)).isoformat(),
        "training_input_note": "Historical demand is reconstructed; this does not measure accuracy with the native live demand feed.",
    }
