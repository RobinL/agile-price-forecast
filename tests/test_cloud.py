"""Exercise the cloud failure boundaries without credentials or a live bucket."""

import io
import json
import tarfile
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from botocore.exceptions import ClientError

from agile_forecast import production, r2, state_bundle
from agile_forecast.storage import ROOT, read_json, save_json

NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)
SNAPSHOT = "snapshots/20260918T110000000000Z-live"


class FakeS3:
    """In-memory objects with the same conditional-write failure behaviour."""

    def __init__(self):
        self.objects = {}
        self.revision = 0
        self.fail_bundle = False
        self.fail_pointer = False

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        data, etag = self.objects[Key]
        return {"Body": io.BytesIO(data), "ETag": etag, "ContentLength": len(data)}

    def put_object(self, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None, **kwargs):
        old = self.objects.get(Key)
        if (IfMatch and (not old or old[1] != IfMatch)) or (IfNoneMatch == "*" and old):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        data = Body.read() if hasattr(Body, "read") else Body
        if (self.fail_bundle and r2.bundle_key(Key)) or (
            self.fail_pointer and Key == r2.MANIFEST
        ):
            raise ClientError({"Error": {"Code": "InternalError"}}, "PutObject")
        self.revision += 1
        etag = f'"{self.revision}"'
        self.objects[Key] = (data, etag)
        return {"ETag": etag}

    def list_objects_v2(self, Bucket, MaxKeys):
        return {
            "IsTruncated": len(self.objects) > MaxKeys,
            "Contents": [
                {"Key": k, "Size": len(v[0])} for k, v in self.objects.items()
            ][:MaxKeys],
        }

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


@pytest.fixture
def state(tmp_path):
    root = tmp_path / "local"
    save_json(root / "model.json", {"kind": "test-model"})
    save_json(root / "history.json", {"mode": "research"})
    save_json(root / "latest_snapshot.json", {"directory": SNAPSHOT})
    save_json(
        root / SNAPSHOT / "metadata.json", {"as_of": NOW.isoformat(), "mode": "live"}
    )
    save_json(
        root / "history/processed_snapshots.json",
        {"snapshots": [SNAPSHOT.split("/")[1], "retired"]},
    )
    (root / SNAPSHOT / "features.csv").write_text("example\n1\n")
    return root


@pytest.fixture
def bundle(state, tmp_path):
    destination = tmp_path / "state.tar.gz"
    state_bundle.pack(state, destination, NOW)
    return destination


def seeded_store(bundle):
    client = FakeS3()
    store = r2.Store(client, "test-bucket", clock=lambda: NOW)
    store.reserve(seed=True)
    store.publish(bundle)
    store.release()
    return client, store


def test_bundle_round_trip_excludes_secrets_and_unrelated_files(state, tmp_path):
    (state / ".env").write_text("DO_NOT_UPLOAD=secret")
    (state / ".transparency_token").write_text("never-upload")
    (state / "history.csv").write_text("obsolete duplicate")
    save_json(
        state / "snapshots/20250101T000000Z-live/metadata.json",
        {"as_of": "2025-01-01T00:00:00Z"},
    )
    historical = state / "history/features/2025-01.parquet"
    historical.parent.mkdir(parents=True)
    historical.write_bytes(b"audit history is retained")
    path = tmp_path / "bundle.tar.gz"
    description = state_bundle.pack(state, path, NOW)
    restored = tmp_path / "restored"
    state_bundle.unpack(path, restored, description)
    assert not (restored / ".env").exists()
    assert not (restored / ".transparency_token").exists()
    assert not (restored / "history.csv").exists()
    assert not (restored / "snapshots/20250101T000000Z-live").exists()
    assert (
        restored / "history/features/2025-01.parquet"
    ).read_bytes() == historical.read_bytes()
    assert read_json(restored / "history/processed_snapshots.json")["snapshots"] == [
        SNAPSHOT.split("/")[1]
    ]
    with pytest.raises(ValueError, match="new directory"):
        state_bundle.unpack(path, restored, description)


def test_corruption_cannot_install_partial_state(bundle, tmp_path):
    description = state_bundle.describe(bundle)
    bundle.write_bytes(bundle.read_bytes() + b"tampered")
    destination = tmp_path / "restore"
    with pytest.raises(ValueError, match="checksum"):
        state_bundle.unpack(bundle, destination, description)
    assert not destination.exists()


