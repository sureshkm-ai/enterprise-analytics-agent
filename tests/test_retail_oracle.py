"""Handwritten independent proofs; no generator/adapter is used for expectations."""

import hashlib
import json
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import duckdb
import pytest

from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, TimeRangeV2
from enterprise_analytics_agent.retail_evaluation.oracle import (
    SCHEMAS,
    OracleInputError,
    OracleSnapshot,
    SourceRow,
    freeze_retail_evidence,
    verify_local_provenance,
)


def authored_rows() -> dict[str, list[SourceRow]]:
    """A: $28-$3-$5.50=$19.50; B: $10-$1=$9; C: $15-$2=$13.

    A has two received returned items; B has a refund but no received return;
    C has a received return without a refund. Counts are 3 orders, 2 returned.
    The total is $53 gross, $41.50 net, AOV $13.83 and rate 0.666667.
    """
    jan1, jan2, jan3 = date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)
    later = date(2026, 7, 1)
    return {
        "customers": [
            {"tenant_id": "retail_demo", "customer_id": "c", "name": "Demo", "region": "North"},
            {"tenant_id": "other", "customer_id": "c", "name": "Other", "region": "North"},
        ],
        "products": [
            {
                "tenant_id": "retail_demo",
                "product_id": "p",
                "name": "Item",
                "category": "a",
                "unit_price_cents": 1000,
            },
            {
                "tenant_id": "other",
                "product_id": "p",
                "name": "Other",
                "category": "a",
                "unit_price_cents": 1000,
            },
        ],
        "orders": [
            _order("a", jan1, "North", "online", tax=999999, shipping=888888),
            _order("b", jan2, "North", "store"),
            _order("c", jan3, "South", "store", status="shipped"),
            _order("empty", jan1, "North", "online"),
            _order("canceled", jan1, "North", "online", status="canceled"),
            _order("pending", jan1, "North", "online", status="pending"),
            _order("eur", jan1, "North", "online", currency="EUR"),
            _order("hidden", jan1, "East", "online"),
            _order("before", date(2024, 12, 31), "North", "online"),
            _order("end", date(2025, 2, 1), "North", "online"),
            _order("a", jan1, "North", "online", tenant="other"),
        ],
        "order_items": [
            _item("a1", "a", 2, 1000, 300),
            _item("a2", "a", 1, 800, 0),
            _item("b1", "b", 1, 1000, 0),
            _item("c1", "c", 3, 500, 200),
            *[
                _item(order, order, 1, 100000, 0)
                for order in ("canceled", "pending", "eur", "hidden", "before", "end")
            ],
            _item("a1", "a", 1, 1000000, 0, tenant="other"),
        ],
        "payments": [
            {
                "tenant_id": "retail_demo",
                "payment_id": name,
                "order_id": "a",
                "paid_at": jan1,
                "status": "captured",
                "amount_cents": amount,
                "currency": "USD",
            }
            for name, amount in (("pay1", 888888), ("pay2", 999999))
        ],
        "refunds": [
            _refund("r1", "a1", 400, later),
            _refund("r2", "a1", 150, later),
            _refund("refund-only", "b1", 100, later),
            _refund("pending", "a1", 900, jan3, status="pending"),
            _refund("rejected", "a1", 777, jan3, status="rejected"),
            _refund("not-usd", "a1", 99999, later, currency="EUR"),
            _refund("canceled", "canceled", 100, later),
            _refund("other", "a1", 50000, later, tenant="other"),
        ],
        "returns": [
            _return("partial", "a1", 1, later),
            _return("second-event", "a1", 1, later),
            _return("second-item", "a2", 1, later),
            _return("return-only", "c1", 1, later),
            _return("pending", "b1", 1, later, status="pending"),
            _return("rejected", "b1", 1, later, status="rejected"),
            _return("canceled", "canceled", 1, later),
            _return("other", "a1", 1, later, tenant="other"),
        ],
    }


def _order(
    order_id: str,
    ordered_at: date,
    region: str,
    channel: str,
    *,
    tenant: str = "retail_demo",
    status: str = "completed",
    currency: str = "USD",
    tax: int = 0,
    shipping: int = 0,
) -> SourceRow:
    return {
        "tenant_id": tenant,
        "order_id": order_id,
        "customer_id": "c",
        "ordered_at": ordered_at,
        "status": status,
        "currency": currency,
        "region": region,
        "channel": channel,
        "tax_cents": tax,
        "shipping_cents": shipping,
    }


