"""Built with PriorLabs-TabPFN. CPU-only, local inference; no R2 credentials."""

import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path

os.environ["TABPFN_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.setdefault("SKB_DATA_DIRECTORY", str(Path("runtime_state/skrub").resolve()))
os.environ.setdefault("MPLCONFIGDIR", str(Path("runtime_state/mpl").resolve()))
import numpy as np
import pandas as pd
import torch
from tabpfn import TabPFNRegressor

SHA = "2ab5a07d5c41dfe6db9aa7ae106fc6de898326c2765be66505a07e2868c10736"


def deny(*args, **kwargs):
    raise RuntimeError("Network disabled during shadow inference")


def main():
    root = Path(sys.argv[1])
    checkpoint = Path(sys.argv[2])
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != SHA:
        raise ValueError("Checkpoint checksum mismatch")
    assert set(torch.load(checkpoint, map_location="cpu", weights_only=True)) == {
        "config",
        "state_dict",
    }
    socket.socket.connect = deny
    socket.create_connection = deny
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    data = json.loads((root / "input.json").read_text())
    cols = data["features"]
    context = pd.DataFrame(data["context"])
    target = pd.DataFrame(data["target"])
    started = time.monotonic()
    model = TabPFNRegressor(
        model_path=str(checkpoint.resolve()),
        device="cpu",
        n_estimators=2,
        n_preprocessing_jobs=1,
        random_state=271828,
    )
    model.fit(context[cols].to_numpy(dtype=float), context.price.to_numpy(dtype=float))
    raw = np.minimum(
        model.predict(target[cols].to_numpy(dtype=float), output_type="median"), 100
    )
    base = target.current.to_numpy(dtype=float)
    assert len(raw) == 48 and np.isfinite(raw).all() and np.isfinite(base).all()
    shift = float(0.5 * (raw.mean() - base.mean()))
    from importlib.metadata import version

    result = {
        "checkpoint_sha256": SHA,
        "inference_code_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "seconds": time.monotonic() - started,
        "adjustment": shift,
        "versions": {
            p: version(p)
            for p in ["tabpfn", "torch", "numpy", "pandas", "scikit-learn"]
        },
        "slots": [
            {
                "target_start": r["target_start"],
                "current": float(b),
                "tabpfn": float(t),
                "adjusted": float(b + shift),
            }
            for r, b, t in zip(data["target"], base, raw, strict=True)
        ],
    }
    (root / "prediction.json").write_text(json.dumps(result, allow_nan=False))
    print(
        f"Shadow inference complete: 48 slots in {result['seconds']:.1f}s. No production output changed."
    )


if __name__ == "__main__":
    main()
