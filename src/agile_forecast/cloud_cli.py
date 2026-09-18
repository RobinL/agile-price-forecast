"""Explicit cloud commands; normal local development never constructs an R2 client."""

import argparse
import tempfile
from pathlib import Path

from . import production, state_bundle
from .r2 import Store
from .storage import DEFAULT_SITE, DEFAULT_STATE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser(
        "prepare-seed", help="Offline: freeze local state and a portability reference."
    )
    prepare.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    prepare.add_argument(
        "--output", type=Path, default=Path("runtime_state/seed.tar.gz")
    )
    seed = sub.add_parser(
        "seed", help="One-time upload; refuses to replace existing R2 state."
    )
    seed.add_argument("--bundle", type=Path, default=Path("runtime_state/seed.tar.gz"))
    pull = sub.add_parser(
        "pull", help="Download trusted state to a NEW private local directory."
    )
    pull.add_argument("--state-dir", type=Path, required=True)
    pull.add_argument(
        "--previous",
        action="store_true",
        help="Restore the previous successful bundle for inspection.",
    )
    run = sub.add_parser(
        "run", help="Restore → collect → update/refit → forecast → save state → export."
    )
    run.add_argument("--site-dir", type=Path, default=DEFAULT_SITE)
    run.add_argument(
        "--refit",
        action="store_true",
        help="Refit now rather than wait until the model is seven days old.",
    )
    check = sub.add_parser(
        "check-site",
        help="Offline: check the public build's file allowlist, schema and size.",
    )
    check.add_argument("--directory", type=Path, default=Path("dist"))
    check.add_argument("--live", action="store_true")
    args = parser.parse_args()
    store = None
    try:
        if args.command == "prepare-seed":
            result = production.prepare_seed(args.state_dir, args.output)
            print(
                f"Prepared private seed: {args.output} ({result['size'] / 1e6:.1f} MB). No upload made."
            )
        elif args.command == "check-site":
            print(production.check_site(args.directory, args.live))
        else:
            store = Store.from_environment()
            if args.command == "pull":
                store.restore(args.state_dir, previous=args.previous)
                print(f"Restored private state into {args.state_dir}.")
            elif args.command == "seed":
                # Check structure before contacting R2 or reserving a write.
                with tempfile.TemporaryDirectory() as directory:
                    state = Path(directory) / "state"
                    state_bundle.unpack(
                        args.bundle, state, state_bundle.describe(args.bundle)
                    )
                    if not (state / "portability.json").is_file():
                        raise ValueError(
                            "Use prepare-seed to include the first-fit reference."
                        )
                store.reserve(seed=True)
                store.publish(args.bundle)
                store.release()
                print(
                    "Private R2 state seeded. No forecast scheduled or website published."
                )
            else:
                store.reserve()
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    state, site = root / "state", root / "site"
                    store.restore(state)
                    production.refresh(state, site, args.refit)
                    state_bundle.pack(state, root / "state.tar.gz")
                    store.publish(root / "state.tar.gz")
                    store.release()
                    production.copy_public_forecast(site, args.site_dir)
                print(
                    "New live forecast saved; private R2 state committed before public export."
                )
    except (ValueError, FileNotFoundError) as error:
        # Best-effort lease release; a killed process instead expires after 20m.
        # Never mask the original failure, and never reset the daily run count.
        if store and store.lease:
            try:
                store.release()
            except ValueError:
                pass
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
