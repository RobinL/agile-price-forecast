"""Guard the boundaries that make a forecasting comparison honest."""

import numpy as np
import pandas as pd
import pytest

from agile_forecast import archive, ensemble, features, model_store
from agile_forecast.storage import save_snapshot


class FixedExpert:
    def __init__(self, slope=1):
        self.slope = slope

    def predict(self, frame):
        return frame.lead_hours.to_numpy() * self.slope


def prediction_frame():
    cutoff = pd.Timestamp("2026-09-18T15:30:00Z")
    targets = features.future_intervals(cutoff)
    frame = pd.DataFrame(
        {
            "cutoff": cutoff,
            "target_start": targets,
            "target_end": targets + pd.Timedelta(minutes=30),
            "lead_hours": np.arange(336) / 2,
            "status_at_issue": "unknown",
        }
    )
    for name in features.REQUIRED:
        frame[name] = 10000.0
    return frame


def test_complete_research_window_preserves_level_and_caps_bias():
    f = prediction_frame()
    bundle = {
        "cutoff": f.cutoff.iloc[0],
        "members": {name: FixedExpert() for name in ensemble.MEMBERS},
    }
    bundle["members"]["cat365_base"] = FixedExpert(3)
    result = ensemble.predict(bundle, f, bias=100)
    primary = result[result.policy == "research-48-72"]
    assert len(primary) == 48
    assert primary.candidate.mean() == pytest.approx(primary.prediction.mean() + 4)
    assert primary.candidate.diff().dropna().eq(1).all()
    outside = result[result.policy != "research-48-72"]
    np.testing.assert_array_equal(outside.candidate, outside.prediction)
    assert len(outside) == 288
    # A single missing required input disables the complete-window adjustment,
    # and that missing interval remains a gap instead of a fabricated estimate.
    f.loc[100, "demand_hh"] = np.nan
    incomplete = ensemble.predict(bundle, f, bias=100)
    assert not incomplete.policy.eq("research-48-72").any()
    assert np.isnan(incomplete.loc[100, "candidate"])
    assert incomplete.loc[100, "policy"] == "unavailable"


def test_seven_day_extension_cannot_change_original_feature_context():
    f = prediction_frame()
    f["opmr_peak_demand"], f["minimum_demand"] = 30000, 20000
    f["emb_wind"] = np.arange(len(f))
    longer = features.engineer(f)
    original = features.engineer(f.iloc[:144])
    pd.testing.assert_frame_equal(longer.iloc[:144], original)


def test_cardinal_points_label_interval_ends_and_keep_midnight_endpoint():
    starts = pd.date_range("2026-09-18T23:00:00Z", periods=48, freq="30min")
    f = pd.DataFrame(
        {"target_start": starts, "target_end": starts + pd.Timedelta(minutes=30)}
    )
    clocks = [30, 300, 600, 900, 1200, 1500, 1800, 2100, 2400]
    points = pd.DataFrame(
        {
            "TARGETDATE": 20260919,
            "CP_ST_TIME": clocks,
            "CP_END_TIME": clocks,
            "FORECASTDEMAND": np.arange(9) * 1000 + 20000,
        }
    )
    result = features.attach_profiles(f, points, starts[0], starts[0])
    assert result.demand_hh.iloc[0] == 20000
    assert result.demand_hh.iloc[-1] == 28000
    assert result.demand_hh.iloc[1] == 20200
    assert result.profile_range.eq(8000).all()


def test_observed_price_revisions_are_as_of_and_history_updates_idempotent(tmp_path):
    target = pd.Timestamp("2026-09-19T12:00:00Z")
    for day, price in [(18, 10.0), (19, 12.0), (20, 10.0)]:
        issue = pd.Timestamp(f"2026-09-{day}T15:30:00Z")
        f = pd.DataFrame({"cutoff": [issue], "target_start": [target]})
        prices = pd.DataFrame({"target_start": [target], "price_p_kwh": [price]})
        save_snapshot(
            tmp_path,
            f,
            prices,
            {"mode": "live", "as_of": issue.isoformat()},
            features=f,
        )
        assert archive.update_history(tmp_path) == 1
        assert archive.update_history(tmp_path) == 0
    assert len(archive.read_months(tmp_path, "prices")) == 3
    assert archive.prices_as_of(tmp_path, "2026-09-19T16:00:00Z").price.iloc[0] == 12
    assert archive.prices_as_of(tmp_path, "2026-09-20T16:00:00Z").price.iloc[0] == 10
    assert archive.prices_as_of(tmp_path, "2026-09-18T00:00:00Z").empty


