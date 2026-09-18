"""Private monthly tables: forecast inputs, observed prices, and issued predictions.

Only explicit imports or collected snapshots add history. Training never fetches
anything. Updates are idempotent and each file is replaced only when complete.
No database server and no R2 dependency; these are ordinary portable files.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .ensemble import BASELINE_ID, reference_issues
from .storage import read_json, read_table, save_json


def append_months(state, table, frame, date_column, keys):
    if frame.empty:
        return
    root = Path(state) / "history" / table
    root.mkdir(parents=True, exist_ok=True)
    months = pd.to_datetime(frame[date_column], utc=True).dt.strftime("%Y-%m")
    for month, rows in frame.groupby(months):
        destination = root / f"{month}.parquet"
        if destination.exists():
            rows = pd.concat([pd.read_parquet(destination), rows], ignore_index=True)
        rows = (
            rows.drop_duplicates(keys, keep="first")
            .sort_values(keys)
            .reset_index(drop=True)
        )
        temporary = destination.with_suffix(".parquet.tmp")
        rows.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(destination)


def read_months(state, table):
    paths = sorted((Path(state) / "history" / table).glob("*.parquet"))
    if not paths:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)


def prices_as_of(state, cutoff):
    f = read_months(state, "prices")
    if f.empty:
        return f
    # Observed revisions become eligible only at their own recorded time.
    return (
        f[f.price_available_at <= pd.Timestamp(cutoff)]
        .sort_values("price_available_at")
        .drop_duplicates("target_start", keep="last")
    )


def history_as_of(state, cutoff):
    f = read_months(state, "features")
    if f.empty:
        raise ValueError("No research training history. Run import-research first.")
    f = f[
        (f.cutoff < pd.Timestamp(cutoff))
        & (f.cutoff > pd.Timestamp(cutoff) - pd.Timedelta(days=400))
    ].copy()
    labels = prices_as_of(state, cutoff)
    if labels.empty:
        raise ValueError("No eligible observed prices in training history.")
    f = f.drop(columns=["price", "price_available_at"], errors="ignore")
    return (
        f.merge(
            labels[["target_start", "price", "price_available_at"]],
            on="target_start",
            how="left",
            validate="many_to_one",
        )
        .sort_values(["cutoff", "target_start"])
        .reset_index(drop=True)
    )


def update_history(state):
    """Harvest complete live snapshots; never promote demo/replay data to live history."""
    root = Path(state)
    progress = root / "history" / "processed_snapshots.json"
    processed = set(read_json(progress)["snapshots"]) if progress.exists() else set()
    added = 0
    for folder in sorted((root / "snapshots").glob("*")):
        if folder.name in processed or not (folder / "features.csv").exists():
            continue
        metadata = read_json(folder / "metadata.json")
        if metadata["mode"] != "live":
            continue
        features = read_table(folder / "features.csv")
        as_of = pd.Timestamp(metadata["as_of"])
        if not features.cutoff.eq(as_of).all():
            raise ValueError(
                "Snapshot feature issue does not match its recorded collection time."
            )
        prices = read_table(folder / "prices.csv").rename(
            columns={"price_p_kwh": "price"}
        )
        prices["price_available_at"] = as_of
        # Preserve every price change with its first observation time. Repeated
        # identical observations need not duplicate the long-running price table.
        old = read_months(root, "prices")
        if not old.empty:
            latest = (
                old[old.price_available_at <= as_of]
                .sort_values("price_available_at")
                .drop_duplicates("target_start", keep="last")
                .set_index("target_start")
                .price
            )
            # A correction can revert to a previously seen value. Compare with
            # the latest observation, not every value ever seen for this slot.
            prices = prices[prices.price.ne(prices.target_start.map(latest))]
        append_months(root, "features", features, "cutoff", ["cutoff", "target_start"])
        append_months(
            root,
            "prices",
            prices,
            "target_start",
            ["target_start", "price_available_at"],
        )
        processed.add(folder.name)
        save_json(progress, {"snapshots": sorted(processed)})
        added += 1
    return added


def recent_bias(state, cutoff):
    """Completed short-horizon errors from one daily reference issue, not 24 votes/day."""
    cutoff = pd.Timestamp(cutoff)
    f = read_months(state, "predictions")
    empty = {"value": 0.0, "samples": 0, "issue_days": 0, "warming_up": True}
    if f.empty:
        return empty
    f = f[(f.baseline_id == BASELINE_ID) & (f.cutoff < cutoff)]
    f = f[f.cutoff.isin(reference_issues(f))]
    # Re-running a fit for the same issue never revises the reference forecast.
    f = f.sort_values("cutoff", kind="stable").drop_duplicates(
        ["cutoff", "target_start"], keep="first"
    )
    f = f[
        (f.lead_hours >= 0)
        & (f.lead_hours < 24)
        & (f.target_end <= cutoff)
        & (f.target_end > cutoff - pd.Timedelta(days=3))
    ]
    labels = prices_as_of(state, cutoff)
    if f.empty or labels.empty:
        return empty
    f = f.merge(
        labels[["target_start", "price", "price_available_at"]],
        on="target_start",
        how="inner",
        validate="many_to_one",
    )
    f = f[np.isfinite(f.prediction) & np.isfinite(f.price)]
    if f.empty:
        return empty
    days = int(f.cutoff.dt.tz_convert("Europe/London").dt.date.nunique())
    return {
        "value": float((f.price - f.prediction).mean()) if days >= 3 else 0.0,
        "samples": len(f),
        "issue_days": days,
        "warming_up": days < 3,
    }


def record_predictions(state, frame, model_id):
    f = frame.copy()
    f["model_id"] = model_id
    f["baseline_id"] = BASELINE_ID
    append_months(
        state, "predictions", f, "cutoff", ["cutoff", "target_start", "model_id"]
    )
