"""Thin command wrappers. Each stage can also be called directly in Python."""

import argparse
from pathlib import Path

import pandas as pd
import requests

from . import demo, feeds, forecast, history, model
from .storage import (
    DEFAULT_SITE,
    DEFAULT_STATE,
    load_snapshot,
    read_json,
    read_table,
    save_json,
)


def main():
    parser = argparse.ArgumentParser(
        description="Local Agile forecasting; no R2 or cloud deployment."
    )
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "demo", help="Create made-up input/history in an empty state directory."
    )
    research = sub.add_parser(
        "import-research",
        help="Import existing private tables once; create a dated replay snapshot.",
    )
    research.add_argument("--from", dest="source", type=Path, required=True)
    collect = sub.add_parser(
        "collect", help="Explicitly download today's three public feeds."
    )
    collect.add_argument("--product", default=feeds.PRODUCT)
    train = sub.add_parser("train", help="Fit from local history, with no downloads.")
    train.add_argument(
        "--as-of",
        help="Timezone-aware training cutoff; defaults to the snapshot cutoff.",
    )
    sub.add_parser(
        "evaluate", help="Chronological comparison with the price one week earlier."
    )
    sub.add_parser(
        "forecast", help="Reuse the saved model and inputs, then export public JSON."
    )
    args = parser.parse_args()
    state, site = args.state_dir.resolve(), args.site_dir.resolve()
    try:
        if args.command == "demo":
            demo.create_demo(state)
        elif args.command == "import-research":
            history.import_research(args.source, state)
        elif args.command == "collect":
            feeds.collect(state, args.product)
        elif args.command in {"train", "evaluate"}:
            _, _, snapshot = load_snapshot(state)
            data = read_table(state / "history.csv")
            mode = read_json(state / "history.json")["mode"]
            as_of = pd.Timestamp(getattr(args, "as_of", None) or snapshot["as_of"])
            if as_of.tzinfo is None:
                raise ValueError(
                    "Training cutoff must include a timezone, for example ...T12:00:00Z."
                )
            if args.command == "train":
                save_json(state / "model.json", model.fit(data, as_of, mode))
            else:
                result = model.evaluate(data, as_of, mode)
                save_json(state / "accuracy.json", result)
                print(
                    f"Model MAE: {result['model_mae_p_kwh']:.3f}; week-earlier MAE: {result['week_earlier_mae_p_kwh']:.3f} p/kWh ({result['slots']} matched slots)."
                )
        elif args.command == "forecast":
            result = forecast.export(state, site)
            counts = (
                pd.Series([r["status"] for r in result["slots"]])
                .value_counts()
                .to_dict()
            )
            print(
                f"{result['mode']} forecast: {counts}; output: {site / 'data/forecast.json'}"
            )
    except (ValueError, FileNotFoundError, requests.RequestException) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
