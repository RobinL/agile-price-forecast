"""The frozen research recipe, without imports from the research project.

Two AgilePredict reproductions and three demand-profile experts vote by median.
A year-long expert changes the shape of the complete 48–72h window, preserving
that median's average level. Half the matured three-day error adjusts its level.
Other horizons use the median alone and remain experimental.

AgilePredict parameters/ensemble adapted from fboundy/agile_predict at commit
505adda5820d91ceb369ca4728116c446567c530. See notices/AgilePredict-MIT.txt.
"""

import hashlib

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from sklearn.ensemble import ExtraTreesRegressor

from .features import EXTENDED, PHYSICAL, PROFILE, REQUIRED

RECIPE_ID = "level-shape-v1"
BASELINE_ID = "demand-median-v1"
MEMBERS = ["AP0_60", "AP0_90", "cat90_profile", "lgb90_profile", "cat180_profile"]
CAT = {
    "iterations": 500,
    "learning_rate": 0.05,
    "depth": 6,
    "l2_leaf_reg": 3,
    "random_seed": 42,
    "verbose": 0,
    "thread_count": 1,
    "allow_writing_files": False,
}
LGB = {
    "n_estimators": 500,
    "learning_rate": 0.05,
    "max_depth": 5,
    "num_leaves": 31,
    "min_child_samples": 5,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_lambda": 3,
    "random_state": 42,
    "n_jobs": 1,
    "verbose": -1,
}
EXTRA = {
    "n_estimators": 700,
    "min_samples_leaf": 4,
    "max_features": "sqrt",
    "random_state": 42,
    "n_jobs": 1,
}


def reference_issues(frame):
    """At most one observed issue per London day; never manufacture 16:30 data.

    The research used exactly 16:30. An observed issue between 16:30 and 17:30
    can keep the live history moving, but its changed issuance is experimental.
    """
    issues = pd.Series(frame.cutoff.unique()).sort_values()
    local = issues.dt.tz_convert("Europe/London")
    minute = local.dt.hour * 60 + local.dt.minute
    issues = issues[(minute >= 990) & (minute < 1050)]
    return (
        issues.groupby(issues.dt.tz_convert("Europe/London").dt.date).first().tolist()
    )


def training_rows(history, cutoff, days, long_model=False):
    cutoff = pd.Timestamp(cutoff)
    f = history.copy()
    allowed = (
        f.cutoff.isin(reference_issues(f))
        & (f.cutoff < cutoff)
        & (f.cutoff > cutoff - pd.Timedelta(days=days))
        & (f.price_available_at <= cutoff)
        & (f.target_end <= cutoff)
        & np.isfinite(f.price)
    )
    for column in f.columns:
        if column.endswith("_available_at") and column != "price_available_at":
            allowed &= f[column].isna() | (f[column] <= f.cutoff)
    if long_model:
        allowed &= f.long_training_eligible
    midnight = (
        f.cutoff.dt.tz_convert("Europe/London").dt.normalize().dt.tz_convert("UTC")
    )
    # Preserve the audited recipe's ELAPSED-hour boundaries across DST changes.
    allowed &= (f.target_start >= midnight + pd.Timedelta(hours=22)) & (
        f.target_start < midnight + pd.Timedelta(hours=46)
    )
    result = f.loc[allowed].sort_values(["cutoff", "target_start"])
    if result.duplicated(["cutoff", "target_start"]).any():
        raise ValueError("Duplicate training observations.")
    if len(result) < 14 * 48:
        raise ValueError(
            "Research model needs at least 672 eligible training intervals."
        )
    return result


def ap_design(frame, cutoff, prediction=False):
    columns = [
        "solar",
        "emb_wind",
        "demand_peak",
        "peak",
        "time",
        "upstream_weekend",
        "bank_holiday",
        "dispatchable_capacity",
    ]
    x = (
        frame[columns]
        .rename(columns={"demand_peak": "demand", "upstream_weekend": "weekend"})
        .copy()
    )
    x["days_ago"] = (
        0.0 if prediction else (cutoff - frame.cutoff).dt.total_seconds() / 86400
    )
    return x[
        [
            "solar",
            "emb_wind",
            "demand",
            "peak",
            "time",
            "days_ago",
            "weekend",
            "bank_holiday",
            "dispatchable_capacity",
        ]
    ]


def profile_design(frame, cutoff, prediction=False):
    f = frame.copy()
    f["demand_hh_to_peak"] = f.demand_hh / f.profile_peak.replace(0, np.nan)
    f["demand_hh_capacity_ratio"] = f.demand_hh / f.dispatchable_capacity.replace(
        0, np.nan
    )
    f["demand_profile_missing"] = f.demand_hh.isna().astype(int)
    x = f[PHYSICAL + EXTENDED].copy()
    x["days_ago"] = (
        0.0 if prediction else (cutoff - f.cutoff).dt.total_seconds() / 86400
    )
    for name in PROFILE:
        x[name] = f[name]
    return x.replace([np.inf, -np.inf], np.nan)


