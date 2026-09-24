"""Private half-hour demand shadow trial, isolated from website and production state."""

import argparse
import gzip
import hashlib
import io
import json
import os
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, demand_challenger, ensemble, model_store
from .r2 import Store
from .shadow import records
from .storage import read_json, read_table, save_json

PREFIX = "shadow/demand/v1/"
MAX_RECORDS = 1800
MAX_BYTES = 250_000_000
PROTOCOL = {
    "id": demand_challenger.RECIPE,
    "region": "G",
    "horizon": [48, 72],
    "change": "Only AP0_60/AP0_90 retrained with half-hour demand at production fit cutoff; other members and final policy unchanged.",
    "fallback": "Production input-validity rules remain unchanged: missing required demand leaves a gap.",
    "sampling": "Each fresh successful production issue; primary evaluation is first observed 16:30-17:30 London issue per day, paired weekly blocks.",
    "bias": "Separate causal recent-error correction; shared production bias recorded as a secondary comparison during warm-up.",
}


def key_for(cutoff):
    return (
        PREFIX
        + pd.Timestamp(cutoff).tz_convert("UTC").strftime("%Y%m%dT%H%M%S%fZ")
        + ".json.gz"
    )


def inventory(store):
    items, token = [], None
    while True:
        args = {"Prefix": PREFIX, "MaxKeys": 1000}
        if token:
            args["ContinuationToken"] = token
        page = store.request("list_objects_v2", **args)
        items.extend(page.get("Contents", []))
        if len(items) > MAX_RECORDS:
            raise ValueError("Demand trial record budget reached.")
        if not page.get("IsTruncated"):
            return items
        token = page.get("NextContinuationToken")
        if not token or len(items) >= MAX_RECORDS:
            raise ValueError("Demand trial inventory budget reached.")


def snapshot(state):
    folder = Path(state) / read_json(Path(state) / "latest_snapshot.json")["directory"]
    return folder, read_json(folder / "metadata.json")


def restore_history(state, output, store):
    """Read at most one daily reference record per date for the bias calculation."""
    _, meta = snapshot(state)
    cutoff = pd.Timestamp(meta["as_of"])
    items = inventory(store)
    exists = any(item["Key"] == key_for(cutoff) for item in items)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"exists={str(exists).lower()}\n")
    candidates = []
    for item in items:
        name = item["Key"].removeprefix(PREFIX).removesuffix(".json.gz")
        try:
            issue = pd.to_datetime(name, format="%Y%m%dT%H%M%S%fZ", utc=True)
        except ValueError:
            raise ValueError("Unexpected demand shadow object name.") from None
        local = issue.tz_convert("Europe/London")
        if (
            cutoff - pd.Timedelta(days=5) < issue < cutoff
            and 990 <= local.hour * 60 + local.minute < 1050
        ):
            candidates.append((issue, item))
    selected = {}
    for issue, item in sorted(candidates, key=lambda pair: pair[0]):
        selected.setdefault(issue.tz_convert("Europe/London").date(), item)
    previous = []
    for item in selected.values():
        if item["Size"] > 1_000_000:
            raise ValueError("Oversized shadow record.")
        body = store.request("get_object", Key=item["Key"])["Body"].read()
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            raw = stream.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("Oversized uncompressed shadow record.")
        data = json.loads(raw)
        if data["protocol"] != PROTOCOL:
            raise ValueError("Shadow protocol mismatch.")
        if data["smoke_only"] or key_for(data["cutoff"]) != item["Key"]:
            raise ValueError("Invalid reference issue.")
        previous.extend(data["short_predictions"])
    save_json(Path(output) / "previous.json", previous)
    print(f"Restored {len(selected)} reference issues; existing output: {exists}.")


