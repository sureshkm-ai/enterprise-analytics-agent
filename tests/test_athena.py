"""Governed Athena compilation and contracts tested without AWS or credentials.

The SQL-subset smoke tests execute emitted SELECTs in DuckDB, with literal
independent accounting answers. Actual Athena dialect acceptance is a live gate.
"""

from collections.abc import Iterator
from dataclasses import asdict
from datetime import date
from decimal import Decimal, localcontext
from typing import cast

import duckdb
import pytest
from test_athena_execution import FakeClient, page

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.adapters.athena import AthenaConfig, AthenaSemanticAdapter
from enterprise_analytics_agent.adapters.aws_schema import glue_table_name
from enterprise_analytics_agent.contracts import (
    AuthorizationContext,
    DescribeMetricRequest,
    DiscoverDimensionsRequest,
    DiscoverMetricsRequest,
    QueryMetricRequest,
    TimeRange,
)
from enterprise_analytics_agent.contracts_v2 import (
    DescribeMetricRequestV2,
    DiscoverDimensionsRequestV2,
    DiscoverMetricsRequestV2,
    QueryMetricRequestV2,
    TimeRangeV2,
)
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, TABLE_SCHEMAS, DataRow
from enterprise_analytics_agent.errors import (
    AuthorizationError,
    DataValidationError,
    InvalidDimensionError,
    MissingMetricDataError,
    UnknownMetricError,
    UnsupportedMetricVersionError,
)
from enterprise_analytics_agent.snapshots import (
    SnapshotColumn,
    SnapshotManifest,
    TableManifest,
    table_key,
)

_SCHEMAS = {**TABLE_SCHEMAS, **OPTIONAL_TABLE_SCHEMAS}
_METRICS = ("gross_sales", "net_revenue", "order_count", "average_order_value", "return_rate")


@pytest.fixture
def athena_config() -> AthenaConfig:
    return AthenaConfig(
        profile="explicit-test-profile",
        region="us-west-2",
        database="retail",
        workgroup="retail-development",
        output_location="s3://query-results/results/",
        expected_bucket_owner="123456789012",
    )


def manifest(*, returns: bool = True) -> SnapshotManifest:
    return SnapshotManifest(
        dataset_version="fixture-v1",
        tables={
            table: TableManifest(
                key=table_key("fixture-v1", table),
                sha256="0" * 64,
                row_count=0,
                size_bytes=1,
                columns=tuple(SnapshotColumn(name=name, type=kind) for name, kind in schema),
            )
            for table, schema in _SCHEMAS.items()
            if returns or table != "returns"
        },
    )


def request(metric: str, *, grouped: bool = False) -> QueryMetricRequestV2:
    return QueryMetricRequestV2(
        metric_id=metric,
        time_range=TimeRangeV2(start=date(2025, 1, 1), end=date(2025, 2, 1)),
        group_by=("region",) if grouped else (),
    )


class SqlSubsetClient(FakeClient):
    """Execute only the emitted SELECT subset in a separate offline SQL engine."""

    def __init__(self, rows: dict[str, list[DataRow]], config: AthenaConfig) -> None:
        super().__init__()
        self.connection = duckdb.connect(":memory:", config={"threads": 1})
        self.connection.execute(f'CREATE SCHEMA "{config.database}"')
        for table, values in rows.items():
            name = glue_table_name("fixture-v1", table)
            schema = ", ".join(f'"{column}" {kind}' for column, kind in _SCHEMAS[table])
            self.connection.execute(f'CREATE TABLE "{config.database}"."{name}" ({schema})')
            if values:
                self.connection.executemany(
                    f'INSERT INTO "{config.database}"."{name}" '
                    f"VALUES ({', '.join('?' for _ in _SCHEMAS[table])})",
                    values,
                )
        self.result_page: dict[str, object] = {}

    def start_query_execution(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("start", kwargs))
        encoded = cast(list[str], kwargs["ExecutionParameters"])
        parameters: list[object] = []
        for literal in encoded:
            if literal.startswith("CAST('") and literal.endswith("' AS DATE)"):
                parameters.append(date.fromisoformat(literal[6:-10]))
            else:
                assert literal.startswith("'") and literal.endswith("'")
                parameters.append(literal[1:-1].replace("''", "'"))
        cursor = self.connection.execute(str(kwargs["QueryString"]), parameters)
        columns = tuple(
            (column[0], "bigint" if str(column[1]) == "HUGEINT" else str(column[1]).lower())
            for column in cursor.description
        )
        values = [
            tuple(None if value is None else str(value) for value in row)
            for row in cursor.fetchall()
        ]
        self.result_page = page(columns, values)
        return {"QueryExecutionId": "offline-query"}

    def get_query_results(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("results", kwargs))
        return self.result_page

    def close(self) -> None:
        self.connection.close()


