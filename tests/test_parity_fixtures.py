"""Offline expected-value proof for the data that will later be queried on AWS."""

from pathlib import Path

import pytest
from aws_fixture_data import write_parity_snapshot
from aws_parity_cases import PARITY_CASES, ParityCase

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter


@pytest.fixture(scope="module")
def parity_directories(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("independent-parity")
    return {
        version: write_parity_snapshot(root / version, returns=mode)
        for version, mode in (
            ("parity-v1", "received"),
            ("parity-legacy-v1", "absent"),
            ("parity-no-returns-v1", "empty"),
        )
    }


@pytest.mark.parametrize("case", PARITY_CASES, ids=lambda case: case.name)
def test_authored_data_matches_independent_expected_answers(
    parity_directories: dict[str, Path], case: ParityCase
) -> None:
    with DuckDBSemanticAdapter(parity_directories[case.dataset_version]) as adapter:
        actual = adapter.query_metric(case.request(), context=case.context())
    assert tuple((row.dimensions, row.value) for row in actual.rows) == case.expected


def test_legacy_fixture_cannot_silently_reuse_a_seven_table_destination(tmp_path: Path) -> None:
    directory = write_parity_snapshot(tmp_path / "fixture", returns="received")
    before = (directory / "returns.parquet").read_bytes()
    with pytest.raises(ValueError, match="already has returns"):
        write_parity_snapshot(directory, returns="absent")
    assert (directory / "returns.parquet").read_bytes() == before