def _item(
    item_id: str,
    order_id: str,
    quantity: int,
    price: int,
    discount: int,
    *,
    tenant: str = "retail_demo",
) -> SourceRow:
    return {
        "tenant_id": tenant,
        "order_item_id": item_id,
        "order_id": order_id,
        "product_id": "p",
        "quantity": quantity,
        "unit_price_cents": price,
        "discount_cents": discount,
    }


def _refund(
    refund_id: str,
    item_id: str,
    amount: int,
    occurred: date,
    *,
    status: str = "approved",
    tenant: str = "retail_demo",
    currency: str = "USD",
) -> SourceRow:
    return {
        "tenant_id": tenant,
        "refund_id": refund_id,
        "order_item_id": item_id,
        "refunded_at": occurred,
        "approved_at": occurred if status == "approved" else None,
        "status": status,
        "amount_cents": amount,
        "currency": currency,
    }


def _return(
    return_id: str,
    item_id: str,
    quantity: int,
    occurred: date,
    *,
    status: str = "received",
    tenant: str = "retail_demo",
) -> SourceRow:
    return {
        "tenant_id": tenant,
        "return_id": return_id,
        "order_item_id": item_id,
        "quantity": quantity,
        "returned_at": occurred,
        "received_at": occurred if status == "received" else None,
        "status": status,
    }


def request(
    metric_id: str,
    *,
    group_by: tuple[str, ...] = (),
    filters: dict[str, tuple[str, ...]] | None = None,
    start: date = date(2025, 1, 1),
    end: date = date(2025, 2, 1),
) -> QueryMetricRequestV2:
    return QueryMetricRequestV2(
        metric_id=metric_id,
        time_range=TimeRangeV2(start=start, end=end),
        group_by=group_by,
        dimension_filters=filters or {},
    )


@pytest.mark.parametrize(
    ("metric", "expected", "unit", "currency"),
    [
        ("gross_sales", "53.00", "currency", "USD"),
        ("net_revenue", "41.50", "currency", "USD"),
        ("order_count", 3, "count", None),
        ("average_order_value", "13.83", "currency", "USD"),
        ("return_rate", "0.666667", "ratio", None),
    ],
)
def test_independent_multi_metric_proof(
    metric: str,
    expected: str | int,
    unit: str,
    currency: str | None,
) -> None:
    # Literal calculations are above; neither production metrics nor generator
    # provide any expected value. Repeat *every* source to challenge join fanout.
    tables = authored_rows()
    for table in tables:
        tables[table] = tables[table] + deepcopy(tables[table])
    result = OracleSnapshot.from_rows(tables).query(
        request(metric), tenant_id="retail_demo", allowed_regions=("North", "South")
    )
    assert result.model_dump(mode="json")["rows"] == [
        {"api_version": "v2", "dimensions": {}, "value": expected}
    ]
    assert result.unit == unit
    assert result.currency == currency


@pytest.mark.parametrize(
    ("metric", "north", "south"),
    [
        ("gross_sales", "38.00", "15.00"),
        ("net_revenue", "28.50", "13.00"),
        ("order_count", 2, 1),
        ("average_order_value", "14.25", "13.00"),
        ("return_rate", "0.500000", "1.000000"),
    ],
)
def test_grouped_arithmetic_and_aggregate_ratios(
    metric: str,
    north: str | int,
    south: str | int,
) -> None:
    result = OracleSnapshot.from_rows(authored_rows()).query(
        request(metric, group_by=("region",)),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    )
    assert result.model_dump(mode="json")["rows"] == [
        {"api_version": "v2", "dimensions": {"region": "North"}, "value": north},
        {"api_version": "v2", "dimensions": {"region": "South"}, "value": south},
    ]


