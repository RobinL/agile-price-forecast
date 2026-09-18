"""Offline checks. Reproduction, historical comparison and forward scores are distinct."""

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, ensemble, features, model_store
from . import model as linear
from .storage import save_json


def verify_research(source, state):
    """Refit on the compact seed and compare to saved research outputs, no imports."""
    source = Path(source)
    benchmark = json.loads((source / "reports/deployment/benchmark.json").read_text())
    history = pd.read_parquet(
        source / "artifacts/deployment/daily_features_400d.parquet"
    )
    core = pd.read_parquet(source / "artifacts/practical/core.parquet")
    test = core[core.cutoff == pd.Timestamp(benchmark["test_cutoff"])].sort_values(
        "target_start"
    )
    rebuilt = features.engineer(test)
    derived = features.CALENDAR + [
        "upstream_weekend",
        "lead_hours",
        "embedded_total",
        "demand_swing",
        "demand_capacity_ratio",
        "wind_ramp",
        "solar_ramp",
        "wind_daily_mean",
        "wind_daily_min",
        "wind_daily_max",
        "solar_daily_mean",
        "solar_daily_max",
        "day_context_n",
    ]
    for column in derived:
        np.testing.assert_allclose(
            rebuilt[column], test[column], equal_nan=True, atol=1e-10
        )
    bundle = ensemble.fit(history, pd.Timestamp(benchmark["fit_cutoff"]))
    result = ensemble.predict(bundle, test, bias=float(test.bias_short_3.iloc[0]))
    differences = {
        name: float(np.max(np.abs(result[name] - test[name])))
        for name in ensemble.MEMBERS + ["prediction"]
    }
    choice = json.loads((source / "reports/practical/result.json").read_text())[
        "followup_selection"
    ]
    saved = pd.read_parquet(
        source / choice["experiment_directory"] / "predictions.parquet"
    )
    saved = saved[
        (saved.cutoff == test.cutoff.iloc[0]) & (saved.model == choice["candidate"])
    ].sort_values("target_start")
    primary = result[result.policy == "research-48-72"]
    if len(primary) != 48 or not primary.target_start.reset_index(drop=True).equals(
        saved.target_start.reset_index(drop=True)
    ):
        raise ValueError("Research comparison has different target intervals.")
    differences["candidate"] = float(
        np.max(np.abs(primary.candidate.to_numpy() - saved.prediction.to_numpy()))
    )
    if max(differences.values()) > 1e-8:
        raise ValueError(f"Research reproduction differs: {differences}")
    with tempfile.TemporaryDirectory() as temporary:
        metadata = model_store.save_research(Path(temporary), bundle)
        restored = model_store.load_research(Path(temporary), metadata)
        roundtrip = ensemble.predict(
            restored, test, bias=float(test.bias_short_3.iloc[0])
        )
        np.testing.assert_array_equal(result.candidate, roundtrip.candidate)
    report = {
        "recipe_id": ensemble.RECIPE_ID,
        "recipe_fingerprint": ensemble.recipe_fingerprint(),
        "fit_cutoff": benchmark["fit_cutoff"],
        "issue": benchmark["test_cutoff"],
        "slots": len(test),
        "adjusted_slots": len(primary),
        "maximum_absolute_differences": differences,
        "serialization_exact": True,
        "derived_features_match": True,
        "scope": "Numerical reproduction of one saved research issue, not a new accuracy claim or seven-day validation.",
    }
    save_json(Path(state) / "checks" / "research_parity.json", report)
    return report


def linear_history(frame):
    f = frame.rename(
        columns={
            "cutoff": "issued_at",
            "demand_hh": "demand_mw",
            "emb_wind": "wind_mw",
            "solar": "solar_mw",
            "price": "price_p_kwh",
        }
    ).copy()
    available = ["wind_available_at", "profile_available_at"]
    f["inputs_available_at"] = f[available].max(axis=1)
    return f[f.lead_hours.between(48, 72, inclusive="left")]


def summarize(frame, names):
    rows = []
    valid = np.isfinite(frame[["price"] + names]).all(axis=1)
    paired = frame.loc[valid]
    for name in names:
        rows.append(
            {
                "model": name,
                "mae_p_kwh": float((paired[name] - paired.price).abs().mean())
                if len(paired)
                else None,
                "slots": len(paired),
            }
        )
    return rows


