"""Validated, canonical local snapshots and storage-independent inventory metadata."""

import re
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Literal, Self

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, TABLE_SCHEMAS
from enterprise_analytics_agent.errors import DataValidationError

SNAPSHOT_SCHEMAS = {**TABLE_SCHEMAS, **OPTIONAL_TABLE_SCHEMAS}
_VERSION = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z")


def validate_dataset_version(value: str) -> str:
    """Versions are immutable path components, not arbitrary object-store prefixes."""
    if len(value) > 64 or _VERSION.fullmatch(value) is None:
        raise ValueError("Dataset version must be a lowercase slug of at most 64 characters")
    return value


def manifest_key(dataset_version: str) -> str:
    return f"manifests/{validate_dataset_version(dataset_version)}.json"


def table_key(dataset_version: str, table: str) -> str:
    validate_dataset_version(dataset_version)
    if table not in SNAPSHOT_SCHEMAS:
        raise ValueError("Unknown snapshot table")
    return f"snapshots/{dataset_version}/{table}/part-00000.parquet"


class SnapshotColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: Literal["VARCHAR", "BIGINT", "INTEGER", "DATE"]


class TableManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=0, strict=True)
    size_bytes: int = Field(gt=0, strict=True)
    columns: tuple[SnapshotColumn, ...]


class SnapshotManifest(BaseModel):
    """A ready inventory; it is published only after all objects are verified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: Literal["v1"] = "v1"
    dataset_version: str
    seed: int | None = Field(default=None, strict=True)
    state: Literal["ready"] = "ready"
    tables: dict[str, TableManifest]

    @field_validator("dataset_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        return validate_dataset_version(value)

    @model_validator(mode="after")
    def valid_inventory(self) -> Self:
        if not TABLE_SCHEMAS.keys() <= self.tables.keys():
            raise ValueError("Snapshot inventory must contain all six legacy tables")
        if self.tables.keys() - SNAPSHOT_SCHEMAS.keys():
            raise ValueError("Snapshot inventory contains an unknown table")
        for table, inventory in self.tables.items():
            if inventory.key != table_key(self.dataset_version, table):
                raise ValueError(f"Snapshot object key is inconsistent for {table}")
            columns = tuple((column.name, column.type) for column in inventory.columns)
            if columns != SNAPSHOT_SCHEMAS[table]:
                raise ValueError(f"Snapshot column inventory is inconsistent for {table}")
        return self


@dataclass
class PreparedSnapshot:
    """Owned temporary copies; close after publication or inspection."""

    manifest: SnapshotManifest
    directory: Path
    _temporary_directory: TemporaryDirectory[str]

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._temporary_directory.cleanup()


def prepare_snapshot(
    source_dir: Path, dataset_version: str, *, seed: int | None = None
) -> PreparedSnapshot:
    """Freeze, validate, deduplicate, sort, and checksum a snapshot without AWS calls.

    The frozen copies are validated by the same source-validation boundary as DuckDB.
    Identical replays collapse; conflicting tenant-scoped keys are rejected. Optional
    returns stay absent when absent, while a present empty file remains in inventory.
    """
    validate_dataset_version(dataset_version)
    temporary = TemporaryDirectory(prefix="analytics-snapshot-")
    root = Path(temporary.name)
    frozen = root / "frozen"
    canonical = root / "canonical"
    frozen.mkdir()
    canonical.mkdir()
    try:
        for table in SNAPSHOT_SCHEMAS:
            source = source_dir / f"{table}.parquet"
            if source.is_file():
                shutil.copyfile(source, frozen / source.name)
        with DuckDBSemanticAdapter(frozen):
            pass
        inventories: dict[str, TableManifest] = {}
        with duckdb.connect(":memory:", config={"threads": 1}) as connection:
            for table, schema in SNAPSHOT_SCHEMAS.items():
                source = frozen / f"{table}.parquet"
                if not source.is_file():
                    continue
                columns = ", ".join(f'"{name}"' for name, _ in schema)
                relation = connection.read_parquet(str(source)).distinct().order(columns)
                target = canonical / source.name
                relation.write_parquet(str(target), compression="zstd")
                content = target.read_bytes()
                counted = relation.count("*").fetchone()
                if counted is None or type(counted[0]) is not int:
                    raise DataValidationError("Could not count canonical snapshot records")
                inventories[table] = TableManifest(
                    key=table_key(dataset_version, table),
                    sha256=sha256(content).hexdigest(),
                    row_count=counted[0],
                    size_bytes=len(content),
                    columns=tuple(SnapshotColumn(name=name, type=kind) for name, kind in schema),
                )
        manifest = SnapshotManifest(dataset_version=dataset_version, seed=seed, tables=inventories)
        return PreparedSnapshot(manifest, canonical, temporary)
    except (OSError, duckdb.Error) as exc:
        temporary.cleanup()
        raise DataValidationError("Could not prepare the local snapshot") from exc
    except BaseException:
        temporary.cleanup()
        raise