def test_original_order_dates_refund_only_return_only_and_contribution_worksheet() -> None:
    snapshot = OracleSnapshot.from_rows(authored_rows())
    refund_only = snapshot.query(
        request(
            "net_revenue",
            filters={"channel": ("store",)},
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
        ),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    )
    assert refund_only.rows[0].value == Decimal("9.00")
    assert snapshot.query(
        request("return_rate", start=date(2025, 1, 2), end=date(2025, 1, 3)),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    ).rows[0].value == Decimal("0.000000")
    assert snapshot.query(
        request("net_revenue", start=date(2025, 1, 3), end=date(2025, 1, 4)),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    ).rows[0].value == Decimal("13.00")
    assert snapshot.query(
        request("return_rate", start=date(2025, 1, 3), end=date(2025, 1, 4)),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    ).rows[0].value == Decimal("1.000000")
    a1 = next(
        row
        for row in snapshot.contribution_rows()
        if row["tenant_id"] == "retail_demo" and row["order_item_id"] == "a1"
    )
    assert a1["gross_cents"] == 2000
    assert a1["discount_cents"] == 300
    assert a1["approved_refund_cents"] == 550
    assert a1["net_cents"] == 1150
    assert a1["approved_refund_ids"] == "r1|r2"
    assert a1["received_return_ids"] == "partial|second-event"


@pytest.mark.parametrize(
    ("metric", "empty"),
    [
        ("net_revenue", "0.00"),
        ("gross_sales", "0.00"),
        ("order_count", 0),
        ("average_order_value", None),
        ("return_rate", None),
    ],
)
def test_empty_ungrouped_grouped_and_tenant_region_isolation(
    metric: str,
    empty: str | int | None,
) -> None:
    snapshot = OracleSnapshot.from_rows(authored_rows())
    no_auth_region = request(metric, filters={"region": ("East",)})
    result = snapshot.query(no_auth_region, tenant_id="retail_demo", allowed_regions=("North",))
    assert result.model_dump(mode="json")["rows"][0]["value"] == empty
    assert (
        snapshot.query(
            request(metric, group_by=("region",), start=date(2030, 1, 1), end=date(2030, 2, 1)),
            tenant_id="retail_demo",
            allowed_regions=("North", "South"),
        ).rows
        == ()
    )
    missing_tenant = snapshot.query(
        request(metric),
        tenant_id="missing",
        allowed_regions=("North", "South"),
    )
    assert missing_tenant.model_dump(mode="json")["rows"][0]["value"] == empty


def test_count_excludes_no_item_order_and_tenant_scoped_ids_do_not_collide() -> None:
    snapshot = OracleSnapshot.from_rows(authored_rows())
    assert (
        snapshot.query(
            request("order_count"),
            tenant_id="other",
            allowed_regions=("North", "South"),
        )
        .rows[0]
        .value
        == 1
    )
    assert snapshot.query(
        request("net_revenue"),
        tenant_id="other",
        allowed_regions=("North", "South"),
    ).rows[0].value == Decimal("9500.00")
    assert (
        snapshot.query(
            request("order_count", filters={"region": ("North",), "channel": ("store",)}),
            tenant_id="retail_demo",
            allowed_regions=("North", "South"),
        )
        .rows[0]
        .value
        == 1
    )


@pytest.mark.parametrize("metric", ["net_revenue", "gross_sales", "order_count", "return_rate"])
def test_inclusive_start_exclusive_end(metric: str) -> None:
    snapshot = OracleSnapshot.from_rows(authored_rows())
    # End boundary record is outside January, and included when its date becomes start.
    result = snapshot.query(
        request(metric, start=date(2025, 2, 1), end=date(2025, 2, 2)),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    )
    expectations: dict[str, int | Decimal] = {
        "net_revenue": Decimal("1000.00"),
        "gross_sales": Decimal("1000.00"),
        "order_count": 1,
        "return_rate": Decimal("0.000000"),
    }
    assert result.rows[0].value == expectations[metric]


def _rounding_rows(count: int) -> dict[str, list[SourceRow]]:
    base = authored_rows()
    base["orders"] = [_order(str(i), date(2025, 1, 1), "North", "online") for i in range(count)]
    base["order_items"] = [_item(str(i), str(i), 1, 1 if i == 0 else 0, 0) for i in range(count)]
    base["payments"] = []
    base["refunds"] = []
    base["returns"] = [_return("one", "0", 1, date(2026, 1, 1))]
    return base


def test_half_up_final_rounding_is_independent_of_global_decimal_context() -> None:
    # One cent over 2 orders = $0.005 -> $0.01. 1/128 = .0078125 -> .007813.
    with localcontext() as context:
        context.prec = 2
        assert OracleSnapshot.from_rows(_rounding_rows(2)).query(
            request("average_order_value"),
            tenant_id="retail_demo",
            allowed_regions=("North",),
        ).rows[0].value == Decimal("0.01")
        assert OracleSnapshot.from_rows(_rounding_rows(128)).query(
            request("return_rate"),
            tenant_id="retail_demo",
            allowed_regions=("North",),
        ).rows[0].value == Decimal("0.007813")
        assert context.prec == 2


