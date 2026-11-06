"""Explicit AWS publication of validated immutable development snapshots.

No SDK session or network request is created on import or during local preparation.
Source uploads and the final ready manifest use conditional writes. A failed upload
leaves an unpublished prefix for operator inspection; this module never deletes data.
"""

import base64
import json
import re
from hashlib import sha256
from typing import Any, Protocol

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from enterprise_analytics_agent.adapters.aws_schema import glue_table_name
from enterprise_analytics_agent.errors import DataValidationError
from enterprise_analytics_agent.snapshots import (
    PreparedSnapshot,
    SnapshotManifest,
    manifest_key,
)

_GLUE_TYPES = {"VARCHAR": "string", "BIGINT": "bigint", "INTEGER": "int", "DATE": "date"}
_MAX_MANIFEST_BYTES = 1_000_000


class PublicationError(DataValidationError):
    """Publication could not be confirmed; inspect the version before retrying."""


class S3Client(Protocol):
    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...


class GlueClient(Protocol):
    def get_table(self, **kwargs: Any) -> dict[str, Any]: ...


class PublicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    database: str = Field(pattern=r"^[a-z][a-z0-9_]{0,254}$")
    expected_account_id: str = Field(pattern=r"^[0-9]{12}$")
    table_prefix: str = "ea"

    @field_validator("table_prefix")
    @classmethod
    def valid_prefix(cls, value: str) -> str:
        # Use the shared identifier validation rather than accepting arbitrary SQL names.
        glue_table_name("validation-v1", "orders", prefix=value)
        return value


def _checksum(content: bytes) -> str:
    return base64.b64encode(sha256(content).digest()).decode("ascii")


def _verify_glue(
    manifest: SnapshotManifest, *, glue: GlueClient, config: PublicationConfig
) -> None:
    """The loader can read predeclared schemas, but cannot mutate the catalog."""
    for table, inventory in manifest.tables.items():
        response = glue.get_table(
            CatalogId=config.expected_account_id,
            DatabaseName=config.database,
            Name=glue_table_name(manifest.dataset_version, table, prefix=config.table_prefix),
        )
        definition = response.get("Table", {})
        descriptor = definition.get("StorageDescriptor", {})
        expected_columns = [
            {"Name": column.name, "Type": _GLUE_TYPES[column.type]} for column in inventory.columns
        ]
        columns = [
            {"Name": column.get("Name"), "Type": column.get("Type")}
            for column in descriptor.get("Columns", [])
        ]
        location = f"s3://{config.bucket}/{inventory.key.rsplit('/', 1)[0]}/"
        if (
            definition.get("TableType") != "EXTERNAL_TABLE"
            or columns != expected_columns
            or descriptor.get("Location") != location
            or definition.get("PartitionKeys", [])
            or descriptor.get("AdditionalLocations", [])
            or descriptor.get("InputFormat")
            != "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
            or descriptor.get("OutputFormat")
            != "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
            or descriptor.get("SerdeInfo", {}).get("SerializationLibrary")
            != "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
        ):
            raise PublicationError(
                f"Deployed Glue schema/location does not match snapshot: {table}"
            )


