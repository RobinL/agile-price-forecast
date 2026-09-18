"""Small file helpers. Future R2 syncing belongs around this local file boundary."""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE = ROOT / "runtime_state/local"
DEFAULT_SITE = ROOT / "runtime_state/site"


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def read_table(path):
    frame = pd.read_csv(path)
    for name in [
        "issued_at",
        "target_start",
        "price_available_at",
        "inputs_available_at",
        "cutoff",
        "target_end",
        "wind_available_at",
        "wind_issue_at",
        "demand_available_at",
        "demand_issue_at",
        "capacity_available_at",
        "capacity_issue_at",
        "profile_available_at",
        "profile_issue_at",
        "previous_available_at",
        "extra_capacity_available_at",
    ]:
        if name in frame:
            frame[name] = pd.to_datetime(frame[name], utc=True, format="mixed")
    return frame


def save_snapshot(state, inputs, prices, metadata, features=None):
    """Save an immutable snapshot; update the pointer only after it is complete."""
    stamp = pd.Timestamp(metadata["as_of"]).strftime("%Y%m%dT%H%M%S%fZ")
    folder = Path(state) / "snapshots" / f"{stamp}-{metadata['mode']}"
    folder.mkdir(parents=True, exist_ok=False)
    inputs.to_csv(folder / "inputs.csv", index=False)
    prices.to_csv(folder / "prices.csv", index=False)
    if features is not None:
        features.to_csv(folder / "features.csv", index=False)
    save_json(folder / "metadata.json", metadata)
    save_json(
        Path(state) / "latest_snapshot.json",
        {"directory": str(folder.relative_to(state))},
    )
    return folder


def load_snapshot(state):
    folder = Path(state) / read_json(Path(state) / "latest_snapshot.json")["directory"]
    return (
        read_table(folder / "inputs.csv"),
        read_table(folder / "prices.csv"),
        read_json(folder / "metadata.json"),
    )
