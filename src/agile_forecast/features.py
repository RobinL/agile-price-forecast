"""Build the research model's named columns from observed provider snapshots.

The first 72h use exactly the research's window context. Later 72h blocks use
that same calculation as an explicitly unvalidated extension. All calendar
features are local computations. Missing source values stay missing.
"""

import holidays
import numpy as np
import pandas as pd

GRID = ["solar", "emb_wind", "demand_peak", "dispatchable_capacity"]
CALENDAR = [
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
]
AGE = ["wind_age_hours", "demand_age_hours", "capacity_age_hours"]
PHYSICAL = GRID + CALENDAR + AGE
OPMR = {
    "Generator Availability": "generator_available",
    "Maximum IC Import": "maximum_import",
    "Constrained Plant": "constrained_plant",
    "OPMR total": "reserve_requirement",
    "National Surplus": "national_surplus",
    "Minimum Demand Forecast": "minimum_demand",
    "Peak Demand Forecast": "opmr_peak_demand",
    "Negative Reserve": "negative_reserve",
}
EXTENDED = list(OPMR.values()) + [
    "demand_swing",
    "demand_capacity_ratio",
    "embedded_total",
    "wind_revision_24",
    "solar_revision_24",
    "wind_ramp",
    "solar_ramp",
    "wind_daily_mean",
    "wind_daily_min",
    "wind_daily_max",
    "solar_daily_mean",
    "solar_daily_max",
    "day_context_n",
]
PROFILE = [
    "profile_peak",
    "profile_min",
    "profile_range",
    "demand_hh",
    "demand_hh_to_peak",
    "demand_hh_capacity_ratio",
    "demand_hh_ramp",
    "profile_mean",
    "demand_profile_missing",
]
REQUIRED = GRID + ["demand_hh"]


def future_intervals(as_of):
    # Keep the real issue timestamp. Targets themselves must be settlement slots.
    return pd.date_range(
        pd.Timestamp(as_of).ceil("30min"), periods=7 * 48, freq="30min"
    )


def calendar(frame):
    f = frame.copy()
    local = f.target_start.dt.tz_convert("Europe/London")
    f["target_date"] = local.dt.strftime("%Y-%m-%d")
    f["time"] = local.dt.hour + local.dt.minute / 60
    f["peak"] = local.dt.hour.between(16, 18).astype(float)
    f["weekend"] = (local.dt.dayofweek >= 5).astype(int)
    f["upstream_weekend"] = (f.target_start.dt.dayofweek >= 5).astype(int)
    f["dow"], f["month"] = local.dt.dayofweek, local.dt.month
    f["sin_hour"], f["cos_hour"] = (
        np.sin(2 * np.pi * f.time / 24),
        np.cos(2 * np.pi * f.time / 24),
    )
    f["sin_year"], f["cos_year"] = (
        np.sin(2 * np.pi * local.dt.dayofyear / 365.25),
        np.cos(2 * np.pi * local.dt.dayofyear / 365.25),
    )
    bank_holidays = holidays.UK(
        subdiv="England", years=range(local.dt.year.min(), local.dt.year.max() + 1)
    )
    f["bank_holiday"] = [int(day in bank_holidays) for day in local.dt.date]
    return f


def engineer(frame):
    f = calendar(frame.sort_values(["cutoff", "target_start"]).reset_index(drop=True))
    f["lead_hours"] = (f.target_start - f.cutoff).dt.total_seconds() / 3600
    f["embedded_total"] = f.emb_wind + f.solar
    f["demand_swing"] = f.opmr_peak_demand - f.minimum_demand
    f["demand_capacity_ratio"] = f.demand_peak / f.dispatchable_capacity.replace(
        0, np.nan
    )
    # Extending the horizon must not alter any feature of the original first 72h.
    block = (f.lead_hours.clip(lower=0) // 72).astype(int)
    runs = f.groupby([f.cutoff, block])
    f["wind_ramp"], f["solar_ramp"] = runs.emb_wind.diff(), runs.solar.diff()
    days = f.groupby([f.cutoff, block, f.target_date])
    for source, prefix, operations in [
        ("emb_wind", "wind", ["mean", "min", "max"]),
        ("solar", "solar", ["mean", "max"]),
    ]:
        for operation in operations:
            f[f"{prefix}_daily_{operation}"] = days[source].transform(operation)
    f["day_context_n"] = days.target_start.transform("size")
    return f


def attach_profiles(frame, points, available_at, issue_at):
    """Interpolate current cardinal points exactly as in the historical recipe.

    Clock values label interval ends in London time. Interpolation clamps at
    the first/last anchor, including 24:00. Missing days remain unavailable.
    """
    f = frame.copy()
    f["target_date"] = f.target_start.dt.tz_convert("Europe/London").dt.strftime(
        "%Y-%m-%d"
    )
    p = points.copy()
    p["target_date"] = pd.to_datetime(p.TARGETDATE.astype(str)).dt.strftime("%Y-%m-%d")

    def minutes(values):
        v = pd.to_numeric(values, errors="raise")
        if ((v % 100 >= 60) | (v < 0) | (v > 2400)).any():
            raise ValueError("Invalid cardinal clock time.")
        return v // 100 * 60 + v % 100

    start, end = minutes(p.CP_ST_TIME), minutes(p.CP_END_TIME)
    if (end < start).any():
        raise ValueError("Unresolved midnight-crossing cardinal window.")
    p["anchor"] = (start + end) / 2
    p["FORECASTDEMAND"] = pd.to_numeric(p.FORECASTDEMAND, errors="raise")
    for name in [
        "profile_peak",
        "profile_min",
        "profile_range",
        "profile_mean",
        "demand_hh",
        "demand_hh_ramp",
    ]:
        f[name] = np.nan
    for day, anchors in p.groupby("target_date"):
        anchors = anchors[anchors.FORECASTDEMAND.between(1000, 80000)].sort_values(
            "anchor"
        )
        if len(anchors) < 8 or anchors.anchor.min() > 60 or anchors.anchor.max() < 1380:
            continue
        if (anchors.groupby("anchor").FORECASTDEMAND.nunique() > 1).any():
            raise ValueError("Conflicting cardinal demand anchors.")
        anchors = anchors.drop_duplicates("anchor")
        mask = f.target_date == day
        clock = f.loc[mask, "target_end"].dt.tz_convert("Europe/London")
        minute = clock.dt.hour * 60 + clock.dt.minute
        minute += (
            clock.dt.tz_localize(None).dt.normalize() - pd.Timestamp(day)
        ).dt.days * 1440
        values = np.interp(minute, anchors.anchor, anchors.FORECASTDEMAND)
        f.loc[mask, "demand_hh"] = values
        f.loc[mask, "demand_hh_ramp"] = values - np.interp(
            minute - 30, anchors.anchor, anchors.FORECASTDEMAND
        )
        f.loc[mask, "profile_peak"] = anchors.FORECASTDEMAND.max()
        f.loc[mask, "profile_min"] = anchors.FORECASTDEMAND.min()
        f.loc[mask, "profile_range"] = (
            anchors.FORECASTDEMAND.max() - anchors.FORECASTDEMAND.min()
        )
        f.loc[mask, "profile_mean"] = np.interp(
            np.arange(30, 1441, 30), anchors.anchor, anchors.FORECASTDEMAND
        ).mean()
    f["profile_available_at"], f["profile_issue_at"] = available_at, issue_at
    return f
