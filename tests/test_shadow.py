"""Regression tests for the experimental storage boundary."""

import gzip
import json
from unittest.mock import Mock

import pandas as pd
import pytest
from test_cloud import NOW, FakeS3, state  # noqa: F401

from agile_forecast import r2, shadow, state_bundle
from agile_forecast.storage import save_json


def output(tmp_path, smoke=False):
    start = pd.Timestamp.now(tz="UTC").ceil("30min") + pd.Timedelta(hours=50)
    slots = [
        {"target_start": str(t), "current": 10.0, "tabpfn": 12.0, "adjusted": 11.0}
        for t in pd.date_range(start, periods=48, freq="30min")
    ]
    save_json(
        tmp_path / "input.json",
        {
            "protocol": shadow.PROTOCOL,
            "smoke_only": smoke,
            "cutoff": str(start - pd.Timedelta(hours=50)),
            "target": [
                {"target_start": s["target_start"], "current": 10.0} for s in slots
            ],
        },
    )
    save_json(tmp_path / "prediction.json", {"slots": slots, "adjustment": 1.0})
    save_json(tmp_path / "outcomes.json", {"prices": []})
    return tmp_path


def test_shadow_only_writes_its_prefix_and_never_overwrites(tmp_path):
    client = FakeS3()
    store = r2.Store(client, "private")
    root = output(tmp_path)
    shadow.upload(root, store)
    assert len(client.objects) == 1
    key = next(iter(client.objects))
    assert key.startswith(shadow.PREFIX)
    before = client.objects.copy()
    shadow.upload(root, store)
    assert client.objects == before
    record = json.loads(gzip.decompress(client.objects[key][0]))
    assert record["prediction"]["adjustment"] == 1


def test_smoke_and_invalid_predictions_cannot_upload(tmp_path):
    store = Mock()
    root = output(tmp_path, smoke=True)
    with pytest.raises(ValueError, match="Smoke"):
        shadow.upload(root, store)
    store.request.assert_not_called()
    data = json.loads((root / "prediction.json").read_text())
    data["slots"][0]["adjusted"] = 100
    save_json(root / "prediction.json", data)
    with pytest.raises(AssertionError):
        shadow.package(root)


def test_production_inventory_ignores_shadow_objects(state, tmp_path):  # noqa: F811
    client = FakeS3()
    for i in range(150):
        client.objects[f"{shadow.PREFIX}{i}.json.gz"] = (b"private", "e")
    store = r2.Store(client, "private", clock=lambda: NOW)
    bundle = tmp_path / "state.tar.gz"
    state_bundle.pack(state, bundle)
    store.reserve(seed=True)
    store.publish(bundle)
    store.release()
    assert sum(k.startswith(shadow.PREFIX) for k in client.objects) == 150


def test_prepare_excludes_unmatured_labels_and_preserves_baseline(
    tmp_path, monkeypatch
):
    import numpy as np

    from agile_forecast import archive

    cutoff = pd.Timestamp("2026-09-19T15:40:00Z")

    def issue(at):
        f = pd.DataFrame(
            {
                "target_start": pd.date_range(
                    at.ceil("30min") + pd.Timedelta(hours=48), periods=48, freq="30min"
                )
            }
        )
        f["cutoff"] = at
        f["target_end"] = f.target_start + pd.Timedelta(minutes=30)
        for c in shadow.FEATURES:
            f[c] = 1.0
        f["lead_hours"] = (f.target_start - at).dt.total_seconds() / 3600
        f["price"] = 12.0
        f["price_available_at"] = f.target_end
        return f

    historic = pd.concat(
        [issue(cutoff - pd.Timedelta(days=n)) for n in range(1, 25)], ignore_index=True
    )
    target = issue(cutoff)
    production = target[["cutoff", "target_start"]].assign(
        candidate=10.0, model_id="frozen"
    )
    monkeypatch.setattr(
        archive,
        "read_months",
        lambda _state, table: (
            pd.concat([historic, target]) if table == "features" else production
        ),
    )
    monkeypatch.setattr(archive, "history_as_of", lambda _state, at: historic.copy())
    monkeypatch.setattr(
        archive,
        "prices_as_of",
        lambda _state, at: historic[historic.price_available_at <= at][
            ["target_start", "price", "price_available_at"]
        ],
    )
    save_json(tmp_path / "model.json", {"id": "frozen"})
    shadow.prepare(tmp_path, tmp_path / "out", now=cutoff + pd.Timedelta(minutes=30))
    data = json.loads((tmp_path / "out/input.json").read_text())
    assert len(data["context"]) == 960 and len(data["target"]) == 48
    assert all(pd.Timestamp(r["target_end"]) <= cutoff for r in data["context"])
    assert all(r["current"] == 10 for r in data["target"])
    assert np.isfinite([r["price"] for r in data["context"]]).all()