def test_negative_adjustment_rounds_half_up_away_from_zero() -> None:
    tables = _rounding_rows(2)
    tables["order_items"][0]["unit_price_cents"] = 0
    tables["refunds"] = [_refund("adjustment", "0", 1, date(2026, 1, 1))]
    assert OracleSnapshot.from_rows(tables).query(
        request("average_order_value"),
        tenant_id="retail_demo",
        allowed_regions=("North",),
    ).rows[0].value == Decimal("-0.01")


def test_absent_and_empty_returns_sources_remain_distinct() -> None:
    tables = authored_rows()
    del tables["returns"]
    legacy = OracleSnapshot.from_rows(tables)
    assert legacy.query(
        request("net_revenue"), tenant_id="retail_demo", allowed_regions=("North", "South")
    ).rows[0].value == Decimal("41.50")
    with pytest.raises(OracleInputError, match="requires the physical returns source"):
        legacy.query(request("return_rate"), tenant_id="retail_demo", allowed_regions=("North",))
    tables["returns"] = []
    assert OracleSnapshot.from_rows(tables).query(
        request("return_rate"),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    ).rows[0].value == Decimal("0.000000")


@pytest.mark.parametrize("table", tuple(SCHEMAS))
def test_conflicting_business_events_fail_instead_of_latest_write_wins(table: str) -> None:
    tables = authored_rows()
    conflict = dict(tables[table][0])
    field = {
        "customers": "name",
        "products": "name",
        "orders": "channel",
        "order_items": "quantity",
        "payments": "amount_cents",
        "refunds": "amount_cents",
        "returns": "quantity",
    }[table]
    conflict[field] = 3 if field in {"quantity", "amount_cents"} else "different"
    tables[table].append(conflict)
    with pytest.raises(OracleInputError, match="Conflicting business key"):
        OracleSnapshot.from_rows(tables)


@pytest.mark.parametrize(
    ("table", "column", "bad_value", "message"),
    [
        ("order_items", "order_id", "missing", "tenant-scoped relationship"),
        ("order_items", "product_id", "missing", "tenant-scoped relationship"),
        ("refunds", "tenant_id", "other", "tenant-scoped relationship"),
        ("orders", "ordered_at", None, "Null required"),
        ("order_items", "quantity", True, "must be an integer"),
        ("order_items", "quantity", 0, "Invalid item"),
        ("order_items", "discount_cents", 2001, "Invalid item"),
        ("refunds", "approved_at", None, "approval date"),
        ("returns", "received_at", None, "received date"),
        ("returns", "quantity", 3, "Invalid physical return"),
        ("returns", "status", "unknown", "Invalid physical return"),
        ("payments", "amount_cents", -1, "Negative amount"),
    ],
)
def test_bad_inputs_are_rejected(
    table: str,
    column: str,
    bad_value: object,
    message: str,
) -> None:
    tables = authored_rows()
    # This tenant exists, but no matching a1 under another *absent* tenant may be joined.
    if table == "refunds" and column == "tenant_id":
        bad_value = "third"
    tables[table][0][column] = bad_value
    with pytest.raises(OracleInputError, match=message):
        OracleSnapshot.from_rows(tables)