def evaluate_research(state, as_of, days=28):
    """Fixed weekly fits, same targets for all models, fully matured labels only."""
    as_of = pd.Timestamp(as_of)
    history = archive.history_as_of(state, as_of)
    issues = [
        c
        for c in ensemble.reference_issues(history)
        if as_of - pd.Timedelta(days=days) <= c < as_of
    ]
    results, bundle, small, fitted = [], None, None, None
    for issue in issues:
        day = issue.tz_convert("Europe/London").normalize()
        monday = day - pd.DateOffset(days=day.weekday())
        cutoff = (monday + pd.Timedelta(hours=16, minutes=30)).tz_convert("UTC")
        if cutoff > issue:
            cutoff -= pd.Timedelta(days=7)
        if cutoff != fitted:
            training = archive.history_as_of(state, cutoff)
            bundle = ensemble.fit(training, cutoff)
            small = linear.fit(linear_history(training), cutoff, "research")
            fitted = cutoff
        test = history[history.cutoff == issue].copy()
        bias = archive.recent_bias(state, issue)
        output = ensemble.predict(bundle, test, bias=bias["value"])
        output["linear"] = linear.predict(small, linear_history_for_prediction(test))
        output["price"] = test.price.to_numpy()
        output["price_available_at"] = test.price_available_at.to_numpy()
        output = output[
            (output.status_at_issue == "unknown")
            & (output.target_end <= as_of)
            & (output.price_available_at <= as_of)
        ]
        results.append(output)
    if not results:
        raise ValueError(
            "No historical evaluation issues. Import the research seed first."
        )
    scores = pd.concat(results, ignore_index=True)
    primary = scores[scores.lead_hours.between(48, 72, inclusive="left")]
    names = ["linear", "AP0_60", "AP0_90", "prediction", "candidate"]
    comparison = summarize(primary, names)
    if comparison[0]["slots"] == 0:
        raise ValueError("No common eligible evaluation targets.")
    by_horizon = []
    for day in range(1, 8):
        subset = scores[
            scores.lead_hours.between((day - 1) * 24, day * 24, inclusive="left")
        ]
        by_horizon.append({"day_ahead": day, "comparison": summarize(subset, names)})
    report = {
        "kind": "research-comparison",
        "recipe_id": ensemble.RECIPE_ID,
        "recipe_fingerprint": ensemble.recipe_fingerprint(),
        "evaluated_as_of": as_of.isoformat(),
        "target_start": primary.target_start.min().isoformat(),
        "target_end": primary.target_end.max().isoformat(),
        "issue_days": int(primary.cutoff.nunique()),
        "comparison": comparison,
        "by_horizon": by_horizon,
        "description": "Retrospective paired comparison, weekly fits, previously explored research data. AgilePredict columns reproduce its pinned recipe on common data, not its live service. Main comparison covers unknown 48–72h prices; absent later-horizon scores mean no evidence, not zero error.",
    }
    save_json(Path(state) / "accuracy.json", report)
    directory = Path(state) / "checks"
    directory.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(directory / "comparison.parquet", index=False)
    return report


def linear_history_for_prediction(frame):
    return frame.rename(
        columns={"demand_hh": "demand_mw", "emb_wind": "wind_mw", "solar": "solar_mw"}
    )


def score_issued(state, as_of):
    """Actual saved issues only, matched to observed outcomes; never re-predict."""
    cutoff = pd.Timestamp(as_of)
    f = archive.read_months(state, "predictions")
    labels = archive.prices_as_of(state, cutoff)
    if f.empty or labels.empty:
        return {"description": "No matured live forecasts yet.", "by_horizon": []}
    f = f[f.model_id != "archived-out-of-sample-reference"]
    f = f[(f.target_end <= cutoff) & (f.cutoff < f.target_start)]
    f = f.merge(
        labels[["target_start", "price"]],
        on="target_start",
        how="inner",
        validate="many_to_one",
    )
    rows = []
    # Keep versions separate; hourly issues are descriptive, not independent trials.
    for model_id, group in f.groupby("model_id"):
        for day in range(1, 8):
            s = group[
                group.lead_hours.between((day - 1) * 24, day * 24, inclusive="left")
                & group.status_at_issue.eq("unknown")
            ]
            rows.append(
                {
                    "model_id": model_id,
                    "day_ahead": day,
                    "comparison": summarize(s, ["candidate", "AP0_60", "AP0_90"]),
                }
            )
    result = {
        "description": "Saved live issues only; published-at-issue slots excluded. Overlapping hourly issues are not independent observations.",
        "scored_as_of": cutoff.isoformat(),
        "by_horizon": rows,
    }
    save_json(Path(state) / "checks" / "forward_scores.json", result)
    return result