@pytest.fixture
def athena_rows(snapshot_rows: dict[str, list[DataRow]]) -> dict[str, list[DataRow]]:
    rows = {table: values.copy() for table, values in snapshot_rows.items()}
    rows["orders"].extend(
        [
            ("t1", "o3", "c1", date(2025, 1, 5), "completed", "USD", "North", "store", 0, 0),
            ("t1", "no-items", "c1", date(2025, 1, 5), "completed", "USD", "North", "store", 0, 0),
        ]
    )
    rows["order_items"].append(("t1", "i4", "o3", "p1", 1, 1000, 0))
    later = date(2025, 3, 1)
    received: DataRow = ("t1", "return1", "i1", 1, later, later, "received")
    rows["returns"] = [
        received,
        received,
        ("t1", "return2", "i2", 1, later, later, "received"),
        ("t1", "pending", "i3", 1, later, None, "pending"),
        ("t1", "rejected", "i4", 1, later, None, "rejected"),
        ("t1", "cancel-return", "i-cancel", 1, later, later, "received"),
        ("t1", "eur-return", "i-eur", 1, later, later, "received"),
        ("t1", "east-return", "i-hidden", 1, later, later, "received"),
        ("t2", "return1", "i1", 1, later, later, "received"),
    ]
    # Raw replay rows are deliberately retained, even though publication normally
    # canonicalizes them. Every fact source must remain fanout-safe in the SQL.
    for table in ("orders", "order_items", "refunds", "payments"):
        rows[table].append(rows[table][0])
    return rows


@pytest.fixture
def sql_adapter(
    athena_rows: dict[str, list[DataRow]], athena_config: AthenaConfig
) -> Iterator[AthenaSemanticAdapter]:
    client = SqlSubsetClient(athena_rows, athena_config)
    yield_adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    try:
        yield yield_adapter
    finally:
        client.close()


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("gross_sales", Decimal("53.00")),
        ("net_revenue", Decimal("42.50")),
        ("order_count", 3),
        ("average_order_value", Decimal("14.17")),
        ("return_rate", Decimal("0.333333")),
    ],
)
def test_all_metrics_have_independent_accounting_answers(
    sql_adapter: AthenaSemanticAdapter,
    context: AuthorizationContext,
    metric: str,
    expected: Decimal | int,
) -> None:
    result = sql_adapter.query_metric(request(metric), context=context)
    assert len(result.rows) == 1
    assert result.rows[0].value == expected
    assert result.currency == (None if metric in ("order_count", "return_rate") else "USD")
    assert result.api_version == "v2"


@pytest.mark.parametrize(
    ("metric", "north", "south"),
    [
        ("gross_sales", Decimal("38.00"), Decimal("15.00")),
        ("net_revenue", Decimal("29.50"), Decimal("13.00")),
        ("order_count", 2, 1),
        ("average_order_value", Decimal("14.75"), Decimal("13.00")),
        ("return_rate", Decimal("0.500000"), Decimal("0.000000")),
    ],
)
def test_grouping_never_averages_subgroup_ratios(
    sql_adapter: AthenaSemanticAdapter,
    context: AuthorizationContext,
    metric: str,
    north: Decimal | int,
    south: Decimal | int,
) -> None:
    result = sql_adapter.query_metric(request(metric, grouped=True), context=context)
    assert [(row.dimensions, row.value) for row in result.rows] == [
        ({"region": "North"}, north),
        ({"region": "South"}, south),
    ]


