"""Offline snapshot/publication invariants with authored records and in-memory AWS fakes."""

import base64
import json
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import duckdb
import pytest
from botocore.exceptions import ClientError
from conftest import write_snapshot
from pydantic import ValidationError

from enterprise_analytics_agent.adapters.aws_schema import glue_table_name
from enterprise_analytics_agent.adapters.s3_publication import (
    PublicationConfig,
    PublicationError,
    get_ready_manifest,
    publish_snapshot,
)
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, DataRow
from enterprise_analytics_agent.errors import DataValidationError
from enterprise_analytics_agent.snapshots import (
    PreparedSnapshot,
    SnapshotManifest,
    manifest_key,
    prepare_snapshot,
)


def error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "fixture failure"}}, "FixtureOperation")


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_put: int | None = None
        self.corrupt_checksum = False

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put", kwargs))
        if self.fail_put == sum(operation == "put" for operation, _ in self.calls):
            raise error("InternalError")
        key = str(kwargs["Key"])
        assert kwargs["IfNoneMatch"] == "*"
        if key in self.objects:
            raise error("PreconditionFailed")
        content: bytes = kwargs["Body"]
        assert kwargs["ChecksumSHA256"] == base64.b64encode(sha256(content).digest()).decode()
        self.objects[key] = content
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head", kwargs))
        key = str(kwargs["Key"])
        if key not in self.objects:
            raise error("404")
        content = self.objects[key]
        return {
            "ContentLength": len(content),
            "ChecksumSHA256": "bad"
            if self.corrupt_checksum
            else base64.b64encode(sha256(content).digest()).decode(),
        }

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list", kwargs))
        return {
            "Contents": [{"Key": key} for key in self.objects if key.startswith(kwargs["Prefix"])][
                : kwargs["MaxKeys"]
            ]
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get", kwargs))
        if kwargs["Key"] not in self.objects:
            raise error("NoSuchKey")
        return {"Body": BytesIO(self.objects[kwargs["Key"]])}


class MemoryGlue:
    def __init__(self, prepared: PreparedSnapshot, config: PublicationConfig) -> None:
        self.calls: list[dict[str, Any]] = []
        types = {"VARCHAR": "string", "BIGINT": "bigint", "INTEGER": "int", "DATE": "date"}
        self.tables: dict[str, dict[str, Any]] = {
            glue_table_name(prepared.manifest.dataset_version, name): {
                "Table": {
                    "TableType": "EXTERNAL_TABLE",
                    "PartitionKeys": [],
                    "StorageDescriptor": {
                        "Location": f"s3://{config.bucket}/{inventory.key.rsplit('/', 1)[0]}/",
                        "Columns": [
                            {"Name": column.name, "Type": types[column.type]}
                            for column in inventory.columns
                        ],
                        "InputFormat": (
                            "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
                        ),
                        "OutputFormat": (
                            "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
                        ),
                        "SerdeInfo": {
                            "SerializationLibrary": (
                                "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                            )
                        },
                    },
                }
            }
            for name, inventory in prepared.manifest.tables.items()
        }

    def get_table(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if kwargs["Name"] not in self.tables:
            raise error("EntityNotFoundException")
        return self.tables[kwargs["Name"]]


@pytest.fixture
def publication_config() -> PublicationConfig:
    return PublicationConfig(
        bucket="analytics-data-test", database="analytics_test", expected_account_id="123456789012"
    )


def add_returns(directory: Path, rows: list[DataRow]) -> None:
    with duckdb.connect(":memory:") as connection:
        schema = OPTIONAL_TABLE_SCHEMAS["returns"]
        connection.execute(
            "CREATE TABLE returns (" + ", ".join(f"{n} {t}" for n, t in schema) + ")"
        )
        if rows:
            connection.executemany("INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        connection.table("returns").write_parquet(str(directory / "returns.parquet"))


def test_canonical_preparation_deduplicates_and_is_reproducible(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]]
) -> None:
    # Exact duplicate financial/physical events are replays, not new business events.
    snapshot_rows["refunds"].append(snapshot_rows["refunds"][0])
    snapshot_rows["orders"].append(snapshot_rows["orders"][0])
    first = write_snapshot(tmp_path / "first", snapshot_rows)
    return_event: DataRow = (
        "t1",
        "return1",
        "i1",
        1,
        date(2025, 2, 15),
        date(2025, 2, 16),
        "received",
    )
    add_returns(first, [return_event, return_event])
    second = write_snapshot(
        tmp_path / "second", {table: list(reversed(rows)) for table, rows in snapshot_rows.items()}
    )
    add_returns(second, [return_event])
    with (
        prepare_snapshot(first, "parity-v1", seed=None) as a,
        prepare_snapshot(second, "parity-v1", seed=None) as b,
    ):
        assert a.manifest == b.manifest
        assert a.manifest.tables["orders"].row_count == 9
        assert a.manifest.tables["refunds"].row_count == 7
        assert a.manifest.tables["returns"].row_count == 1
        assert a.manifest.seed is None
        for table, inventory in a.manifest.tables.items():
            content = (a.directory / f"{table}.parquet").read_bytes()
            assert len(content) == inventory.size_bytes
            assert sha256(content).hexdigest() == inventory.sha256
            assert content == (b.directory / f"{table}.parquet").read_bytes()
        directory = a.directory
    assert not directory.exists()


def test_preparation_freezes_original_files(snapshot_dir: Path) -> None:
    with prepare_snapshot(snapshot_dir, "retail-v1", seed=20260101) as prepared:
        content = (prepared.directory / "orders.parquet").read_bytes()
        (snapshot_dir / "orders.parquet").write_bytes(b"changed outside prepared snapshot")
        assert (prepared.directory / "orders.parquet").read_bytes() == content
        assert prepared.manifest.seed == 20260101


def test_missing_and_empty_returns_are_distinct(snapshot_dir: Path) -> None:
    with prepare_snapshot(snapshot_dir, "parity-legacy-v1") as legacy:
        assert "returns" not in legacy.manifest.tables
    add_returns(snapshot_dir, [])
    with prepare_snapshot(snapshot_dir, "parity-no-returns-v1") as present:
        assert present.manifest.tables["returns"].row_count == 0
        assert present.manifest.tables["returns"].size_bytes > 0


@pytest.mark.parametrize("version", ["../bad", "a/b", "a%2fb", "A-v1", "", "a..b", "a" * 65])
def test_version_paths_are_validated(version: str, snapshot_dir: Path) -> None:
    with pytest.raises(ValueError, match="Dataset version"):
        prepare_snapshot(snapshot_dir, version)


def test_governed_table_names() -> None:
    assert glue_table_name("parity-v1", "orders") == (
        "ea_" + sha256(b"parity-v1").hexdigest()[:16] + "_orders"
    )
    assert glue_table_name("parity-v1", "orders") != glue_table_name("retail-v1", "orders")
    with pytest.raises(ValueError):
        glue_table_name("parity-v1", "orders; DROP TABLE x")
    with pytest.raises(ValueError):
        glue_table_name("parity-v1", "orders", prefix="ea.x")


@pytest.mark.parametrize(
    "invalid", ["conflicting", "relationship", "required", "missing", "schema"]
)
def test_invalid_sources_cannot_be_prepared(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], invalid: str
) -> None:
    if invalid == "conflicting":
        snapshot_rows["refunds"].append((*snapshot_rows["refunds"][0][:6], 401, "USD"))
    elif invalid == "relationship":
        snapshot_rows["order_items"][0] = ("unknown-tenant", "i1", "o1", "p1", 2, 1000, 300)
    elif invalid == "required":
        snapshot_rows["order_items"][0] = ("t1", "i1", "o1", "p1", None, 1000, 300)
    directory = write_snapshot(tmp_path / "invalid", snapshot_rows)
    if invalid == "missing":
        (directory / "payments.parquet").unlink()
    elif invalid == "schema":
        with duckdb.connect(":memory:") as connection:
            connection.sql("SELECT 'bad' AS tenant_id").write_parquet(
                str(directory / "payments.parquet")
            )
    with pytest.raises(DataValidationError):
        prepare_snapshot(directory, "parity-v1")


def test_ready_manifest_is_last_and_round_trips(
    snapshot_dir: Path, publication_config: PublicationConfig
) -> None:
    s3 = MemoryS3()
    with prepare_snapshot(snapshot_dir, "parity-legacy-v1") as prepared:
        glue = MemoryGlue(prepared, publication_config)
        manifest = publish_snapshot(prepared, s3=s3, glue=glue, config=publication_config)
        puts = [arguments for operation, arguments in s3.calls if operation == "put"]
        assert len(puts) == 7
        assert puts[-1]["Key"] == "manifests/parity-legacy-v1.json"
        assert all(call["ExpectedBucketOwner"] == "123456789012" for _, call in s3.calls)
        assert len(glue.calls) == 6
        assert (
            get_ready_manifest(
                s3=s3,
                bucket=publication_config.bucket,
                dataset_version="parity-legacy-v1",
                expected_account_id="123456789012",
            )
            == manifest
        )
        assert SnapshotManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_existing_version_is_never_overwritten(
    snapshot_dir: Path, publication_config: PublicationConfig
) -> None:
    s3 = MemoryS3()
    with prepare_snapshot(snapshot_dir, "parity-legacy-v1") as prepared:
        glue = MemoryGlue(prepared, publication_config)
        publish_snapshot(prepared, s3=s3, glue=glue, config=publication_config)
        original = dict(s3.objects)
        with pytest.raises(PublicationError, match="already has a ready manifest"):
            publish_snapshot(prepared, s3=s3, glue=glue, config=publication_config)
        assert s3.objects == original


@pytest.mark.parametrize("failure", ["upload", "checksum", "glue", "changed", "partial"])
def test_failures_never_publish_ready_manifest(
    snapshot_dir: Path, publication_config: PublicationConfig, failure: str
) -> None:
    s3 = MemoryS3()
    with prepare_snapshot(snapshot_dir, "parity-legacy-v1") as prepared:
        glue = MemoryGlue(prepared, publication_config)
        if failure == "upload":
            s3.fail_put = 2
        elif failure == "checksum":
            s3.corrupt_checksum = True
        elif failure == "glue":
            glue.tables.clear()
        elif failure == "changed":
            (prepared.directory / "orders.parquet").write_bytes(b"tampered")
        elif failure == "partial":
            s3.objects["snapshots/parity-legacy-v1/stray.parquet"] = b"orphan"
        with pytest.raises(PublicationError):
            publish_snapshot(prepared, s3=s3, glue=glue, config=publication_config)
        assert manifest_key("parity-legacy-v1") not in s3.objects
        if failure in {"glue", "changed", "partial"}:
            assert not any(operation == "put" for operation, _ in s3.calls)


@pytest.mark.parametrize(
    "mismatch", ["Location", "Columns", "InputFormat", "OutputFormat", "SerdeInfo"]
)
def test_deployed_catalog_must_match_source(
    snapshot_dir: Path, publication_config: PublicationConfig, mismatch: str
) -> None:
    s3 = MemoryS3()
    with prepare_snapshot(snapshot_dir, "parity-v1") as prepared:
        glue = MemoryGlue(prepared, publication_config)
        descriptor = next(iter(glue.tables.values()))["Table"]["StorageDescriptor"]
        descriptor[mismatch] = (
            []
            if mismatch == "Columns"
            else {"SerializationLibrary": "wrong"}
            if mismatch == "SerdeInfo"
            else "wrong"
        )
        with pytest.raises(PublicationError, match="schema/location"):
            publish_snapshot(prepared, s3=s3, glue=glue, config=publication_config)
        assert not s3.objects


def test_malformed_inventory_is_rejected(snapshot_dir: Path) -> None:
    with prepare_snapshot(snapshot_dir, "parity-v1") as prepared:
        payload = prepared.manifest.model_dump(mode="json")
        payload["tables"]["orders"]["key"] = "snapshots/another/orders/part-00000.parquet"
        with pytest.raises(ValidationError, match="object key"):
            SnapshotManifest.model_validate(payload)
        payload = prepared.manifest.model_dump(mode="json")
        del payload["tables"]["orders"]
        with pytest.raises(ValidationError, match="six legacy tables"):
            SnapshotManifest.model_validate(payload)


@pytest.mark.parametrize("failure", ["missing", "invalid", "oversized", "wrong-version"])
def test_get_manifest_failures_are_clear(snapshot_dir: Path, failure: str) -> None:
    s3 = MemoryS3()
    key = "manifests/parity-v1.json"
    if failure == "invalid":
        s3.objects[key] = b"{}"
    elif failure == "oversized":
        s3.objects[key] = b"x" * 1_000_001
    elif failure == "wrong-version":
        with prepare_snapshot(snapshot_dir, "parity-legacy-v1") as prepared:
            s3.objects[key] = json.dumps(prepared.manifest.model_dump(mode="json")).encode()
    with pytest.raises(PublicationError):
        get_ready_manifest(s3=s3, bucket="analytics-data-test", dataset_version="parity-v1")


def test_conditional_create_race_cannot_publish_mixed_snapshot(
    snapshot_dir: Path, publication_config: PublicationConfig
) -> None:
    class RacingS3(MemoryS3):
        def put_object(self, **kwargs: Any) -> dict[str, Any]:
            # Another publisher wins between LIST and the first conditional PUT.
            self.objects[str(kwargs["Key"])] = b"another publisher"
            return super().put_object(**kwargs)

    s3 = RacingS3()
    with prepare_snapshot(snapshot_dir, "parity-v1") as prepared:
        with pytest.raises(PublicationError, match="not confirmed"):
            publish_snapshot(
                prepared,
                s3=s3,
                glue=MemoryGlue(prepared, publication_config),
                config=publication_config,
            )
    assert len(s3.objects) == 1
    assert "manifests/parity-v1.json" not in s3.objects


def test_permission_denial_is_not_treated_as_missing_manifest(
    snapshot_dir: Path, publication_config: PublicationConfig
) -> None:
    class DeniedS3(MemoryS3):
        def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
            raise error("AccessDenied")

    s3 = DeniedS3()
    with prepare_snapshot(snapshot_dir, "parity-v1") as prepared:
        with pytest.raises(PublicationError, match="not confirmed"):
            publish_snapshot(
                prepared,
                s3=s3,
                glue=MemoryGlue(prepared, publication_config),
                config=publication_config,
            )
    assert not s3.objects


@pytest.mark.parametrize("invalid", ["status", "quantity", "received-date", "foreign-tenant"])
def test_invalid_return_sources_are_rejected(snapshot_dir: Path, invalid: str) -> None:
    row: DataRow = ("t1", "return1", "i1", 1, date(2025, 2, 15), date(2025, 2, 16), "received")
    if invalid == "status":
        row = (*row[:6], "unknown")
    elif invalid == "quantity":
        row = (*row[:3], 3, *row[4:])
    elif invalid == "received-date":
        row = (*row[:5], None, row[6])
    elif invalid == "foreign-tenant":
        # The item id exists, but only t1 owns i2; a cross-tenant reference is invalid.
        row = ("t2", "return1", "i2", *row[3:])
    add_returns(snapshot_dir, [row])
    with pytest.raises(DataValidationError):
        prepare_snapshot(snapshot_dir, "parity-v1")
