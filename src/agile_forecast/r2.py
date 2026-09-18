"""Bounded private R2 storage. No web routes, database or background service.

current.json is both an atomic pointer and a short-lived writer lease. A failed
upload cannot replace the previous successful state. Only our generated bundles
are eligible for cleanup; use a dedicated private bucket for this project.
"""

import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from . import state_bundle

PREFIX = "forecast-v1/"
MANIFEST = PREFIX + "current.json"
MAX_REQUESTS = 100
MAX_RUNS = 32
MAX_STORAGE = 2_000_000_000


def utc_now():
    return datetime.now(UTC)


def bundle_key(key):
    return bool(re.fullmatch(r"forecast-v1/bundles/[0-9a-f]{32}\.tar\.gz", key))


class Store:
    def __init__(self, client, bucket, clock=utc_now):
        self.client, self.bucket, self.clock = client, bucket, clock
        self.calls = self.wire_calls = 0
        self.manifest = self.etag = self.lease = None
        # Count physical sends too, including any SDK redirect. SDK retries are
        # disabled, but this keeps the cap independent of transport behaviour.
        if hasattr(client, "meta"):
            client.meta.events.register("before-send.s3", self.before_send)

    def before_send(self, **_):
        if self.wire_calls >= MAX_REQUESTS:
            raise ValueError("R2 request budget exhausted.")
        self.wire_calls += 1

    @classmethod
    def from_environment(cls):
        names = [
            "R2_ENDPOINT_URL",
            "R2_BUCKET",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
        ]
        if any(not os.environ.get(name) for name in names):
            raise ValueError(
                "Set R2_ENDPOINT_URL, R2_BUCKET and the two R2 credential variables."
            )
        endpoint = os.environ["R2_ENDPOINT_URL"].rstrip("/")
        if not re.fullmatch(
            r"https://[0-9a-f]{32}(?:\.(?:eu|fedramp))?\.r2\.cloudflarestorage\.com",
            endpoint,
        ):
            raise ValueError("Use the HTTPS S3 endpoint shown in the R2 dashboard.")
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="auto",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=Config(
                retries={"total_max_attempts": 1},
                connect_timeout=10,
                read_timeout=60,
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        return cls(client, os.environ["R2_BUCKET"])

    def request(self, method, **kwargs):
        if self.calls >= MAX_REQUESTS:
            raise ValueError("R2 request budget exhausted.")
        self.calls += 1
        try:
            return getattr(self.client, method)(Bucket=self.bucket, **kwargs)
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code in {"NoSuchKey", "404"} and method == "get_object":
                raise FileNotFoundError("R2 object is missing.") from None
            if code in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
                "412",
                "409",
            }:
                raise ValueError(
                    "R2 state changed concurrently; no overwrite was made. Retry later."
                ) from None
            raise ValueError(
                f"R2 {method} failed; check access and bucket settings."
            ) from None
        except BotoCoreError:
            # SDK messages can contain endpoints/headers. Do not echo secrets.
            raise ValueError(
                f"R2 {method} could not complete; retry a new run later."
            ) from None

    def read_manifest(self, allow_empty=False):
        try:
            response = self.request("get_object", Key=MANIFEST)
        except FileNotFoundError:
            if not allow_empty:
                raise ValueError(
                    "R2 is not seeded. Run the one-off seed command first."
                ) from None
            return {"version": 1, "current": None, "previous": None}, None
        with response["Body"] as body:
            raw = body.read(65_537)
        if len(raw) > 65_536:
            raise ValueError("Unexpected oversized R2 manifest.")
        data = json.loads(raw)
        if data.get("version") != 1:
            raise ValueError("Unsupported R2 state format.")
        for field in ["current", "previous"]:
            item = data.get(field)
            if item and (
                not bundle_key(item["key"])
                or not 0 < item["size"] <= state_bundle.MAX_PACKED
                or not re.fullmatch("[0-9a-f]{64}", item["sha256"])
            ):
                raise ValueError("Unexpected R2 bundle descriptor.")
        return data, response["ETag"]

    def write_manifest(self, manifest):
        condition = {"IfMatch": self.etag} if self.etag else {"IfNoneMatch": "*"}
        response = self.request(
            "put_object",
            Key=MANIFEST,
            Body=json.dumps(manifest).encode(),
            ContentType="application/json",
            **condition,
        )
        self.etag, self.manifest = response["ETag"], manifest

    def reserve(self, seed=False):
        self.manifest, self.etag = self.read_manifest(allow_empty=seed)
        if seed and self.manifest.get("current"):
            raise ValueError("R2 already has state; seeding cannot overwrite it.")
        if not seed and not self.manifest.get("current"):
            raise ValueError("R2 has no completed seed yet.")
        now = self.clock()
        lease = self.manifest.get("lease")
        if lease and datetime.fromisoformat(lease["until"]) > now:
            raise ValueError(
                "Another run holds the R2 writer lease; retry after it expires."
            )
        day = now.date().isoformat()
        count = self.manifest.get("runs", 0) if self.manifest.get("day") == day else 0
        if count >= MAX_RUNS:
            raise ValueError("The 32-run daily R2 processing budget is exhausted.")
        identifier = uuid4().hex
        manifest = {
            **self.manifest,
            "day": day,
            "runs": count + 1,
            "lease": {
                "id": identifier,
                "until": (now + timedelta(minutes=20)).isoformat(),
            },
        }
        self.write_manifest(manifest)
        self.lease = identifier

    def assert_lease(self):
        lease = self.manifest.get("lease") if self.manifest else None
        if (
            not lease
            or lease["id"] != self.lease
            or datetime.fromisoformat(lease["until"]) <= self.clock()
        ):
            raise ValueError("R2 writer lease expired; abandon this run and retry.")

    def restore(self, destination, previous=False):
        manifest = self.manifest or self.read_manifest()[0]
        item = manifest.get("previous" if previous else "current")
        if not item:
            raise ValueError("There is no requested saved state to restore.")
        destination = Path(destination)
        if destination.exists():
            raise ValueError("Restore needs a new directory.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=destination.parent, prefix="r2-download-"
        ) as temporary:
            archive = Path(temporary) / "state.tar.gz"
            response = self.request("get_object", Key=item["key"])
            with response["Body"] as body, archive.open("xb") as output:
                if response["ContentLength"] != item["size"]:
                    raise ValueError("R2 bundle size does not match its manifest.")
                size = 0
                while chunk := body.read(1024 * 1024):
                    size += len(chunk)
                    if size > item["size"]:
                        raise ValueError("R2 download exceeds expected size.")
                    output.write(chunk)
            state_bundle.unpack(
                archive, destination, {k: item[k] for k in ["size", "sha256"]}
            )

    def publish(self, bundle):
        self.assert_lease()
        description = state_bundle.describe(bundle)
        if description["size"] > state_bundle.MAX_PACKED:
            raise ValueError("State bundle exceeds its upload budget.")
        # A single page is deliberate. Unexpected inventory stops work rather
        # than quietly paging through an unbounded bucket.
        inventory = self.request("list_objects_v2", MaxKeys=100)
        if inventory.get("IsTruncated"):
            raise ValueError("Unexpected bucket inventory; inspect it before writing.")
        objects = inventory.get("Contents", [])
        if (
            sum(item["Size"] for item in objects) + description["size"] + 65_536
            > MAX_STORAGE
        ):
            raise ValueError("R2 upload would exceed the 2 GB storage budget.")
        self.assert_lease()
        key = PREFIX + "bundles/" + uuid4().hex + ".tar.gz"
        with Path(bundle).open("rb") as body:
            self.request(
                "put_object",
                Key=key,
                Body=body,
                ContentType="application/gzip",
                StorageClass="STANDARD",
                IfNoneMatch="*",
            )
        self.assert_lease()
        # This conditional pointer update is the commit. If it fails, the
        # uploaded orphan is harmless and cleaned up after a future success.
        previous = self.manifest.get("current")
        current = {"key": key, **description}
        self.write_manifest({**self.manifest, "current": current, "previous": previous})
        keep = {key} | ({previous["key"]} if previous else set())
        for item in objects:
            if bundle_key(item["Key"]) and item["Key"] not in keep:
                self.assert_lease()
                self.request("delete_object", Key=item["Key"])

    def release(self):
        if self.lease:
            self.assert_lease()
            self.write_manifest({**self.manifest, "lease": None})
            self.lease = None
