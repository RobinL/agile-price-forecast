"""A private folder packed for transport; models still use ordinary local files.

Monthly history stays intact. Only recent snapshots and the current/previous
model binaries travel with it. Never zip the entire checkout or runtime folder.
"""

import hashlib
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

import pandas as pd

from .storage import read_json, save_json

MAX_PACKED = 256_000_000
MAX_UNPACKED = 512_000_000
MAX_FILES = 10_000


def allowed(name):
    return bool(
        re.fullmatch(
            r"(?:model|previous_model|history|latest_snapshot|accuracy|production|portability)\.json"
            r"|models/[0-9a-f]{16}\.(?:joblib|json)"
            r"|history/(?:research_import|processed_snapshots)\.json"
            r"|history/(?:features|prices|predictions)/\d{4}-\d{2}\.parquet"
            r"|snapshots/[0-9TZ]+-(?:live|replay)/(?:inputs|prices|features)\.csv"
            r"|snapshots/[0-9TZ]+-(?:live|replay)/metadata\.json"
            r"|forecasts/[0-9TZ]+-[0-9a-f]+\.json"
            r"|checks/(?:research_parity|forward_scores|linux_parity)\.json",
            name,
        )
    )


def selected_files(state, now):
    """Retain all audit tables/issued exports; bound redundant input snapshots."""
    state = Path(state)
    if state.is_symlink() or any(p.is_symlink() for p in state.rglob("*")):
        raise ValueError("Private state cannot contain symlinks.")
    latest = read_json(state / "latest_snapshot.json")["directory"]
    if not allowed(f"{latest}/metadata.json"):
        raise ValueError("Unexpected latest snapshot path.")
    snapshots = {latest}
    if (state / "portability.json").exists():
        snapshots.add(read_json(state / "portability.json")["snapshot"])
    for path in (state / "snapshots").glob("*/metadata.json"):
        if pd.Timestamp(read_json(path)["as_of"]) >= now - pd.Timedelta(days=30):
            snapshots.add(path.parent.relative_to(state).as_posix())
    models = set()
    for name in ["model.json", "previous_model.json"]:
        if (state / name).exists():
            meta = read_json(state / name)
            if "artifact" in meta:
                artifact = meta["artifact"]
                if not allowed(artifact) or not artifact.startswith("models/"):
                    raise ValueError("Unexpected model artifact path.")
                if not (state / artifact).is_file():
                    raise ValueError("Referenced model binary is missing.")
                models.update([artifact, str(Path(artifact).with_suffix(".json"))])
    selected = []
    for path in sorted(state.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(state).as_posix()
        if not allowed(name):
            continue
        if (
            name.startswith("models/")
            and name.endswith(".joblib")
            and name not in models
        ):
            continue
        if name.startswith("snapshots/") and str(Path(name).parent) not in snapshots:
            continue
        selected.append(path)
    return selected


def pack(state, destination, now=None):
    state, destination = Path(state), Path(destination)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    files = selected_files(state, now)
    if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_UNPACKED:
        raise ValueError(
            "State exceeds the bundle limit; review storage before continuing."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    try:
        with tarfile.open(temporary, "w:gz") as output:
            for path in files:
                output.add(
                    path, arcname=path.relative_to(state).as_posix(), recursive=False
                )
        if temporary.stat().st_size > MAX_PACKED:
            raise ValueError("Compressed state exceeds the 256 MB limit.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return describe(destination)


def describe(path):
    with Path(path).open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"size": Path(path).stat().st_size, "sha256": digest}


def unpack(bundle, destination, expected):
    """Validate before installing; never merge into or overwrite a local folder."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError(
            "Restore needs a new directory, so existing local work stays safe."
        )
    if Path(bundle).stat().st_size > MAX_PACKED or describe(bundle) != expected:
        raise ValueError("State bundle size/checksum does not match its manifest.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        target = Path(temporary) / "state"
        target.mkdir()
        with tarfile.open(bundle, "r:gz") as source:
            names, size = set(), 0
            for member in source:
                size += member.size
                if (
                    not member.isfile()
                    or not allowed(member.name)
                    or member.name in names
                    or size > MAX_UNPACKED
                    or len(names) >= MAX_FILES
                ):
                    raise ValueError(
                        "Unsafe, duplicate or oversized state bundle member."
                    )
                names.add(member.name)
                path = target / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as body, path.open("wb") as output:
                    shutil.copyfileobj(body, output)
        for required in ["model.json", "history.json", "latest_snapshot.json"]:
            if not (target / required).is_file():
                raise ValueError(f"State is missing {required}.")
        snapshot = read_json(target / "latest_snapshot.json")["directory"]
        references = [snapshot]
        if (target / "portability.json").exists():
            references.append(read_json(target / "portability.json")["snapshot"])
        for reference in references:
            if (
                not allowed(reference + "/metadata.json")
                or not (target / reference / "metadata.json").is_file()
            ):
                raise ValueError(
                    "Snapshot reference is unsafe or missing from the bundle."
                )
        # Forget only the bookkeeping entries for snapshots deliberately omitted
        # from transport. Their monthly rows remain permanently in the archive.
        progress = target / "history/processed_snapshots.json"
        if progress.exists():
            present = {p.name for p in (target / "snapshots").iterdir()}
            save_json(
                progress,
                {
                    "snapshots": [
                        s for s in read_json(progress)["snapshots"] if s in present
                    ]
                },
            )
        target.replace(destination)
