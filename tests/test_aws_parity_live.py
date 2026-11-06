"""Live acceptance gate: default pytest skips this module before creating sessions."""

import json
from collections.abc import Callable, Iterator
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from aws_fixture_data import write_parity_snapshot
from aws_parity_cases import PARITY_CASES, ParityCase

from enterprise_analytics_agent.adapters.athena import AthenaConfig, AthenaSemanticAdapter
from enterprise_analytics_agent.adapters.athena_execution import AthenaClient
from enterprise_analytics_agent.adapters.aws_runtime import (
    ATHENA_SDK_CONFIG,
    SDK_CONFIG,
    load_runtime_config,
    session_for_role,
)
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.adapters.s3_publication import S3Client, get_ready_manifest
from enterprise_analytics_agent.contracts import QueryMetricRequest, TimeRange
from enterprise_analytics_agent.contracts_v2 import DiscoverDimensionsRequestV2
from enterprise_analytics_agent.errors import AuthorizationError, MissingMetricDataError

pytestmark = pytest.mark.aws_integration


@pytest.fixture(scope="session")
def cloud_adapter(pytestconfig: pytest.Config) -> Callable[[str], AthenaSemanticAdapter]:
    config = load_runtime_config(Path(str(pytestconfig.getoption("aws_config"))))
    session = session_for_role(config, "query")
    athena = session.client("athena", config=ATHENA_SDK_CONFIG)
    group = athena.get_work_group(WorkGroup=config.workgroup_name)["WorkGroup"]["Configuration"]
    assert group["EnforceWorkGroupConfiguration"] is True
    assert group["BytesScannedCutoffPerQuery"] == config.bytes_scanned_cutoff_per_query
    results = group["ResultConfiguration"]
    location = f"s3://{config.results_bucket}/queries/"
    assert results["OutputLocation"] == location
    assert results["ExpectedBucketOwner"] == config.account
    assert results["EncryptionConfiguration"]["EncryptionOption"] == "SSE_S3"
    assert group["EngineVersion"]["SelectedEngineVersion"] == "Athena engine version 3"
    s3 = cast(S3Client, session.client("s3", config=SDK_CONFIG))

    def create(version: str) -> AthenaSemanticAdapter:
        config.target(version)
        manifest = get_ready_manifest(
            s3=s3,
            bucket=config.source_bucket,
            dataset_version=version,
            expected_account_id=config.account,
        )
        return AthenaSemanticAdapter(
            AthenaConfig(
                profile=config.profile,
                region=config.region,
                database=config.database_name,
                workgroup=config.workgroup_name,
                output_location=location,
                expected_bucket_owner=config.account,
                table_prefix=config.table_prefix,
            ),
            manifest,
            client=cast(AthenaClient, athena),
        )

    return create


@pytest.fixture(scope="session")
def local_parity(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("live-parity-oracle")
    return {
        version: write_parity_snapshot(root / version, returns=mode)
        for version, mode in (
            ("parity-v1", "received"),
            ("parity-legacy-v1", "absent"),
            ("parity-no-returns-v1", "empty"),
        )
    }


@pytest.fixture
def evidence(request: pytest.FixtureRequest) -> Iterator[list[AthenaSemanticAdapter]]:
    adapters: list[AthenaSemanticAdapter] = []
    yield adapters
    output = Path("artifacts/aws-parity-diagnostics.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a") as stream:
        for adapter in adapters:
            for diagnostic in adapter.diagnostics:
                stream.write(json.dumps({"test": request.node.name, **asdict(diagnostic)}) + "\n")


@pytest.mark.parametrize("case", PARITY_CASES, ids=lambda case: case.name)
def test_athena_and_duckdb_each_match_literal_expectations(
    cloud_adapter: Callable[[str], AthenaSemanticAdapter],
    local_parity: dict[str, Path],
    evidence: list[AthenaSemanticAdapter],
    case: ParityCase,
) -> None:
    remote = cloud_adapter(case.dataset_version)
    evidence.append(remote)
    with DuckDBSemanticAdapter(local_parity[case.dataset_version]) as local:
        local_result = local.query_metric(case.request(), context=case.context())
    remote_result = remote.query_metric(case.request(), context=case.context())
    # Neither adapter's answer is used as the other's expected answer.
    assert tuple((row.dimensions, row.value) for row in local_result.rows) == case.expected
    assert tuple((row.dimensions, row.value) for row in remote_result.rows) == case.expected


def test_missing_returns_is_an_error_in_both_adapters(
    cloud_adapter: Callable[[str], AthenaSemanticAdapter], local_parity: dict[str, Path]
) -> None:
    case = ParityCase("missing", "return_rate", (), dataset_version="parity-legacy-v1")
    remote = cloud_adapter(case.dataset_version)
    with DuckDBSemanticAdapter(local_parity[case.dataset_version]) as local:
        for adapter in (local, remote):
            with pytest.raises(MissingMetricDataError):
                adapter.query_metric(case.request(), context=case.context())
    assert remote.diagnostics == ()  # Fail before submitting an empty-source query.


def test_v1_and_authorized_dimension_values(
    cloud_adapter: Callable[[str], AthenaSemanticAdapter], evidence: list[AthenaSemanticAdapter]
) -> None:
    case = ParityCase("v1", "net_revenue", ())
    remote = cloud_adapter("parity-v1")
    evidence.append(remote)
    response = remote.query_metric(
        QueryMetricRequest(
            metric_id="net_revenue", time_range=TimeRange(start=case.start, end=case.end)
        ),
        context=case.context(),
    )
    assert response.rows[0].value == Decimal("41.50")
    scoped = case.context().model_copy(update={"allowed_regions": ("North",)})
    discovered = remote.discover_dimensions(
        DiscoverDimensionsRequestV2(metric_id="net_revenue"), context=scoped
    )
    assert {
        dimension.dimension.dimension_id: dimension.values for dimension in discovered.dimensions
    } == {
        "region": ("North",),
        "channel": ("online",),
    }
    with pytest.raises(AuthorizationError):
        remote.query_metric(
            case.request(), context=scoped.model_copy(update={"allowed_regions": ()})
        )