def _write_authored_parquets(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tables = authored_rows()
    with duckdb.connect(":memory:") as connection:
        for table, schema in SCHEMAS.items():
            columns = ", ".join(f'"{name}" {kind}' for name, kind in schema)
            connection.execute(f'CREATE TABLE "{table}" ({columns})')
            placeholders = ", ".join("?" for _ in schema)
            connection.executemany(
                f'INSERT INTO "{table}" VALUES ({placeholders})',
                [tuple(row[name] for name, _ in schema) for row in tables[table]],
            )
            connection.table(table).write_parquet(str(directory / f"{table}.parquet"))


def test_parquet_reader_decodes_authored_rows_and_enforces_source_schema(tmp_path: Path) -> None:
    _write_authored_parquets(tmp_path)
    result = OracleSnapshot.from_parquet(tmp_path).query(
        request("net_revenue"),
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
    )
    assert result.rows[0].value == Decimal("41.50")
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE invalid (tenant_id VARCHAR)")
        connection.table("invalid").write_parquet(str(tmp_path / "returns.parquet"))
    with pytest.raises(OracleInputError, match="Unexpected Parquet schema"):
        OracleSnapshot.from_parquet(tmp_path)


def _authored_provenance(directory: Path) -> Path:
    """Local fake download receipts for file-integrity tests, never AWS evidence."""
    _write_authored_parquets(directory)
    inventory = OracleSnapshot.from_parquet(directory).table_inventory
    tables: dict[str, object] = {}
    objects: dict[str, object] = {}
    for table, schema in SCHEMAS.items():
        path = directory / f"{table}.parquet"
        key = f"snapshots/retail-v1/{table}/part-00000.parquet"
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        tables[table] = {
            "key": key,
            "size_bytes": path.stat().st_size,
            "sha256": sha,
            "row_count": inventory[table],
            "columns": [{"name": name, "type": kind} for name, kind in schema],
        }
        objects[table] = {
            "key": key,
            "size_bytes": path.stat().st_size,
            "sha256": sha,
            "version_id": "authored-fixture-version",
            "bucket": "enterprise-analytics-dev-453711491609-us-west-2-data",
        }
    manifest = {
        "manifest_version": "v1",
        "state": "ready",
        "dataset_version": "retail-v1",
        "seed": 20260101,
        "tables": tables,
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    provenance = {
        "provenance_version": "retail-input-v1",
        "verified": True,
        "profile": "analytics-dev",
        "account": "453711491609",
        "region": "us-west-2",
        "dataset_version": "retail-v1",
        "seed": 20260101,
        "objects": objects,
        "manifest": {
            "bucket": "enterprise-analytics-dev-453711491609-us-west-2-data",
            "key": "manifests/retail-v1.json",
            "version_id": "authored-fixture-version",
            "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "size_bytes": manifest_path.stat().st_size,
        },
    }
    path = directory / "provenance.json"
    path.write_text(json.dumps(provenance))
    return path


def test_freeze_rechecks_inputs_records_operands_and_never_overwrites_answers(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "authored"
    provenance = _authored_provenance(sources)
    output = tmp_path / "new-evidence"
    questions = Path(__file__).parents[1] / "evaluations/retail-v1/questions.json"
    golden = freeze_retail_evidence(
        source_dir=sources,
        provenance_path=provenance,
        questions_path=questions,
        output_dir=output,
    )
    by_id = {case.case_id: case for case in golden.cases}
    assert len(by_id) == 36
    assert [row.value for row in by_id["Q02"].results[0].rows] == [
        Decimal("28.50"),
        Decimal("13.00"),
    ]
    assert by_id["Q26"].results == ()
    receipt = json.loads((output / "oracle-provenance.json").read_bytes())
    assert (
        receipt["expected_results_sha256"]
        == hashlib.sha256((output / "expected-results.json").read_bytes()).hexdigest()
    )
    assert (
        receipt["contributions_sha256"]
        == hashlib.sha256((output / "contributions.csv").read_bytes()).hexdigest()
    )
    notes = (output / "oracle-notes.md").read_text()
    assert "| Q02/1 | net_revenue" in notes
    assert "3800 | 300 | 650 | 2850 | 2 | 1 |" in notes
    with pytest.raises(FileExistsError):
        freeze_retail_evidence(
            source_dir=sources,
            provenance_path=provenance,
            questions_path=questions,
            output_dir=output,
        )


@pytest.mark.parametrize("tamper", ["manifest", "source", "unverified"])
def test_freeze_refuses_unverified_or_altered_inputs(tmp_path: Path, tamper: str) -> None:
    provenance = _authored_provenance(tmp_path)
    if tamper == "manifest":
        with (tmp_path / "manifest.json").open("ab") as stream:
            stream.write(b" ")
    elif tamper == "source":
        with (tmp_path / "orders.parquet").open("ab") as stream:
            stream.write(b"altered")
    else:
        receipt = json.loads(provenance.read_bytes())
        receipt["verified"] = False
        provenance.write_text(json.dumps(receipt))
    with pytest.raises(OracleInputError, match="provenance|mismatch"):
        verify_local_provenance(tmp_path, provenance)