@pytest.mark.parametrize("metric", _METRICS)
def test_every_metric_scopes_tenant_region_and_empty_results(
    sql_adapter: AthenaSemanticAdapter, context: AuthorizationContext, metric: str
) -> None:
    empty = request(metric).model_copy(update={"dimension_filters": {"region": ("East",)}})
    response = sql_adapter.query_metric(empty, context=context)
    expected = None if metric in ("average_order_value", "return_rate") else 0
    assert response.rows[0].value == expected
    grouped = empty.model_copy(update={"group_by": ("region",)})
    assert sql_adapter.query_metric(grouped, context=context).rows == ()
    other = AuthorizationContext(principal_id="trusted", tenant_id="t2", allowed_regions=("North",))
    values: dict[str, Decimal | int] = {
        "gross_sales": Decimal("1000.00"),
        "net_revenue": Decimal("950.00"),
        "order_count": 1,
        "average_order_value": Decimal("950.00"),
        "return_rate": Decimal("1.000000"),
    }
    assert sql_adapter.query_metric(request(metric), context=other).rows[0].value == values[metric]
    north = context.model_copy(update={"allowed_regions": ("North",)})
    south_filter = request(metric).model_copy(update={"dimension_filters": {"region": ("South",)}})
    assert sql_adapter.query_metric(south_filter, context=north).rows[0].value == expected


@pytest.mark.parametrize(
    ("metric", "december", "february"),
    [
        ("gross_sales", Decimal("9.00"), Decimal("7.00")),
        ("net_revenue", Decimal("7.00"), Decimal("7.00")),
        ("order_count", 1, 1),
        ("average_order_value", Decimal("7.00"), Decimal("7.00")),
        ("return_rate", Decimal("0.000000"), Decimal("0.000000")),
    ],
)
def test_inclusive_start_exclusive_end_and_original_order_adjustments(
    sql_adapter: AthenaSemanticAdapter,
    context: AuthorizationContext,
    metric: str,
    december: Decimal | int,
    february: Decimal | int,
) -> None:
    before = request(metric).model_copy(
        update={"time_range": TimeRangeV2(start=date(2024, 12, 31), end=date(2025, 1, 1))}
    )
    after = request(metric).model_copy(
        update={"time_range": TimeRangeV2(start=date(2025, 2, 1), end=date(2025, 2, 2))}
    )
    assert sql_adapter.query_metric(before, context=context).rows[0].value == december
    assert sql_adapter.query_metric(after, context=context).rows[0].value == february


def test_refunds_and_returns_are_independent(
    athena_rows: dict[str, list[DataRow]],
    athena_config: AthenaConfig,
    context: AuthorizationContext,
) -> None:
    # Move the only received physical return to North order o3, which has no
    # refunds, and retain all financial refunds against o1, which now has no return.
    later = date(2025, 3, 1)
    athena_rows["returns"] = [("t1", "physical-only", "i4", 1, later, later, "received")]
    client = SqlSubsetClient(athena_rows, athena_config)
    adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    assert adapter.query_metric(request("net_revenue"), context=context).rows[0].value == Decimal(
        "42.50"
    )
    assert adapter.query_metric(request("return_rate"), context=context).rows[0].value == Decimal(
        "0.333333"
    )
    client.close()


def test_query_text_contains_only_governed_identifiers_and_bound_values(
    athena_config: AthenaConfig, context: AuthorizationContext
) -> None:
    client = FakeClient()
    client.pages = [
        page(
            (
                ("gross_cents", "decimal"),
                ("net_cents", "decimal"),
                ("order_count", "bigint"),
                ("returned_order_count", "bigint"),
            ),
            [("0", "0", "0", "0")],
        )
    ]
    adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    injection = "North' OR 1=1 --"
    result = adapter.query_metric(
        request("net_revenue").model_copy(update={"dimension_filters": {"region": (injection,)}}),
        context=context,
    )
    assert result.rows[0].value == Decimal("0.00")
    call = client.calls[0][1]
    sql = str(call["QueryString"])
    parameters = cast(list[str], call["ExecutionParameters"])
    assert injection not in sql
    assert "'North'' OR 1=1 --'" in parameters
    assert "HUGEINT" not in sql and "DECIMAL(38,0)" in sql
    assert sql.count("?") == len(parameters)
    assert 'o."ordered_at" >= ?' in sql and 'o."ordered_at" < ?' in sql
    assert "refunded_at >=" not in sql and "approved_at <" not in sql
    assert "payments" not in sql
    assert "COUNT(*)" in sql and "GROUP BY o.tenant_id, o.order_id" in sql
    assert "SELECT DISTINCT" in sql
    assert "o.tenant_id = ?" in sql and "o.region IN (?, ?)" in sql
    assert "SUM(CAST(r.amount_cents AS DECIMAL(38,0)))" in sql
    assert "Athena" not in result.model_dump_json()
    assert "query_id" not in result.model_dump_json()


