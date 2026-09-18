"""The same local pipeline, with explicit preparation and publication gates."""

import platform
import re
import tempfile
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd

from . import archive, ensemble, evaluation, feeds, forecast, model_store, state_bundle
from .storage import ROOT, load_snapshot, read_json, read_table, save_json

PARITY_COLUMNS = ensemble.MEMBERS + ["cat365_base", "prediction", "candidate"]


def bounded_extratrees_refit(comparisons, diagnostics):
    """Accept only the measured macOS ARM → Linux x86 ExtraTrees variation.

    This is a numerical deployment check, not an accuracy claim. Keep strict
    parity everywhere else; the final forecast may move at most a tenth of a
    penny per kWh at any interval, and a hundredth on average.
    """
    if (
        set(comparisons) != set(PARITY_COLUMNS)
        or not diagnostics["seed_inference_matches"]
    ):
        return False
    for name, values in comparisons.items():
        if (
            values["matched_finite_rows"] < 48
            or values["missingness_mismatches"]
            or values["infinite_rows"]
        ):
            return False
        maximum, mean = (0.001, 0.001)
        if name in {"AP0_60", "AP0_90"}:
            maximum, mean = 0.1, 0.03
        elif name in {"prediction", "candidate"}:
            maximum, mean = 0.1, 0.01
        if (
            values["maximum_difference_p_kwh"] > maximum
            or values["mean_absolute_difference_p_kwh"] > mean
        ):
            return False
    for name in ["AP0_60", "AP0_90"]:
        for estimator in ["CatBoostRegressor", "LGBMRegressor", "ExtraTreesRegressor"]:
            values = diagnostics["estimators"].get(f"{name}/{estimator}")
            if not values or values["rows"] < 48:
                return False
            maximum, mean = (
                (0.3, 0.1) if estimator == "ExtraTreesRegressor" else (0.001, 0.001)
            )
            if (
                not np.isfinite([values["maximum"], values["mean"]]).all()
                or values["maximum"] > maximum
                or values["mean"] > mean
            ):
                return False
    return True


def platform_id():
    return f"{platform.system()}-{platform.machine()}"


def prepare_seed(state, destination):
    """Freeze a compact seed and predictions for the first Linux refit to match.

    This is offline and leaves the developer's working files untouched.
    """
    state, destination = Path(state), Path(destination)
    metadata = read_json(state / "model.json")
    if metadata["kind"] != model_store.KIND:
        raise ValueError(
            "Production needs the trained research ensemble, not the demo model."
        )
    _, _, snapshot = load_snapshot(state)
    if snapshot["mode"] != "live":
        raise ValueError("Seed from a real collected input snapshot.")
    bundle = model_store.load_research(state, metadata)
    directory = read_json(state / "latest_snapshot.json")["directory"]
    frame = read_table(state / directory / "features.csv")
    predictions = ensemble.predict(bundle, frame)[PARITY_COLUMNS]
    if predictions.prediction.notna().sum() < 48:
        raise ValueError(
            "Seed needs at least 48 valid forecast intervals for the portability check."
        )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        description = state_bundle.pack(state, root / "source.tar.gz")
        copied = root / "state"
        state_bundle.unpack(root / "source.tar.gz", copied, description)
        # Seed should test Linux afresh, even if the source was restored from R2.
        (copied / "production.json").unlink(missing_ok=True)
        save_json(
            copied / "portability.json",
            {
                "snapshot": directory,
                "trained_as_of": metadata["trained_as_of"],
                "training_sha256": metadata["training_sha256"],
                "recipe_fingerprint": metadata["recipe_fingerprint"],
                "libraries": metadata["libraries"],
                "columns": PARITY_COLUMNS,
                "expected": predictions.astype(object)
                .where(predictions.notna(), None)
                .values.tolist(),
            },
        )
        return state_bundle.pack(copied, destination)


