"""Small command wrappers: collect → update history → train when needed → forecast."""

import argparse
from pathlib import Path

import pandas as pd
import requests

from . import (
    archive,
    demo,
    ensemble,
    evaluation,
    feeds,
    forecast,
    history,
    model,
    model_store,
)
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
        description="Local Agile forecasting. Cloud orchestration is a separate agile-cloud command."
    )
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--site-dir",
        type=Path,
        help="Public output directory; demo state defaults to its own separate site.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Create fictional history in an empty state directory.")
    research = sub.add_parser(
        "import-research",
        help="Seed monthly private history from compact research tables, once.",
    )
    research.add_argument("--from", dest="source", type=Path, required=True)
    verify = sub.add_parser(
        "verify-research",
        help="Refit and check parity with saved experimental outputs, offline.",
    )
    verify.add_argument("--from", dest="source", type=Path, required=True)
    collect = sub.add_parser(
        "collect", help="Download bounded current feeds; save a new immutable snapshot."
    )
    collect.add_argument("--product", default=feeds.PRODUCT)
    sub.add_parser(
        "update-history",
        help="Add live snapshots and observed prices to monthly training tables.",
    )
    train = sub.add_parser(
        "train",
        help="Fit from local history only: research model by default, linear for demo.",
    )
    train.add_argument("--model", choices=["research", "linear"])
    train.add_argument(
        "--as-of", help="Timezone-aware cutoff; defaults to the snapshot cutoff."
    )
    evaluate = sub.add_parser(
        "evaluate",
        help="Chronological paired check; research ensemble vs AP recipes and linear baseline.",
    )
    evaluate.add_argument("--model", choices=["research", "linear"])
    sub.add_parser(
        "score",
        help="Score actual saved live forecasts as outcomes arrive, by day ahead.",
    )
    sub.add_parser(
        "forecast",
        help="Load the saved model and snapshot; export a seven-day forecast without downloading/refitting.",
    )
    args = parser.parse_args()
    state = args.state_dir.resolve()
    try:
        if args.command == "demo":
            demo.create_demo(state)
        elif args.command == "import-research":
            history.import_research(args.source, state)
        elif args.command == "verify-research":
            result = evaluation.verify_research(args.source, state)
            print("Research parity passed:", result["maximum_absolute_differences"])
        elif args.command == "collect":
            feeds.collect(state, args.product)
            print(
                "Saved live inputs. Run update-history, then forecast (train first if needed)."
            )
        elif args.command == "update-history":
            print(
                f"Added {archive.update_history(state)} complete live snapshots to monthly history."
            )
        elif args.command in {"train", "evaluate"}:
            _, _, snapshot = load_snapshot(state)
            mode = read_json(state / "history.json")["mode"]
            selected = args.model or ("linear" if mode == "demo" else "research")
            cutoff = pd.Timestamp(getattr(args, "as_of", None) or snapshot["as_of"])
            if cutoff.tzinfo is None:
                raise ValueError(
                    "Training cutoff must include a timezone, for example ...T12:00:00Z."
                )
            if selected == "research":
                if mode == "demo":
                    raise ValueError(
                        "The research model requires real historical forecasts; demo uses the linear model."
                    )
                if args.command == "train":
                    fitted = ensemble.fit(archive.history_as_of(state, cutoff), cutoff)
                    meta = model_store.save_research(state, fitted)
                    print(
                        f"Research model {meta['id']}: six fitted members saved privately."
                    )
                else:
                    result = evaluation.evaluate_research(state, cutoff)
                    for row in result["comparison"]:
                        print(
                            f"{row['model']}: {row['mae_p_kwh']:.3f} p/kWh ({row['slots']} matched slots)"
                        )
            else:
                data = (
                    read_table(state / "history.csv")
                    if mode == "demo"
                    else evaluation.linear_history(archive.history_as_of(state, cutoff))
                )
                if args.command == "train":
                    save_json(state / "model.json", model.fit(data, cutoff, mode))
                else:
                    result = model.evaluate(data, cutoff, mode)
                    save_json(state / "accuracy.json", result)
                    print(
                        f"Linear MAE: {result['model_mae_p_kwh']:.3f}; week-earlier MAE: {result['week_earlier_mae_p_kwh']:.3f} p/kWh."
                    )
        elif args.command == "score":
            result = evaluation.score_issued(state, pd.Timestamp.now(tz="UTC"))
            print(
                result["description"],
                f"{len(result['by_horizon'])} horizon/model groups.",
            )
        elif args.command == "forecast":
            mode = read_json(state / "model.json")["data_mode"]
            site = (
                Path(args.site_dir).resolve()
                if args.site_dir
                else (state / "site" if mode == "demo" else DEFAULT_SITE)
            )
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