@pytest.mark.parametrize(
    "name,symlink", [("../escape", False), ("/tmp/escape", False), ("model.json", True)]
)
def test_tar_paths_and_links_are_rejected(tmp_path, name, symlink):
    path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(path, "w:gz") as output:
        member = tarfile.TarInfo(name)
        if symlink:
            member.type, member.linkname = tarfile.SYMTYPE, "../escape"
        output.addfile(member)
    with pytest.raises(ValueError, match="Unsafe"):
        state_bundle.unpack(path, tmp_path / "restore", state_bundle.describe(path))
    assert not (tmp_path / "restore").exists()


def test_snapshot_retention_keeps_the_original_portability_reference(state, tmp_path):
    old = "snapshots/20250101T000000Z-live"
    save_json(state / old / "metadata.json", {"as_of": "2025-01-01T00:00:00Z"})
    save_json(state / "portability.json", {"snapshot": old})
    selected = {
        p.relative_to(state).as_posix()
        for p in state_bundle.selected_files(state, pd.Timestamp(NOW))
    }
    assert old + "/metadata.json" in selected


def test_json_snapshot_reference_cannot_escape_the_restored_state(state, tmp_path):
    save_json(state / "portability.json", {"snapshot": "../../outside"})
    bundle = tmp_path / "unsafe-reference.tar.gz"
    description = state_bundle.pack(state, bundle, NOW)
    with pytest.raises(ValueError, match="reference is unsafe"):
        state_bundle.unpack(bundle, tmp_path / "restore", description)
    assert not (tmp_path / "restore").exists()


def test_r2_seed_restore_and_repeated_promotion_keep_two_bundles(bundle, tmp_path):
    client, store = seeded_store(bundle)
    store.restore(tmp_path / "restore")
    assert read_json(tmp_path / "restore/history.json")["mode"] == "research"
    for _ in range(3):
        store = r2.Store(client, "test-bucket", clock=lambda: NOW)
        store.reserve()
        store.publish(bundle)
        store.release()
    assert len([key for key in client.objects if r2.bundle_key(key)]) == 2
    store.restore(tmp_path / "previous", previous=True)
    with pytest.raises(ValueError, match="already has state"):
        r2.Store(client, "test-bucket", clock=lambda: NOW).reserve(seed=True)


@pytest.mark.parametrize("failure", ["fail_bundle", "fail_pointer"])
def test_failed_upload_or_pointer_update_preserves_last_good_state(bundle, failure):
    client, _ = seeded_store(bundle)
    store = r2.Store(client, "test-bucket", clock=lambda: NOW)
    store.reserve()
    before = store.manifest["current"].copy()
    setattr(client, failure, True)
    with pytest.raises(ValueError, match="failed"):
        store.publish(bundle)
    assert json.loads(client.objects[r2.MANIFEST][0])["current"] == before


def test_lease_and_daily_processing_budget_survive_failed_runs(bundle):
    client, _ = seeded_store(bundle)
    active = r2.Store(client, "test-bucket", clock=lambda: NOW)
    active.reserve()
    with pytest.raises(ValueError, match="writer lease"):
        r2.Store(client, "test-bucket", clock=lambda: NOW).reserve()
    active.release()
    for _ in range(30):
        active = r2.Store(client, "test-bucket", clock=lambda: NOW)
        active.reserve()
        active.release()  # No successful forecast, but the attempt still counts.
    with pytest.raises(ValueError, match="daily"):
        r2.Store(client, "test-bucket", clock=lambda: NOW).reserve()
    tomorrow = r2.Store(client, "test-bucket", clock=lambda: NOW + timedelta(days=1))
    tomorrow.reserve()
    assert tomorrow.manifest["runs"] == 1