def publish_snapshot(
    prepared: PreparedSnapshot,
    *,
    s3: S3Client,
    glue: GlueClient,
    config: PublicationConfig,
) -> SnapshotManifest:
    """Publish once; all files and catalog schemas must pass before ready is visible.

    A snapshot version with either ready metadata or partial source files is rejected.
    All writers create the same first governed object with IfNoneMatch='*', so
    concurrent publications cannot combine files into a single ready version.
    """
    manifest = SnapshotManifest.model_validate_json(prepared.manifest.model_dump_json())
    try:
        # Reject mismatched files before performing any AWS write. Read all bytes now;
        # later mutation of the source or temporary directory cannot change the upload.
        contents: dict[str, bytes] = {}
        for table, inventory in manifest.tables.items():
            content = (prepared.directory / f"{table}.parquet").read_bytes()
            if (
                len(content) != inventory.size_bytes
                or sha256(content).hexdigest() != inventory.sha256
            ):
                raise PublicationError(f"Prepared snapshot file changed: {table}")
            contents[table] = content
        # Prefix-scoped ListBucket permission is enough even for a new version.
        # HEAD on a missing key may instead require broader ListBucket to return 404.
        ready_key = manifest_key(manifest.dataset_version)
        existing_ready = s3.list_objects_v2(
            Bucket=config.bucket,
            Prefix=ready_key,
            MaxKeys=1,
            ExpectedBucketOwner=config.expected_account_id,
        )
        if any(item.get("Key") == ready_key for item in existing_ready.get("Contents", [])):
            raise PublicationError(
                "Dataset version already has a ready manifest; choose a new version"
            )
        existing = s3.list_objects_v2(
            Bucket=config.bucket,
            Prefix=f"snapshots/{manifest.dataset_version}/",
            MaxKeys=1,
            ExpectedBucketOwner=config.expected_account_id,
        )
        if existing.get("Contents"):
            raise PublicationError(
                "Dataset version already has source objects; choose a new version"
            )
        _verify_glue(manifest, glue=glue, config=config)
        # The order is fixed even if a caller reordered the inventory dictionary.
        for table in sorted(manifest.tables):
            inventory = manifest.tables[table]
            content = contents[table]
            checksum = _checksum(content)
            s3.put_object(
                Bucket=config.bucket,
                Key=inventory.key,
                Body=content,
                ContentType="application/vnd.apache.parquet",
                ChecksumSHA256=checksum,
                Metadata={"sha256": inventory.sha256},
                IfNoneMatch="*",
                ExpectedBucketOwner=config.expected_account_id,
            )
            uploaded = s3.head_object(
                Bucket=config.bucket,
                Key=inventory.key,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=config.expected_account_id,
            )
            if (
                uploaded.get("ContentLength") != inventory.size_bytes
                or uploaded.get("ChecksumSHA256") != checksum
            ):
                raise PublicationError(
                    f"Uploaded snapshot checksum/length verification failed: {table}"
                )
        body = json.dumps(
            manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        s3.put_object(
            Bucket=config.bucket,
            Key=manifest_key(manifest.dataset_version),
            Body=body,
            ContentType="application/json",
            ChecksumSHA256=_checksum(body),
            IfNoneMatch="*",
            ExpectedBucketOwner=config.expected_account_id,
        )
        return manifest
    except (OSError, BotoCoreError, ClientError) as exc:
        raise PublicationError(
            "Snapshot publication failed; ready manifest was not confirmed"
        ) from exc


def get_ready_manifest(
    *,
    s3: S3Client,
    bucket: str,
    dataset_version: str,
    expected_account_id: str | None = None,
) -> SnapshotManifest:
    """Read only validated ready metadata; missing data is never treated as empty."""
    arguments: dict[str, Any] = {"Bucket": bucket, "Key": manifest_key(dataset_version)}
    if expected_account_id is not None:
        if re.fullmatch(r"[0-9]{12}", expected_account_id) is None:
            raise ValueError("Expected account ID must contain twelve digits")
        arguments["ExpectedBucketOwner"] = expected_account_id
    try:
        response = s3.get_object(**arguments)
        body = response["Body"]
        try:
            content = body.read(_MAX_MANIFEST_BYTES + 1)
        finally:
            body.close()
        if not isinstance(content, bytes) or len(content) > _MAX_MANIFEST_BYTES:
            raise PublicationError("Ready manifest is not a bounded JSON document")
        manifest = SnapshotManifest.model_validate_json(content)
        if manifest.dataset_version != dataset_version:
            raise PublicationError("Ready manifest does not identify the requested dataset version")
        return manifest
    except (BotoCoreError, ClientError, ValidationError, KeyError) as exc:
        raise PublicationError("Could not read a valid ready snapshot manifest") from exc
