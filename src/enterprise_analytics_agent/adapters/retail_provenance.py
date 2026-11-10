"""Read-only, version-pinned canonical input acquisition; never generates source rows."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import boto3
import duckdb
from botocore.config import Config

PROFILE = "analytics-dev"
ACCOUNT = "453711491609"
REGION = "us-west-2"
BUCKET = "enterprise-analytics-dev-453711491609-us-west-2-data"
MANIFEST_KEY = "manifests/retail-v1.json"
READ_CONFIG = Config(connect_timeout=5, read_timeout=20, retries={"total_max_attempts": 2})

# Reviewed storage contract, kept independent from metric adapters/generator functions.
SCHEMAS: dict[str, tuple[tuple[str, str], ...]] = {
    "customers": (
        ("tenant_id", "VARCHAR"),
        ("customer_id", "VARCHAR"),
        ("name", "VARCHAR"),
        ("region", "VARCHAR"),
    ),
    "products": (
        ("tenant_id", "VARCHAR"),
        ("product_id", "VARCHAR"),
        ("name", "VARCHAR"),
        ("category", "VARCHAR"),
        ("unit_price_cents", "BIGINT"),
    ),
    "orders": (
        ("tenant_id", "VARCHAR"),
        ("order_id", "VARCHAR"),
        ("customer_id", "VARCHAR"),
        ("ordered_at", "DATE"),
        ("status", "VARCHAR"),
        ("currency", "VARCHAR"),
        ("region", "VARCHAR"),
        ("channel", "VARCHAR"),
        ("tax_cents", "BIGINT"),
        ("shipping_cents", "BIGINT"),
    ),
    "order_items": (
        ("tenant_id", "VARCHAR"),
        ("order_item_id", "VARCHAR"),
        ("order_id", "VARCHAR"),
        ("product_id", "VARCHAR"),
        ("quantity", "INTEGER"),
        ("unit_price_cents", "BIGINT"),
        ("discount_cents", "BIGINT"),
    ),
    "payments": (
        ("tenant_id", "VARCHAR"),
        ("payment_id", "VARCHAR"),
        ("order_id", "VARCHAR"),
        ("paid_at", "DATE"),
        ("status", "VARCHAR"),
        ("amount_cents", "BIGINT"),
        ("currency", "VARCHAR"),
    ),
    "refunds": (
        ("tenant_id", "VARCHAR"),
        ("refund_id", "VARCHAR"),
        ("order_item_id", "VARCHAR"),
        ("refunded_at", "DATE"),
        ("approved_at", "DATE"),
        ("status", "VARCHAR"),
        ("amount_cents", "BIGINT"),
        ("currency", "VARCHAR"),
    ),
    "returns": (
        ("tenant_id", "VARCHAR"),
        ("return_id", "VARCHAR"),
        ("order_item_id", "VARCHAR"),
        ("quantity", "INTEGER"),
        ("returned_at", "DATE"),
        ("received_at", "DATE"),
        ("status", "VARCHAR"),
    ),
}


class S3Reader(Protocol):
    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...


class IdentityReader(Protocol):
    def get_caller_identity(self) -> dict[str, Any]: ...


def _save_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Refusing to overwrite different canonical evidence: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)


def _read_object(s3: S3Reader, key: str, maximum_bytes: int) -> tuple[bytes, dict[str, object]]:
    params: dict[str, object] = {"Bucket": BUCKET, "Key": key, "ExpectedBucketOwner": ACCOUNT}
    head = s3.head_object(**params)
    length = head.get("ContentLength")
    if type(length) is not int or not 0 < length <= maximum_bytes:
        raise ValueError(f"Invalid object size for {key}")
    version = head.get("VersionId")
    if isinstance(version, str) and version != "null":
        params["VersionId"] = version
    else:
        etag = head.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise ValueError(f"Unversioned object has no conditional read identifier: {key}")
        params["IfMatch"] = etag
    result = s3.get_object(**params)
    body = result["Body"]
    try:
        content = body.read(maximum_bytes + 1)
    finally:
        body.close()
    if not isinstance(content, bytes) or len(content) != length:
        raise ValueError(f"Downloaded length differs for {key}")
    if result.get("ETag") != head.get("ETag") or result.get("VersionId") != version:
        raise ValueError(f"Object identity changed during read: {key}")
    return content, {
        "bucket": BUCKET,
        "key": key,
        "version_id": version,
        "etag": head.get("ETag"),
        "last_modified": str(head.get("LastModified")),
        "size_bytes": length,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def validate_manifest(manifest: dict[str, Any]) -> None:
    if (
        manifest.get("manifest_version"),
        manifest.get("dataset_version"),
        manifest.get("state"),
        manifest.get("seed"),
    ) != ("v1", "retail-v1", "ready", 20260101):
        raise ValueError("Expected the published ready retail-v1 manifest and fixed seed")
    tables = manifest.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(SCHEMAS):
        raise ValueError("Retail evaluation requires all seven canonical source tables")
    for table, schema in SCHEMAS.items():
        item = tables[table]
        if item.get("key") != f"snapshots/retail-v1/{table}/part-00000.parquet":
            raise ValueError(f"Unexpected source object key for {table}")
        columns = tuple((column.get("name"), column.get("type")) for column in item["columns"])
        if columns != schema:
            raise ValueError(f"Manifest schema differs for {table}")
        if (
            type(item.get("row_count")) is not int
            or item["row_count"] < 0
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] <= 0
        ):
            raise ValueError(f"Invalid manifest counts for {table}")
        digest = item.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(f"Invalid manifest checksum for {table}")


def verify_local(directory: Path) -> dict[str, Any]:
    """Verify exact published bytes and physical schemas; performs no metric calculations."""
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest: dict[str, Any] = json.loads(manifest_bytes)
    validate_manifest(manifest)
    with duckdb.connect(":memory:") as connection:
        for table, schema in SCHEMAS.items():
            item = manifest["tables"][table]
            path = directory / f"{table}.parquet"
            content = path.read_bytes()
            if (
                len(content) != item["size_bytes"]
                or hashlib.sha256(content).hexdigest() != item["sha256"]
            ):
                raise ValueError(f"Canonical source checksum/size differs: {table}")
            relation = connection.read_parquet(str(path))
            actual_schema = tuple((column[0], str(column[1])) for column in relation.description)
            if actual_schema != schema:
                raise ValueError(f"Physical Parquet schema differs: {table}")
            rows = relation.fetchall()
            if len(rows) != item["row_count"]:
                raise ValueError(f"Canonical row inventory differs: {table}")
            nullable = {"approved_at", "received_at"}
            for row in rows:
                if any(
                    value is None and column not in nullable
                    for (column, _), value in zip(schema, row, strict=True)
                ):
                    raise ValueError(f"Required source field is null: {table}")
    return manifest


def download_canonical(directory: Path, *, s3: S3Reader, sts: IdentityReader) -> dict[str, object]:
    """Only STS identity, S3 HEAD and S3 GET; denied reads propagate without substitution."""
    identity = sts.get_caller_identity()
    if identity.get("Account") != ACCOUNT:
        raise ValueError("analytics-dev resolved to an unexpected AWS account")
    manifest_bytes, manifest_identity = _read_object(s3, MANIFEST_KEY, 1_000_000)
    manifest: dict[str, Any] = json.loads(manifest_bytes)
    validate_manifest(manifest)
    _save_immutable(directory / "manifest.json", manifest_bytes)
    objects: dict[str, object] = {}
    for table, item in manifest["tables"].items():
        content, metadata = _read_object(s3, item["key"], 100_000_000)
        if len(content) != item["size_bytes"] or metadata["sha256"] != item["sha256"]:
            raise ValueError(f"Published object does not match ready inventory: {table}")
        _save_immutable(directory / f"{table}.parquet", content)
        objects[table] = metadata
    verify_local(directory)
    record: dict[str, object] = {
        "provenance_version": "retail-input-v1",
        "verified": True,
        "verified_at": datetime.now(UTC).isoformat(),
        "profile": PROFILE,
        "account": ACCOUNT,
        "region": REGION,
        "caller_arn": identity.get("Arn"),
        "dataset_version": "retail-v1",
        "seed": 20260101,
        "manifest": manifest_identity,
        "objects": objects,
        "checks": [
            "version-or-etag-pinned GET",
            "sha256",
            "size",
            "physical schema",
            "row inventory",
            "required fields",
        ],
    }
    # Evidence is written only after every table passes; failed/partial reads are not ready.
    output = directory / "provenance.json"
    if output.exists():
        prior = json.loads(output.read_text())
        if prior.get("manifest") != record["manifest"] or prior.get("objects") != objects:
            raise ValueError("Canonical provenance differs from retained evidence")
        return cast(dict[str, object], prior)
    _save_immutable(output, (json.dumps(record, indent=2) + "\n").encode())
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or download exact canonical retail inputs")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Explicit read-only AWS retrieval")
    args = parser.parse_args()
    if args.download:
        session = boto3.Session(profile_name=PROFILE, region_name=REGION)
        record = download_canonical(
            args.directory,
            s3=cast(S3Reader, session.client("s3", config=READ_CONFIG)),
            sts=cast(IdentityReader, session.client("sts", config=READ_CONFIG)),
        )
        print(json.dumps(record, indent=2))
    else:
        verify_local(args.directory)
        print("Canonical local manifest, hashes, sizes, schemas and inventory verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
