import json

import jsonschema
import pandas as pd
import pytest

from agile_forecast.demo import create_demo
from agile_forecast.feeds import (
    NESO_DOWNLOAD_HOST,
    MAX_REQUESTS,
    Downloads,
    demand_rows,
    renewable_rows,
)
from agile_forecast.forecast import build, display_intervals, export
from agile_forecast.model import eligible_history, fit
from agile_forecast.storage import (
    ROOT,
    load_snapshot,
    read_json,
    read_table,
    save_json,
    save_snapshot,
)


@pytest.fixture
def example(tmp_path):
    state = tmp_path / "private"
    create_demo(state)
    inputs, prices, metadata = load_snapshot(state)
    history = read_table(state / "history.csv")
    model = fit(history, metadata["as_of"], "demo")
    return state, inputs, prices, metadata, history, model


@pytest.mark.parametrize(
    "date,count", [("2026-03-29T08:00:00Z", 46), ("2026-10-25T08:00:00Z", 50)]
)
def test_calendar_days_keep_clock_change_intervals(date, count):
    intervals = display_intervals(date)
    local = intervals.tz_convert("Europe/London")
    assert (local.date == local[0].date()).sum() == count
    assert intervals.is_unique
    assert len(intervals[intervals >= pd.Timestamp(date)]) == 336


def test_future_answers_and_late_inputs_cannot_change_fit(example):
    _, _, _, meta, history, expected = example
    future = history.iloc[:2].copy()
    future["price_p_kwh"] = 999999
    future.loc[future.index[0], "price_available_at"] = pd.Timestamp(
        "2099-01-01T00:00:00Z"
    )
    future.loc[future.index[1], "inputs_available_at"] = pd.Timestamp(
        "2099-01-01T00:00:00Z"
    )
    actual = fit(pd.concat([history, future]), meta["as_of"], "demo")
    assert actual == expected


def test_published_prices_override_model_and_missing_inputs_leave_gaps(example):
    _, inputs, prices, meta, _, model = example
    published = prices.iloc[-1].target_start
    inputs.loc[inputs.target_start == published, "demand_mw"] = float("nan")
    future = (
        inputs[inputs.target_start > prices.target_start.max()].iloc[0].target_start
    )
    inputs.loc[inputs.target_start == future, "wind_mw"] = float("nan")
    result = build(model, inputs, prices, meta)
    slots = {pd.Timestamp(s["start"]): s for s in result["slots"]}
    assert slots[published]["status"] == "published"
    assert slots[published]["price"] == round(prices.iloc[-1].price_p_kwh, 3)
    assert slots[future]["status"] == "unavailable"
    assert slots[future]["price"] is None


def test_export_contains_only_public_contract_and_does_not_refit(example, tmp_path):
    state, _, _, _, _, model = example
    save_json(state / "model.json", model)
    before = (state / "model.json").read_bytes()
    result = export(state, tmp_path / "public")
    jsonschema.validate(
        result,
        read_json(ROOT / "schemas/forecast.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    )
    assert (state / "model.json").read_bytes() == before
    text = json.dumps(result)
    assert "demand_mw" not in text and str(state) not in text
    assert len(result["slots"]) == 356
    assert result["accuracy"] is None
    assert result["mode"] == "demo"


def test_model_from_future_or_demo_cannot_be_used_on_real_snapshot(example):
    _, inputs, prices, meta, _, model = example
    with pytest.raises(ValueError, match="mix"):
        build(model, inputs, prices, {**meta, "mode": "live"})
    with pytest.raises(ValueError, match="trained after"):
        build({**model, "trained_as_of": "2099-01-01T00:00:00Z"}, inputs, prices, meta)


def test_native_feed_clock_conventions_are_explicit():
    demand = demand_rows(b"GDATETIME,NATIONALDEMAND\n2026-09-18T23:30:00,20000\n")
    assert demand.iloc[0].target_start == pd.Timestamp("2026-09-18T23:00:00Z")
    renewable = renewable_rows(
        b"DATE_GMT,TIME_GMT,EMBEDDED_WIND_FORECAST,EMBEDDED_SOLAR_FORECAST\n2026-09-18T00:00:00,23:00,2000,0\n"
    )
    assert demand.iloc[0].target_start == renewable.iloc[0].target_start


def test_collector_rejects_unexpected_hosts_and_exhausted_budget():
    client = Downloads()
    with pytest.raises(ValueError, match="URL"):
        client.get("test", "https://example.com/file")
    client.calls = MAX_REQUESTS
    with pytest.raises(ValueError, match="budget"):
        client.get("test", "https://api.neso.energy/file")


def test_duplicate_training_targets_have_only_one_vote(example):
    _, _, _, meta, history, _ = example
    assert len(eligible_history(pd.concat([history, history]), meta["as_of"])) == len(
        eligible_history(history, meta["as_of"])
    )


def test_demo_never_overwrites_private_history(example):
    state, *_ = example
    before = (state / "history.csv").read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        create_demo(state)
    assert (state / "history.csv").read_bytes() == before


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        pass

    def iter_content(self, _):
        yield b"example CSV"


def test_neso_redirect_is_bounded_and_signed_url_is_not_published(monkeypatch):
    destination = f"https://{NESO_DOWNLOAD_HOST}/public.csv?X-Amz-Signature=example"
    replies = iter([FakeResponse(302, {"Location": destination}), FakeResponse(200)])
    monkeypatch.setattr(
        "agile_forecast.feeds.requests.get", lambda *a, **k: next(replies)
    )
    client = Downloads()
    source = "https://api.neso.energy/download/example.csv"
    assert client.get("NESO", source) == b"example CSV"
    assert client.calls == 2
    assert client.records[0]["url"] == source
    assert "Signature" not in json.dumps(client.records)


def test_redirect_to_unexpected_host_is_not_followed(monkeypatch):
    monkeypatch.setattr(
        "agile_forecast.feeds.requests.get",
        lambda *a, **k: FakeResponse(302, {"Location": "https://example.com/no"}),
    )
    client = Downloads()
    with pytest.raises(ValueError, match="URL"):
        client.get("NESO", "https://api.neso.energy/download/example.csv")
    assert client.calls == 1


def test_failed_stale_export_keeps_previous_website_file(example, tmp_path):
    state, inputs, prices, meta, _, model = example
    site = tmp_path / "public"
    save_json(state / "model.json", model)
    export(state, site)
    before = (site / "data/forecast.json").read_bytes()
    old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=3)
    save_snapshot(
        state, inputs, prices, {**meta, "mode": "live", "as_of": old.isoformat()}
    )
    with pytest.raises(ValueError, match="stale"):
        export(state, site)
    assert (site / "data/forecast.json").read_bytes() == before
