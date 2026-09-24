"""Causality, paired comparison and private storage boundaries for the demand trial."""

import gzip
import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from test_cloud import FakeS3

from agile_forecast import archive, demand_challenger, demand_shadow, ensemble, r2
from agile_forecast.storage import read_json, save_json

NOW = pd.Timestamp("2026-09-24T15:37:00Z")


def test_half_hour_member_changes_only_demand_and_preserves_input():
    f = pd.DataFrame({"demand_hh": [20.0, np.nan, 0.0], "demand_peak": [30.0] * 3})
    before = f.copy(deep=True)
    half_hour, peak = Mock(), Mock()
    half_hour.predict.side_effect = lambda frame: frame.demand_peak.to_numpy()
    peak.predict.return_value = np.array([30.0, 30.0, 30.0])
    member = demand_challenger.HalfHourMember(half_hour, peak)
    np.testing.assert_array_equal(member.predict(f), [20, 30, 30])
    pd.testing.assert_frame_equal(f, before)


def test_fit_uses_original_fit_cutoff_and_does_not_mutate_control(monkeypatch):
    history = object()
    peak = object()
    other = object()
    control = {
        "cutoff": NOW,
        "members": {"AP0_60": peak, "AP0_90": peak, "other": other},
    }
    selected = []

    def training_rows(f, cutoff, days):
        assert f is history and cutoff == NOW
        selected.append(days)
        return pd.DataFrame(
            {
                "demand_hh": [20.0] * 672 + [np.nan],
                "demand_peak": 30.0,
                "profile_available_at": NOW - pd.Timedelta(days=2),
                "price_available_at": NOW - pd.Timedelta(days=1),
            }
        )

    class FakeModel:
        def fit(self, rows, cutoff):
            assert len(rows) == 672 and rows.demand_peak.eq(20).all()
            assert cutoff == NOW
            return self

    monkeypatch.setattr(ensemble, "training_rows", training_rows)
    monkeypatch.setattr(ensemble, "AgilePredictRecipe", FakeModel)
    challenger, audit = demand_challenger.fit(control, history)
    assert selected == [60, 90] and len(audit) == 2
    assert control["members"]["AP0_60"] is peak
    assert challenger["members"]["other"] is other
    assert challenger["members"]["AP0_60"].fallback is peak


def test_bias_matches_production_and_excludes_future_revisions(monkeypatch):
    parts = []
    for days in [1, 2, 3]:
        cutoff = NOW - pd.Timedelta(days=days)
        starts = pd.date_range(cutoff.ceil("30min"), periods=48, freq="30min")
        parts.append(
            pd.DataFrame(
                {
                    "cutoff": cutoff,
                    "target_start": starts,
                    "target_end": starts + pd.Timedelta(minutes=30),
                    "prediction": 10.0,
                    "baseline_id": ensemble.BASELINE_ID,
                    "lead_hours": (starts - cutoff).total_seconds() / 3600,
                }
            )
        )
    predictions = pd.concat(parts, ignore_index=True)
    prices = predictions[["target_start", "target_end"]].copy()
    prices["price_available_at"] = prices.target_end
    prices["price"] = 12.0
    future = prices.assign(price=1e9, price_available_at=NOW + pd.Timedelta(days=1))
    prices = pd.concat([prices, future])
    monkeypatch.setattr(
        archive,
        "read_months",
        lambda _, table: prices if table == "prices" else predictions,
    )
    result = demand_challenger.recent_bias(predictions, prices, NOW)
    assert result == archive.recent_bias(None, NOW)
    assert result["value"] == 2.0 and result["issue_days"] == 3
    assert not result["warming_up"]
    assert demand_challenger.recent_bias(
        predictions, prices, NOW - pd.Timedelta(days=2)
    )["warming_up"]


def record(tmp_path, cutoff=NOW, smoke=False):
    starts = pd.date_range(
        cutoff.ceil("30min") + pd.Timedelta(hours=48), periods=48, freq="30min"
    )
    save_json(
        tmp_path / "record.json",
        {
            "protocol": demand_shadow.PROTOCOL,
            "smoke_only": smoke,
            "cutoff": cutoff.isoformat(),
            "slots": [
                {
                    "target_start": t.isoformat(),
                    "current": 10.0,
                    "challenger": 9.0,
                    "challenger_shared_bias": 9.0,
                }
                for t in starts
            ],
            "short_predictions": [],
        },
    )
    return tmp_path


def test_private_prefix_immutable_and_production_inventory_unchanged(tmp_path):
    client = FakeS3()
    client.objects["forecast-v1/production"] = (b"untouched", "e")
    store = r2.Store(client, "private")
    root = record(tmp_path)
    demand_shadow.upload(root, store, now=NOW)
    key = demand_shadow.key_for(NOW)
    assert set(client.objects) == {"forecast-v1/production", key}
    original = client.objects.copy()
    data = read_json(root / "record.json")
    data["slots"][0]["challenger"] = 100
    save_json(root / "record.json", data)
    demand_shadow.upload(root, store, now=NOW)
    assert client.objects == original


@pytest.mark.parametrize("problem", ["smoke", "stale", "duplicate", "nan", "budget"])
def test_invalid_comparisons_cannot_be_saved(tmp_path, monkeypatch, problem):
    client = FakeS3()
    store = r2.Store(client, "private")
    root = record(tmp_path, smoke=problem == "smoke")
    data = read_json(root / "record.json")
    if problem == "duplicate":
        data["slots"][1]["target_start"] = data["slots"][0]["target_start"]
    if problem == "nan":
        data["slots"][0]["challenger"] = None
    if problem == "budget":
        monkeypatch.setattr(demand_shadow, "MAX_BYTES", 1)
    save_json(root / "record.json", data)
    with pytest.raises((ValueError, TypeError)):
        demand_shadow.upload(
            root, store, now=NOW + pd.Timedelta(hours=7 if problem == "stale" else 0)
        )
    assert not client.objects


def test_history_uses_first_genuine_reference_issue_and_not_latest(tmp_path):
    state, output = tmp_path / "state", tmp_path / "out"
    save_json(state / "latest_snapshot.json", {"directory": "snapshot"})
    save_json(state / "snapshot/metadata.json", {"as_of": NOW.isoformat()})
    client = FakeS3()
    for offset in [
        pd.Timedelta(days=1),
        pd.Timedelta(days=1, minutes=-10),
        pd.Timedelta(days=1, hours=2),
        pd.Timedelta(0),
    ]:
        issue = NOW - offset
        body = {
            "protocol": demand_shadow.PROTOCOL,
            "smoke_only": False,
            "cutoff": issue.isoformat(),
            "short_predictions": [{"cutoff": issue.isoformat()}],
        }
        client.objects[demand_shadow.key_for(issue)] = (
            gzip.compress(json.dumps(body).encode()),
            "e",
        )
    demand_shadow.restore_history(state, output, r2.Store(client, "private"))
    previous = read_json(output / "previous.json")
    assert previous == [{"cutoff": (NOW - pd.Timedelta(days=1)).isoformat()}]