def test_legacy_six_table_inventory_remains_usable_and_missing_returns_fail(
    athena_config: AthenaConfig, context: AuthorizationContext
) -> None:
    client = FakeClient()
    adapter = AthenaSemanticAdapter(athena_config, manifest(returns=False), client=client)
    assert len(adapter.discover_metrics(DiscoverMetricsRequestV2(), context=context).metrics) == 5
    with pytest.raises(MissingMetricDataError, match="returns.parquet"):
        adapter.query_metric(request("return_rate"), context=context)
    assert not client.calls
    client.pages = [page((("dimension_value", "varchar"),), [("North",)])]
    assert adapter.discover_dimensions(
        DiscoverDimensionsRequestV2(metric_id="return_rate"), context=context
    ).dimensions[0].values == ("North",)


def test_public_v1_compatibility_and_metadata_are_backend_independent(
    sql_adapter: AthenaSemanticAdapter, context: AuthorizationContext
) -> None:
    semantic: SemanticAdapter = sql_adapter
    result = semantic.query_metric(
        QueryMetricRequest(
            metric_id="net_revenue",
            time_range=TimeRange(start=date(2025, 1, 1), end=date(2025, 2, 1)),
            group_by=("region",),
        ),
        context=context,
    )
    assert result.model_dump_json() == (
        '{"api_version":"v1","metric_id":"net_revenue","definition_version":"1.0.0",'
        '"time_range":{"api_version":"v1","start":"2025-01-01","end":"2025-02-01"},'
        '"group_by":["region"],"unit":"currency","currency":"USD","rows":['
        '{"api_version":"v1","dimensions":{"region":"North"},"value":"29.50"},'
        '{"api_version":"v1","dimensions":{"region":"South"},"value":"13.00"}]}'
    )
    assert [
        metric.metric_id
        for metric in semantic.discover_metrics(DiscoverMetricsRequest(), context=context).metrics
    ] == ["net_revenue"]
    assert len(semantic.discover_metrics(DiscoverMetricsRequestV2(), context=context).metrics) == 5
    assert (
        semantic.discover_metrics(DiscoverMetricsRequestV2(search="return"), context=context)
        .metrics[0]
        .metric_id
        == "return_rate"
    )
    v1 = semantic.describe_metric(DescribeMetricRequest(metric_id="net_revenue"), context=context)
    v2 = semantic.describe_metric(DescribeMetricRequestV2(metric_id="return_rate"), context=context)
    assert v1.metric.definition_version == v2.metric.definition_version == "1.0.0"
    assert v2.metric.currency is None and v2.metric.unit == "ratio"
    assert v2.metric.time_semantics.as_of_cutoff is False
    assert "DECIMAL" not in v2.model_dump_json()
    assert "tenant_id" not in v2.model_dump_json()


def test_dimension_discovery_has_same_authorization_and_business_filters(
    sql_adapter: AthenaSemanticAdapter, context: AuthorizationContext
) -> None:
    result = sql_adapter.discover_dimensions(
        DiscoverDimensionsRequest(metric_id="net_revenue"), context=context
    )
    assert [dimension.values for dimension in result.dimensions] == [
        ("North", "South"),
        ("online", "store"),
    ]
    other = context.model_copy(update={"tenant_id": "missing"})
    assert all(
        not dimension.values
        for dimension in sql_adapter.discover_dimensions(
            DiscoverDimensionsRequestV2(metric_id="return_rate"), context=other
        ).dimensions
    )


