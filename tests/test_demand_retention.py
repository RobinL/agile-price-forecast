import pandas as pd
from agile_forecast.feeds import retain_demand_profiles
from agile_forecast.storage import save_json


def test_advancing_feed_retains_only_fresh_previously_known_matching_slots(tmp_path):
    now = pd.Timestamp("2026-09-19T09:00Z")
    targets = pd.date_range("2026-09-20", periods=6, freq="30min", tz="UTC")
    frame = pd.DataFrame(
        {"target_start": targets, "demand_hh": [30000] + [float("nan")] * 5}
    )
    columns = [
        "demand_hh_ramp",
        "profile_peak",
        "profile_min",
        "profile_range",
        "profile_mean",
    ]
    for col in columns:
        frame[col] = 1.0
    frame["profile_available_at"] = frame["profile_issue_at"] = now
    old = frame.copy()
    old["demand_hh"] = [21000, 22000, 23000, 24000, 25000, 26000]
    old["profile_issue_at"] = now - pd.Timedelta(hours=24)
    old["profile_available_at"] = now - pd.Timedelta(hours=23)
    old.loc[2, "profile_issue_at"] = now - pd.Timedelta(hours=121)
    old.loc[3, "profile_available_at"] = now + pd.Timedelta(hours=1)
    old.loc[4, "profile_issue_at"] = now + pd.Timedelta(hours=1)
    # Different target must not be substituted into a missing slot.
    old.loc[5, "target_start"] += pd.Timedelta(days=1)
    folder = tmp_path / "snapshots/previous-live"
    save_json(
        folder / "metadata.json",
        {"mode": "live", "as_of": (now - pd.Timedelta(hours=23)).isoformat()},
    )
    old.to_csv(folder / "features.csv", index=False)
    result = retain_demand_profiles(tmp_path, frame, now)
    assert result.demand_hh.iloc[:2].tolist() == [30000, 22000]
    assert result.demand_hh.iloc[2:].isna().all()
    assert result.profile_issue_at.iloc[1] == now - pd.Timedelta(hours=24)
    assert result.profile_available_at.iloc[1] == now - pd.Timedelta(hours=23)
    assert frame.demand_hh.iloc[1:].isna().all()
