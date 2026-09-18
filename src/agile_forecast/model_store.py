"""Save trusted fitted models privately; promote the JSON pointer last."""

import hashlib
from importlib.metadata import version
from pathlib import Path

import joblib

from .ensemble import RECIPE_ID, recipe_fingerprint
from .storage import read_json, save_json

KIND = "research-level-shape-v1"
LIBRARIES = [
    "numpy",
    "pandas",
    "scikit-learn",
    "catboost",
    "lightgbm",
    "holidays",
    "joblib",
]


def save_research(state, bundle):
    state = Path(state)
    folder = state / "models"
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "fitting.joblib.tmp"
    joblib.dump(bundle, temporary, compress=3)
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    destination = folder / f"{digest[:16]}.joblib"
    temporary.replace(destination)
    metadata = {
        "id": digest[:16],
        "kind": KIND,
        "recipe_id": RECIPE_ID,
        "recipe_fingerprint": recipe_fingerprint(),
        "data_mode": "research",
        "trained_as_of": bundle["cutoff"].isoformat(),
        "training_rows": max(r["rows"] for r in bundle["training"]),
        "training_start": min(r["training_start"] for r in bundle["training"]),
        "training_end": max(r["training_end"] for r in bundle["training"]),
        "members": bundle["training"],
        "training_sha256": bundle["training_sha256"],
        "artifact": str(destination.relative_to(state)),
        "artifact_sha256": digest,
        "libraries": {name: version(name) for name in LIBRARIES},
    }
    save_json(destination.with_suffix(".json"), metadata)
    current = state / "model.json"
    if current.exists():
        old = read_json(current)
        if old["kind"] == "linear-ridge-v1":
            save_json(state / "linear_model.json", old)
        save_json(state / "previous_model.json", old)
    save_json(current, metadata)
    return metadata


def load_research(state, metadata):
    path = (Path(state) / metadata["artifact"]).resolve()
    if not path.is_relative_to((Path(state) / "models").resolve()):
        raise ValueError("Model artifact must be inside this private state directory.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["artifact_sha256"]:
        raise ValueError(
            "Model artifact checksum differs; restore a trusted model or refit."
        )
    if metadata["recipe_fingerprint"] != recipe_fingerprint():
        raise ValueError("Model recipe changed. Refit before forecasting.")
    if metadata["libraries"] != {name: version(name) for name in LIBRARIES}:
        raise ValueError(
            "Model library versions changed. Refit with the locked environment."
        )
    # joblib is executable serialization: load ONLY our own trusted local state
    # (or its private R2 copy). Never load a visitor-supplied model file.
    return joblib.load(path)