class AgilePredictRecipe:
    def fit(self, frame, cutoff):
        self.cutoff = cutoff
        x, y = ap_design(frame, cutoff), frame.price
        self.medians = x.median()
        sd = y.std(ddof=1)
        weights = (
            np.maximum(1.0, abs((y - y.mean()) / sd)) if sd > 0 else np.ones(len(y))
        )
        self.models = [
            CatBoostRegressor(**CAT),
            LGBMRegressor(**LGB),
            ExtraTreesRegressor(**EXTRA),
        ]
        for index, estimator in enumerate(self.models):
            estimator.fit(
                x.fillna(self.medians) if index == 2 else x, y, sample_weight=weights
            )
        return self

    def predict(self, frame):
        x = ap_design(frame, self.cutoff, True)
        return np.column_stack(
            [
                m.predict(x.fillna(self.medians) if i == 2 else x)
                for i, m in enumerate(self.models)
            ]
        ).mean(axis=1)


class DemandExpert:
    def __init__(self, name):
        self.name = name

    def fit(self, frame, cutoff):
        self.cutoff = cutoff
        x = profile_design(frame, cutoff)
        self.medians = x.median().fillna(0)
        if self.name == "lgb90_profile":
            self.model = LGBMRegressor(
                **{
                    **LGB,
                    "n_estimators": 250,
                    "num_leaves": 15,
                    "min_child_samples": 48,
                    "reg_lambda": 10,
                    "objective": "regression_l1",
                }
            )
        else:
            params = {**CAT, "iterations": 450, "depth": 5, "l2_leaf_reg": 8}
            if self.name != "cat180_profile":
                params["loss_function"] = "MAE"
            self.model = CatBoostRegressor(**params)
        weights = (
            np.exp2(-(cutoff - frame.cutoff).dt.total_seconds().to_numpy() / 86400 / 60)
            if self.name == "cat180_profile"
            else np.ones(len(frame))
        )
        self.model.fit(x.fillna(self.medians), frame.price, sample_weight=weights)
        return self

    def predict(self, frame):
        return self.model.predict(
            profile_design(frame, self.cutoff, True).fillna(self.medians)
        )


def fit(history, cutoff):
    cutoff = pd.Timestamp(cutoff)
    bundle = {"cutoff": cutoff, "members": {}, "recipe_id": RECIPE_ID}
    records = []
    for name, days in [
        ("AP0_60", 60),
        ("AP0_90", 90),
        ("cat90_profile", 90),
        ("lgb90_profile", 90),
        ("cat180_profile", 180),
        ("cat365_base", 365),
    ]:
        rows = training_rows(history, cutoff, days, long_model=name == "cat365_base")
        estimator = (
            AgilePredictRecipe() if name.startswith("AP0") else DemandExpert(name)
        )
        bundle["members"][name] = estimator.fit(rows, cutoff)
        records.append(
            {
                "name": name,
                "rows": len(rows),
                "training_start": rows.target_start.min().isoformat(),
                "training_end": rows.target_start.max().isoformat(),
            }
        )
    bundle["training"] = records
    # Include the exact eligible matrices/labels in provenance, not just dates.
    columns = (
        ["cutoff", "target_start", "price", "price_available_at"]
        + PHYSICAL
        + EXTENDED
        + [
            "profile_peak",
            "profile_min",
            "profile_range",
            "profile_mean",
            "demand_hh",
            "demand_hh_ramp",
            "long_training_eligible",
        ]
    )
    eligible = history[
        (history.cutoff < cutoff)
        & (history.price_available_at <= cutoff)
        & (history.target_end <= cutoff)
    ].sort_values(["cutoff", "target_start"])
    bundle["training_sha256"] = hashlib.sha256(
        pd.util.hash_pandas_object(eligible[columns], index=False).values.tobytes()
    ).hexdigest()
    return bundle


def predict(bundle, frame, bias=0.0):
    """Predict all supplied future rows; adjust only a COMPLETE unknown 48–72h batch."""
    if (frame.cutoff < bundle["cutoff"]).any():
        raise ValueError("Forecast predates model fit.")
    if frame.duplicated(["cutoff", "target_start"]).any():
        raise ValueError("Duplicate forecast targets.")
    result = frame[
        ["cutoff", "target_start", "target_end", "lead_hours", "status_at_issue"]
    ].copy()
    valid = np.isfinite(frame[REQUIRED]).all(axis=1)
    valid &= (frame[["solar", "emb_wind"]] >= 0).all(axis=1) & (
        frame[["demand_peak", "demand_hh", "dispatchable_capacity"]] > 0
    ).all(axis=1)
    for name in MEMBERS + ["cat365_base"]:
        result[name] = np.nan
        if valid.any():
            result.loc[valid, name] = bundle["members"][name].predict(frame.loc[valid])
    result["prediction"] = result[MEMBERS].median(axis=1, skipna=False)
    result["candidate"] = result.prediction
    result["policy"] = np.where(valid, "ensemble-experimental", "unavailable")
    primary = (result.lead_hours >= 48) & (result.lead_hours < 72)
    for _, group in result.loc[primary].groupby("cutoff"):
        if (
            len(group) != 48
            or not group.status_at_issue.eq("unknown").all()
            or not np.isfinite(group[MEMBERS + ["cat365_base"]]).all().all()
        ):
            continue
        shape = (group.prediction + group.cat365_base) / 2
        result.loc[group.index, "candidate"] = (
            shape - shape.mean() + group.prediction.mean() + np.clip(0.5 * bias, -4, 4)
        )
        result.loc[group.index, "policy"] = "research-48-72"
    return result


def recipe_fingerprint():
    """Invalidate attached accuracy when the recipe or feature code changes."""
    from pathlib import Path

    parts = [
        Path(__file__).read_bytes(),
        Path(__file__).with_name("features.py").read_bytes(),
    ]
    return hashlib.sha256(b"".join(parts)).hexdigest()