def ensure_portable_model(state):
    """First fit on a new OS/architecture must reproduce the frozen local seed."""
    marker = state / "production.json"
    if marker.exists() and read_json(marker)["platform"] == platform_id():
        return
    reference = read_json(state / "portability.json")
    if reference["recipe_fingerprint"] != ensemble.recipe_fingerprint():
        raise ValueError(
            "Model recipe changed since the seed; prepare a new reviewed reference."
        )
    cutoff = pd.Timestamp(reference["trained_as_of"])
    fitted = ensemble.fit(archive.history_as_of(state, cutoff), cutoff)
    if fitted["training_sha256"] != reference["training_sha256"]:
        raise ValueError(
            "Portability refit training data differs from the saved local model."
        )
    frame = read_table(state / reference["snapshot"] / "features.csv")
    actual = ensemble.predict(fitted, frame)[reference["columns"]].to_numpy()
    expected = np.asarray(reference["expected"], dtype=float)
    if actual.shape != expected.shape:
        raise ValueError(
            "First production refit differs from the local reference: "
            f"output shape {actual.shape}, expected {expected.shape}; do not publish."
        )
    # Report only aggregate differences, not private input rows or credentials.
    # These diagnostics are essential when a different CPU/OS fails parity:
    # measure which member changed before considering any tolerance change.
    comparisons = {}
    print(
        f"Portability comparison on {platform_id()} (tolerance 0.001 p/kWh):",
        flush=True,
    )
    for index, name in enumerate(reference["columns"]):
        observed, original = actual[:, index], expected[:, index]
        finite = np.isfinite(observed) & np.isfinite(original)
        errors = np.abs(observed[finite] - original[finite])
        differences = ~np.isclose(
            observed, original, atol=0.001, rtol=0, equal_nan=True
        )
        comparisons[name] = {
            "matched_finite_rows": int(finite.sum()),
            "rows_outside_tolerance": int(differences.sum()),
            "missingness_mismatches": int(
                (np.isnan(observed) != np.isnan(original)).sum()
            ),
            "infinite_rows": int(np.isinf(observed).sum() + np.isinf(original).sum()),
            "maximum_difference_p_kwh": float(errors.max()) if len(errors) else None,
            "mean_absolute_difference_p_kwh": float(errors.mean())
            if len(errors)
            else None,
        }
        print(f"  {name}: {comparisons[name]}", flush=True)
    diagnostics = None
    policy = "strict-0.001"
    if not np.allclose(actual, expected, atol=0.001, rtol=0, equal_nan=True):
        diagnostics = diagnose_refit(state, fitted, frame, reference)
        if not diagnostics or not bounded_extratrees_refit(comparisons, diagnostics):
            raise ValueError(
                "First production refit differs from the local reference beyond "
                "the checked ExtraTrees portability limits; do not publish."
            )
        policy = "bounded-extratrees-refit-v1"
        print(
            "Accepted bounded ExtraTrees refit variation; all other estimators passed strict parity.",
            flush=True,
        )
    maximum = float(np.nanmax(np.abs(actual - expected)))
    metadata = model_store.save_research(state, fitted)
    if metadata["libraries"] != reference["libraries"]:
        raise ValueError("Production libraries differ from the saved local reference.")
    report = {
        "platform": platform_id(),
        "maximum_difference_p_kwh": maximum,
        "comparisons": comparisons,
        "policy": policy,
        "estimator_diagnostics": diagnostics,
        "model_id": metadata["id"],
        "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    save_json(state / "checks/linux_parity.json", report)
    save_json(marker, report)
    print(
        f"Portability refit passed ({policy}): maximum difference {maximum:.6f} p/kWh."
    )


def diagnose_refit(state, fitted, frame, reference):
    """Separate saved-model inference portability from platform-dependent refitting.

    Load only our own checksummed, version-checked seed for this diagnostic. It
    never becomes the production model: production still uses a checked refit.
    """
    metadata = read_json(state / "model.json")
    if metadata.get("kind") != model_store.KIND:
        return
    original = model_store.load_research(state, metadata)
    saved_predictions = ensemble.predict(original, frame)
    expected = np.asarray(reference["expected"], dtype=float)
    transported = saved_predictions[reference["columns"]].to_numpy()
    matches = bool(
        np.allclose(transported, expected, atol=0.001, rtol=0, equal_nan=True)
    )
    print(
        "Saved seed inference matches its original outputs:",
        matches,
        flush=True,
    )
    diagnostics = {"seed_inference_matches": matches, "estimators": {}}
    valid = saved_predictions.prediction.notna()
    for name in ["AP0_60", "AP0_90"]:
        before, after = original["members"][name], fitted["members"][name]
        design = ensemble.ap_design(frame.loc[valid], before.cutoff, True)
        for index, (old, new) in enumerate(
            zip(before.models, after.models, strict=True)
        ):
            old_x = design.fillna(before.medians) if index == 2 else design
            new_x = design.fillna(after.medians) if index == 2 else design
            errors = np.abs(new.predict(new_x) - old.predict(old_x))
            diagnostics["estimators"][f"{name}/{type(old).__name__}"] = {
                "rows": len(errors),
                "maximum": float(errors.max()),
                "mean": float(errors.mean()),
            }
            print(
                f"  {name}/{type(old).__name__}: "
                f"max={errors.max():.9f}, mean={errors.mean():.9f} p/kWh",
                flush=True,
            )
    return diagnostics


def validate_forecast(payload, now=None):
    jsonschema.validate(
        payload,
        read_json(ROOT / "schemas/forecast.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    )
    if payload["mode"] != "live":
        raise ValueError("Cloud publication requires a live forecast.")
    if now is not None:
        now = pd.Timestamp(now)
        age = now - pd.Timestamp(payload["issued_at"])
        if not pd.Timedelta(0) <= age <= pd.Timedelta(hours=2):
            raise ValueError(
                "Forecast is stale or future-dated; leave the published site unchanged."
            )
        future = [r for r in payload["slots"] if pd.Timestamp(r["start"]) > now]
        if sum(r["status"] == "predicted" for r in future) < 48:
            raise ValueError(
                "Too few usable forecast intervals; leave the published site unchanged."
            )


def refresh(state, site, force_refit=False):
    """Run on an isolated restored copy. Any exception prevents R2 promotion."""
    state, site = Path(state), Path(site)
    ensure_portable_model(state)
    feeds.collect(state)
    archive.update_history(state)
    _, _, snapshot = load_snapshot(state)
    cutoff = pd.Timestamp(snapshot["as_of"])
    metadata = read_json(state / "model.json")
    if force_refit or cutoff - pd.Timestamp(metadata["trained_as_of"]) >= pd.Timedelta(
        days=7
    ):
        print("Refitting the fixed research recipe from eligible historical examples.")
        model_store.save_research(
            state, ensemble.fit(archive.history_as_of(state, cutoff), cutoff)
        )
    payload = forecast.export(state, site)
    validate_forecast(payload, pd.Timestamp.now(tz="UTC"))
    evaluation.score_issued(state, cutoff)
    return payload


def check_site(directory, live=False):
    """Pages receives ONLY the explicit public contract and bundled static assets."""
    directory = Path(directory)
    files = []
    required = {"index.html", "data/forecast.json", "third-party-licences.txt"}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Public build cannot contain symlinks.")
        if not path.is_file():
            continue
        name = path.relative_to(directory).as_posix()
        if name not in required and not re.fullmatch(
            r"assets/[\w-]+\.(?:js|css)", name
        ):
            raise ValueError(f"Unexpected public build file: {name}")
        files.append(path)
    if any(not (directory / name).is_file() for name in required):
        raise ValueError("Public build is incomplete.")
    if not (directory / "third-party-licences.txt").read_text().strip():
        raise ValueError("Public build is missing software licence notices.")
    size = sum(path.stat().st_size for path in files)
    if size > 10_000_000:
        raise ValueError("Public build exceeds the 10 MB limit.")
    payload = read_json(directory / "data/forecast.json")
    if live:
        validate_forecast(payload)
    else:
        jsonschema.validate(payload, read_json(ROOT / "schemas/forecast.schema.json"))
    return {"files": len(files), "bytes": size, "mode": payload["mode"]}


def copy_public_forecast(source, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    # Copy just the explicit public output, never the private state tree.
    payload = read_json(Path(source) / "data/forecast.json")
    save_json(destination / "data/forecast.json", payload)