def test_bias_uses_only_matured_known_outcomes_and_one_reference_issue_per_day(
    tmp_path,
):
    cutoff = pd.Timestamp("2026-09-21T15:30:00Z")
    rows = []
    for days in (1, 2, 3):
        issue = cutoff - pd.Timedelta(days=days)
        for delay in (0, 30):
            rows.append(
                {
                    "cutoff": issue + pd.Timedelta(minutes=delay),
                    "target_start": issue + pd.Timedelta(hours=1),
                    "target_end": issue + pd.Timedelta(hours=1.5),
                    "lead_hours": 1.0,
                    "prediction": 10.0 if delay == 0 else -1000.0,
                    "baseline_id": ensemble.BASELINE_ID,
                }
            )
    f = pd.DataFrame(rows)
    archive.append_months(
        tmp_path, "predictions", f, "cutoff", ["cutoff", "target_start"]
    )
    prices = (
        f[["target_start"]]
        .drop_duplicates()
        .assign(price=14.0, price_available_at=cutoff)
    )
    archive.append_months(
        tmp_path,
        "prices",
        prices,
        "target_start",
        ["target_start", "price_available_at"],
    )
    assert archive.recent_bias(tmp_path, cutoff - pd.Timedelta(seconds=1))["value"] == 0
    bias = archive.recent_bias(tmp_path, cutoff)
    assert bias == {"value": 4.0, "samples": 3, "issue_days": 3, "warming_up": False}


def test_training_excludes_late_inputs_and_future_outcomes():
    rows = []
    cutoff = pd.Timestamp("2026-09-18T15:30:00Z")
    for day in range(2, 22):
        issue = cutoff - pd.Timedelta(days=day)
        targets = pd.date_range(
            issue.normalize() + pd.Timedelta(hours=21), periods=48, freq="30min"
        )
        rows.append(
            pd.DataFrame(
                {
                    "cutoff": issue,
                    "target_start": targets,
                    "target_end": targets + pd.Timedelta(minutes=30),
                    "price": 10.0,
                    "price_available_at": targets + pd.Timedelta(minutes=30),
                    "wind_available_at": issue,
                    "long_training_eligible": True,
                }
            )
        )
    f = pd.concat(rows, ignore_index=True)
    expected = ensemble.training_rows(f, cutoff, 60)
    poisoned = f.iloc[:2].copy()
    poisoned["price"] = 99999
    poisoned.loc[0, "price_available_at"] = cutoff + pd.Timedelta(days=1)
    poisoned.loc[1, "wind_available_at"] = cutoff
    actual = ensemble.training_rows(pd.concat([f, poisoned]), cutoff, 60)
    pd.testing.assert_frame_equal(expected, actual)


def test_model_checksum_checked_before_deserializing(tmp_path):
    bundle = {
        "cutoff": pd.Timestamp("2026-09-18T15:30:00Z"),
        "training_sha256": "example",
        "training": [
            {
                "name": "example",
                "rows": 672,
                "training_start": "2026-08-01T00:00:00Z",
                "training_end": "2026-09-17T00:00:00Z",
            }
        ],
    }
    metadata = model_store.save_research(tmp_path, bundle)
    assert model_store.load_research(tmp_path, metadata)["training_sha256"] == "example"
    (tmp_path / metadata["artifact"]).write_bytes(b"untrusted, not a valid model")
    with pytest.raises(ValueError, match="checksum"):
        model_store.load_research(tmp_path, metadata)


def test_demo_cli_does_not_overwrite_real_site(tmp_path, monkeypatch):
    import sys

    from agile_forecast.cli import main

    public = tmp_path / "real-site"
    public.mkdir()
    marker = public / "keep.txt"
    marker.write_text("real")
    monkeypatch.setattr("agile_forecast.cli.DEFAULT_SITE", public)
    state = tmp_path / "demo"
    for command in ["demo", "train", "forecast"]:
        monkeypatch.setattr(
            sys, "argv", ["agile-forecast", "--state-dir", str(state), command]
        )
        main()
    assert marker.read_text() == "real"
    assert not (public / "data").exists()
    assert (state / "site/data/forecast.json").exists()