@pytest.mark.parametrize("operation", ["metrics", "describe", "dimensions", "query"])
def test_authorization_is_required_before_any_operation(
    athena_config: AthenaConfig, context: AuthorizationContext, operation: str
) -> None:
    client = FakeClient()
    adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    bad = context.model_copy(update={"allowed_regions": ()})
    with pytest.raises(AuthorizationError):
        if operation == "metrics":
            adapter.discover_metrics(DiscoverMetricsRequestV2(), context=bad)
        elif operation == "describe":
            adapter.describe_metric(DescribeMetricRequestV2(metric_id="net_revenue"), context=bad)
        elif operation == "dimensions":
            adapter.discover_dimensions(
                DiscoverDimensionsRequestV2(metric_id="net_revenue"), context=bad
            )
        else:
            adapter.query_metric(request("net_revenue"), context=bad)
    assert not client.calls


def test_unknown_metric_dimension_and_version_fail_before_submission(
    athena_config: AthenaConfig, context: AuthorizationContext
) -> None:
    client = FakeClient()
    adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    with pytest.raises(UnknownMetricError):
        adapter.query_metric(request("SELECT secret"), context=context)
    with pytest.raises(InvalidDimensionError):
        adapter.query_metric(
            request("net_revenue").model_copy(update={"group_by": ("tenant_id",)}), context=context
        )
    with pytest.raises(UnsupportedMetricVersionError):
        adapter.query_metric(
            QueryMetricRequest(
                metric_id="order_count",
                time_range=TimeRange(start=date(2025, 1, 1), end=date(2025, 2, 1)),
            ),
            context=context,
        )
    assert not client.calls


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile", ""),
        ("region", ""),
        ("database", 'retail";DROP'),
        ("table_prefix", "ea;"),
        ("workgroup", ""),
        ("output_location", "s3://bucket-no-slash"),
        ("expected_bucket_owner", ""),
        ("timeout_seconds", 0),
        ("timeout_seconds", float("inf")),
        ("poll_seconds", 0),
        ("max_attempts", 0),
    ],
)
def test_configuration_is_explicit_and_validated(
    athena_config: AthenaConfig, field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        settings = asdict(athena_config)
        settings[field] = value
        AthenaConfig(**settings)


@pytest.mark.parametrize(
    ("metric", "gross", "net", "orders", "returned", "expected"),
    [
        ("average_order_value", "1", "1", "2", "0", Decimal("0.01")),
        ("average_order_value", "0", "-1", "2", "0", Decimal("-0.01")),
        ("return_rate", "0", "0", "128", "1", Decimal("0.007813")),
    ],
)
def test_rounding_is_exact_half_up_independent_of_decimal_context(
    athena_config: AthenaConfig,
    context: AuthorizationContext,
    metric: str,
    gross: str,
    net: str,
    orders: str,
    returned: str,
    expected: Decimal,
) -> None:
    client = FakeClient()
    client.pages = [
        page(
            (
                ("gross_cents", "decimal"),
                ("net_cents", "decimal"),
                ("order_count", "bigint"),
                ("returned_order_count", "bigint"),
            ),
            [(gross, net, orders, returned)],
        )
    ]
    adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    with localcontext() as decimal_context:
        decimal_context.prec = 2
        assert adapter.query_metric(request(metric), context=context).rows[0].value == expected


def test_invalid_aggregate_is_rejected(
    athena_config: AthenaConfig, context: AuthorizationContext
) -> None:
    client = FakeClient()
    client.pages = [
        page(
            (
                ("gross_cents", "decimal"),
                ("net_cents", "decimal"),
                ("order_count", "bigint"),
                ("returned_order_count", "bigint"),
            ),
            [("1.5", "0", "0", "0")],
        )
    ]
    adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    with pytest.raises(DataValidationError, match="exact integer"):
        adapter.query_metric(request("gross_sales"), context=context)


def test_present_empty_returns_yields_zero_and_legacy_supports_other_metrics(
    athena_rows: dict[str, list[DataRow]],
    athena_config: AthenaConfig,
    context: AuthorizationContext,
) -> None:
    athena_rows["returns"] = []
    client = SqlSubsetClient(athena_rows, athena_config)
    adapter = AthenaSemanticAdapter(athena_config, manifest(), client=client)
    assert adapter.query_metric(request("return_rate"), context=context).rows[0].value == Decimal(
        "0.000000"
    )
    client.close()
    del athena_rows["returns"]
    client = SqlSubsetClient(athena_rows, athena_config)
    adapter = AthenaSemanticAdapter(athena_config, manifest(returns=False), client=client)
    expected: dict[str, Decimal | int] = {
        "gross_sales": Decimal("53.00"),
        "net_revenue": Decimal("42.50"),
        "order_count": 3,
        "average_order_value": Decimal("14.17"),
    }
    for metric, value in expected.items():
        assert adapter.query_metric(request(metric), context=context).rows[0].value == value
    client.close()


def test_sdk_request_shapes_with_stubber(
    athena_config: AthenaConfig, context: AuthorizationContext
) -> None:
    """Botocore validates request keys/types against its actual service model."""
    import boto3
    from botocore.stub import ANY, Stubber

    from enterprise_analytics_agent.adapters.athena_execution import AthenaClient

    sdk = boto3.Session(
        aws_access_key_id="offline-testing", aws_secret_access_key="offline-testing"
    ).client("athena", region_name="us-west-2")
    columns = (
        ("gross_cents", "decimal"),
        ("net_cents", "decimal"),
        ("order_count", "bigint"),
        ("returned_order_count", "bigint"),
    )
    with Stubber(sdk) as stub:
        stub.add_response(
            "start_query_execution",
            {"QueryExecutionId": "stubbed-query"},
            {
                "QueryString": ANY,
                "ClientRequestToken": ANY,
                "QueryExecutionContext": {"Database": "retail", "Catalog": "AwsDataCatalog"},
                "WorkGroup": "retail-development",
                "ResultConfiguration": {
                    "OutputLocation": "s3://query-results/results/",
                    "ExpectedBucketOwner": "123456789012",
                    "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
                },
                "ExecutionParameters": ANY,
                "ResultReuseConfiguration": {"ResultReuseByAgeConfiguration": {"Enabled": False}},
            },
        )
        stub.add_response(
            "get_query_execution",
            {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}},
            {"QueryExecutionId": "stubbed-query"},
        )
        stub.add_response(
            "get_query_results",
            page(columns, [("5300", "4250", "3", "0")]),
            {"QueryExecutionId": "stubbed-query", "MaxResults": 1000},
        )
        adapter = AthenaSemanticAdapter(athena_config, manifest(), client=cast(AthenaClient, sdk))
        assert adapter.query_metric(request("net_revenue"), context=context).rows[
            0
        ].value == Decimal("42.50")
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("actual_account", ["123456789012", "999999999999"])
def test_profile_factory_requires_explicit_profile_region_account_and_bounded_sdk_config(
    athena_config: AthenaConfig, monkeypatch: pytest.MonkeyPatch, actual_account: str
) -> None:
    import boto3
    from botocore.config import Config

    observed: dict[str, object] = {}
    clients: list[str] = []

    class STS:
        def get_caller_identity(self) -> dict[str, str]:
            observed["identity_checked"] = True
            return {"Account": actual_account}

    class Session:
        def __init__(self, *, profile_name: str, region_name: str) -> None:
            observed["profile"] = profile_name
            observed["region"] = region_name

        def client(self, name: str, *, config: Config) -> FakeClient | STS:
            clients.append(name)
            observed["sdk_config"] = config
            if name == "sts":
                return STS()
            assert name == "athena"
            assert observed["identity_checked"] is True
            return FakeClient()

    monkeypatch.setattr(boto3, "Session", Session)
    if actual_account == athena_config.expected_bucket_owner:
        adapter = AthenaSemanticAdapter.from_profile(athena_config, manifest())
        assert adapter.diagnostics == ()
        assert clients == ["sts", "athena"]
    else:
        with pytest.raises(AuthorizationError, match="different account"):
            AthenaSemanticAdapter.from_profile(athena_config, manifest())
        assert clients == ["sts"]
    assert (observed["profile"], observed["region"]) == ("explicit-test-profile", "us-west-2")
    sdk_config = cast(Config, observed["sdk_config"])
    options = cast(dict[str, object], vars(sdk_config))
    assert options["connect_timeout"] == 5.0 and options["read_timeout"] == 10.0
    assert options["retries"] == {"total_max_attempts": 1, "mode": "standard"}
