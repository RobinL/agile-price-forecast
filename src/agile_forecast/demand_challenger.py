"""Experimental demand-only change; production never imports this module.

Keep every existing expert and adjustment. Refit only the two AP-style members
at the production model's training cutoff using then-known half-hour profiles.
"""

import copy

import numpy as np
import pandas as pd

from . import ensemble

RECIPE = "half-hour-demand-v1"


class HalfHourMember:
    def __init__(self, fitted, fallback):
        self.fitted, self.fallback = fitted, fallback

    def predict(self, frame):
        result = self.fallback.predict(frame)
        valid = np.isfinite(frame.demand_hh) & frame.demand_hh.gt(0)
        if valid.any():
            changed = frame.loc[valid].copy()
            changed["demand_peak"] = changed.demand_hh
            result[valid] = self.fitted.predict(changed)
        return result


def fit(control, history):
    """Never mutate the production bundle, or use labels beyond its fit cutoff."""
    challenger = copy.copy(control)
    challenger["members"] = control["members"].copy()
    audit = []
    for name, days in [("AP0_60", 60), ("AP0_90", 90)]:
        rows = ensemble.training_rows(history, control["cutoff"], days)
        rows = rows[np.isfinite(rows.demand_hh) & rows.demand_hh.gt(0)].copy()
        if len(rows) < 14 * 48:
            raise ValueError("Insufficient historical half-hour demand profiles.")
        if rows.profile_available_at.isna().any():
            raise ValueError("Demand profiles must have availability timestamps.")
        rows["demand_peak"] = rows.demand_hh
        fitted = ensemble.AgilePredictRecipe().fit(rows, control["cutoff"])
        challenger["members"][name] = HalfHourMember(fitted, control["members"][name])
        audit.append(
            {
                "member": name,
                "rows": len(rows),
                "latest_label": rows.price_available_at.max().isoformat(),
            }
        )
    return challenger, audit


def recent_bias(predictions, prices, cutoff):
    """Identical policy to production, using only this arm's short-horizon errors."""
    empty = {"value": 0.0, "samples": 0, "issue_days": 0, "warming_up": True}
    if predictions.empty or prices.empty:
        return empty
    f = predictions[predictions.cutoff < cutoff].copy()
    f = f[f.cutoff.isin(ensemble.reference_issues(f))]
    f = f.sort_values("cutoff", kind="stable").drop_duplicates(
        ["cutoff", "target_start"], keep="first"
    )
    f = f[
        (f.lead_hours >= 0)
        & (f.lead_hours < 24)
        & (f.target_end <= cutoff)
        & (f.target_end > cutoff - pd.Timedelta(days=3))
    ]
    labels = (
        prices[(prices.price_available_at <= cutoff)]
        .sort_values("price_available_at")
        .drop_duplicates("target_start", keep="last")
    )
    f = f.merge(
        labels[["target_start", "price"]], on="target_start", validate="many_to_one"
    )
    f = f[np.isfinite(f.prediction) & np.isfinite(f.price)]
    days = f.cutoff.dt.tz_convert("Europe/London").dt.date.nunique()
    return {
        "value": float((f.price - f.prediction).mean()) if days >= 3 else 0.0,
        "samples": len(f),
        "issue_days": int(days),
        "warming_up": days < 3,
    }