def test_expired_writer_cannot_promote_and_conditional_writes_cannot_clobber(bundle):
    client, _ = seeded_store(bundle)
    clock = [NOW]
    stale = r2.Store(client, "test-bucket", clock=lambda: clock[0])
    stale.reserve()
    clock[0] += timedelta(minutes=21)
    current = r2.Store(client, "test-bucket", clock=lambda: clock[0])
    current.reserve()
    with pytest.raises(ValueError, match="expired"):
        stale.publish(bundle)
    with pytest.raises(ValueError, match="concurrently"):
        stale.write_manifest(stale.manifest)
    assert json.loads(client.objects[r2.MANIFEST][0])["lease"]["id"] == current.lease


def test_storage_and_request_budgets_stop_writes(bundle, monkeypatch):
    client, _ = seeded_store(bundle)
    store = r2.Store(client, "test-bucket", clock=lambda: NOW)
    store.reserve()
    before = set(client.objects)
    monkeypatch.setattr(r2, "MAX_STORAGE", 1)
    with pytest.raises(ValueError, match="storage budget"):
        store.publish(bundle)
    assert set(client.objects) == before
    store.calls = r2.MAX_REQUESTS
    with pytest.raises(ValueError, match="request budget"):
        store.read_manifest()
    store.wire_calls = r2.MAX_REQUESTS
    with pytest.raises(ValueError, match="request budget"):
        store.before_send()


def test_public_artifact_rejects_private_files_and_demo_for_live_deployment(tmp_path):
    (tmp_path / "index.html").write_text("<html>public</html>")
    fixture = read_json(ROOT / "fixtures/site/data/forecast.json")
    save_json(tmp_path / "data/forecast.json", fixture)
    assert production.check_site(tmp_path)["mode"] == "demo"
    with pytest.raises(ValueError, match="live forecast"):
        production.check_site(tmp_path, live=True)
    (tmp_path / "model.joblib").write_bytes(b"private")
    with pytest.raises(ValueError, match="Unexpected public"):
        production.check_site(tmp_path)


def test_publication_rejects_stale_inputs_or_too_few_predictions():
    fixture = read_json(ROOT / "fixtures/site/data/forecast.json")
    fixture["mode"] = "live"
    now = pd.Timestamp(fixture["issued_at"])
    production.validate_forecast(fixture, now)
    with pytest.raises(ValueError, match="stale"):
        production.validate_forecast(fixture, now + pd.Timedelta(hours=3))
    for slot in fixture["slots"]:
        slot["status"], slot["price"], slot["policy"] = (
            "unavailable",
            None,
            "unavailable",
        )
    with pytest.raises(ValueError, match="Too few"):
        production.validate_forecast(fixture, now)


@pytest.mark.parametrize("difference", [0.0, 0.01])
def test_first_platform_fit_must_match_before_model_promotion(
    state, monkeypatch, difference, capsys
):
    save_json(
        state / "portability.json",
        {
            "snapshot": SNAPSHOT,
            "trained_as_of": NOW.isoformat(),
            "recipe_fingerprint": production.ensemble.recipe_fingerprint(),
            "training_sha256": "same-eligible-data",
            "libraries": {},
            "columns": ["candidate"],
            "expected": [[10.0]],
        },
    )
    monkeypatch.setattr(production.archive, "history_as_of", lambda *args: None)
    monkeypatch.setattr(
        production.ensemble,
        "fit",
        lambda *args: {"training_sha256": "same-eligible-data"},
    )
    monkeypatch.setattr(
        production.ensemble,
        "predict",
        lambda *args: pd.DataFrame({"candidate": [10 + difference]}),
    )
    promoted = []

    def save(*args):
        promoted.append(True)
        return {"id": "checked-model", "libraries": {}}

    monkeypatch.setattr(production.model_store, "save_research", save)
    if difference:
        with pytest.raises(ValueError, match="differs from the local reference"):
            production.ensure_portable_model(state)
        assert not promoted
        assert not (state / "production.json").exists()
        output = capsys.readouterr().out
        assert "candidate:" in output
        assert "'rows_outside_tolerance': 1" in output
        assert "'maximum_difference_p_kwh':" in output
    else:
        production.ensure_portable_model(state)
        production.ensure_portable_model(state)  # Reuse the checked fitted model.
        assert len(promoted) == 1
        assert read_json(state / "production.json")["maximum_difference_p_kwh"] == 0
        assert (
            read_json(state / "production.json")["comparisons"]["candidate"][
                "rows_outside_tolerance"
            ]
            == 0
        )