def prepare(state, output, smoke=False, now=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    state, output = Path(state), Path(output)
    folder, meta = snapshot(state)
    cutoff = pd.Timestamp(meta["as_of"])
    if meta["mode"] != "live" or not pd.Timedelta(0) <= now - cutoff <= pd.Timedelta(
        hours=6
    ):
        raise ValueError("Need a fresh live production snapshot.")
    f = read_table(folder / "features.csv")
    if not f.cutoff.eq(cutoff).all():
        raise ValueError("Snapshot issue mismatch.")
    for col in f:
        if col.endswith("_available_at") and (f[col].dropna() > cutoff).any():
            raise ValueError("Future source information in snapshot.")
    metadata = read_json(state / "model.json")
    control = model_store.load_research(state, metadata)
    history = archive.history_as_of(state, control["cutoff"])
    challenger, audit = demand_challenger.fit(control, history)
    previous = pd.DataFrame(read_json(output / "previous.json"))
    if not previous.empty:
        for col in ["cutoff", "target_start", "target_end"]:
            previous[col] = pd.to_datetime(previous[col], utc=True)
    labels = archive.prices_as_of(state, cutoff)
    own_bias = demand_challenger.recent_bias(previous, labels, cutoff)
    production_bias = archive.recent_bias(state, cutoff)
    cp = ensemble.predict(control, f, production_bias["value"])
    hp = ensemble.predict(challenger, f, own_bias["value"])
    shared = ensemble.predict(challenger, f, production_bias["value"])
    known = labels.target_start
    targets = hp[hp.lead_hours.between(48, 72, inclusive="left")].copy()
    if (
        len(targets) != 48
        or targets.target_start.isin(known).any()
        or not targets.policy.eq("research-48-72").all()
        or now >= targets.target_start.min()
    ):
        raise ValueError("Need 48 contiguous unknown future comparison slots.")
    if not targets.target_start.diff().dropna().eq(pd.Timedelta(minutes=30)).all():
        raise ValueError("Non-contiguous targets.")
    saved = archive.read_months(state, "predictions")
    saved = saved[saved.cutoff.eq(cutoff) & saved.model_id.eq(metadata["id"])]
    paired = targets[["target_start", "candidate"]].rename(
        columns={"candidate": "challenger"}
    )
    paired = paired.merge(
        saved[["target_start", "candidate"]].rename(columns={"candidate": "current"}),
        on="target_start",
        validate="one_to_one",
    )
    paired = paired.merge(
        cp[["target_start", "candidate"]].rename(
            columns={"candidate": "replayed_current"}
        ),
        on="target_start",
        validate="one_to_one",
    )
    paired = paired.merge(
        shared[["target_start", "candidate"]].rename(
            columns={"candidate": "challenger_shared_bias"}
        ),
        on="target_start",
        validate="one_to_one",
    )
    if (
        len(paired) != 48
        or not np.isfinite(paired.drop(columns="target_start")).all().all()
    ):
        raise ValueError("Incomplete paired predictions.")
    if not np.allclose(paired.current, paired.replayed_current, rtol=0, atol=1e-8):
        raise ValueError("Production replay differs; refuse comparison.")
    short = hp[hp.lead_hours.between(0, 24, inclusive="left")]
    body = {
        "protocol": PROTOCOL,
        "smoke_only": smoke,
        "cutoff": cutoff.isoformat(),
        "prepared_at": now.isoformat(),
        "git_commit": os.environ.get("GITHUB_SHA", "local"),
        "code_sha256": hashlib.sha256(
            Path(demand_challenger.__file__).read_bytes()
        ).hexdigest(),
        "production_model": metadata,
        "training": audit,
        "history_sha256": hashlib.sha256(
            pd.util.hash_pandas_object(history, index=True).values.tobytes()
        ).hexdigest(),
        "libraries": {name: version(name) for name in model_store.LIBRARIES},
        "production_bias": production_bias,
        "challenger_bias": own_bias,
        "fallback_slots": int((~np.isfinite(f.demand_hh) | f.demand_hh.le(0)).sum()),
        "slots": records(paired),
        # Preserve the actual snapshot, including source availability timestamps.
        # Ratios derived by profile_design are recomputable from these inputs.
        "features": records(f),
        "short_predictions": records(
            short[["cutoff", "target_start", "target_end", "lead_hours", "prediction"]]
        ),
        "outcomes": records(
            labels[labels.target_start >= cutoff - pd.Timedelta(days=120)][
                ["target_start", "price", "price_available_at"]
            ]
        ),
    }
    save_json(output / "record.json", body)
    print(
        "Prepared paired final forecasts; production replay matches exactly. No publication."
    )


def upload(output, store, now=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    data = read_json(Path(output) / "record.json")
    if data["protocol"] != PROTOCOL or data["smoke_only"]:
        raise ValueError("Smoke or incompatible record cannot enter trial.")
    slots = data["slots"]
    times = pd.DatetimeIndex([p["target_start"] for p in slots])
    cutoff = pd.Timestamp(data["cutoff"])
    if not pd.Timedelta(0) <= now - cutoff <= pd.Timedelta(hours=6):
        raise ValueError("Stale or future issue cannot enter trial.")
    leads = (times - cutoff).total_seconds() / 3600
    if (
        len(slots) != 48
        or not times.is_unique
        or not times.is_monotonic_increasing
        or not np.all(
            np.diff(times.as_unit("ns").asi8) == pd.Timedelta(minutes=30).value
        )
        or not np.all((leads >= 48) & (leads < 72))
        or now >= times.min()
    ):
        raise ValueError("Invalid or retrospective shadow targets.")
    if not np.isfinite(
        [
            [p[k] for k in ["current", "challenger", "challenger_shared_bias"]]
            for p in slots
        ]
    ).all():
        raise ValueError("Invalid predictions.")
    raw = json.dumps(data, allow_nan=False).encode()
    packed = gzip.compress(raw, mtime=0)
    if len(raw) > 5_000_000 or len(packed) > 1_000_000:
        raise ValueError("Shadow record too large.")
    items = inventory(store)
    key = key_for(cutoff)
    if any(item["Key"] == key for item in items):
        print("Preserving existing shadow record.")
        return
    if (
        len(items) >= MAX_RECORDS
        or sum(i["Size"] for i in items) + len(packed) > MAX_BYTES
    ):
        raise ValueError("Shadow budget reached; review before extending.")
    store.request(
        "put_object",
        Key=key,
        Body=packed,
        ContentType="application/gzip",
        IfNoneMatch="*",
    )
    print("Saved immutable demand shadow record; public forecast unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["history", "prepare", "upload"])
    parser.add_argument(
        "--state", type=Path, default=Path("runtime_state/demand-source")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("runtime_state/demand-shadow")
    )
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.command == "history":
        restore_history(args.state, args.output, Store.from_environment())
    elif args.command == "prepare":
        prepare(args.state, args.output, args.smoke)
    else:
        upload(args.output, Store.from_environment())


if __name__ == "__main__":
    main()
