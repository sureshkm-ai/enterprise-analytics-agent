"""Generator compatibility and physical-return facts, not expected metric calculations."""

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from enterprise_analytics_agent.data import (
    BUSINESS_KEYS,
    OPTIONAL_BUSINESS_KEYS,
    OPTIONAL_TABLE_SCHEMAS,
    TABLE_SCHEMAS,
    generate_retail_data,
)

# Frozen before the M2 generator edit from commit 64cbea4's six logical tables.
# These are compatibility fingerprints, never expected answers for a metric.
# Canonical encoding: all columns sorted, compact JSON, dates as ISO strings.
M1_FINGERPRINTS = {
    20260101: {
        "customers": "b6f10a64c88c8318894c263d510d38941f2b0baebca517c2d33a89eb194208e5",
        "products": "643465389e9fa569dbf169fb2d51db2ea28dc410fc9e95deaa47effa485ee0ca",
        "orders": "0d3912693a02b2a9f467e73dc44763472b80dd12235d1b266ee09a470767cc24",
        "order_items": "f3767d2209a7c06e8f733a10e34786497f6160968cee13b3a4e33acff9c62e01",
        "payments": "7883b86adf25695225836dbda93688cb68d729f63dfc7f05acbbcdd657550093",
        "refunds": "f350f1d5d66f9d5bbadc74cfa37cdabb601f861b2763d7c790047c2f480ae90f",
    },
    7: {
        "customers": "b6f10a64c88c8318894c263d510d38941f2b0baebca517c2d33a89eb194208e5",
        "products": "643465389e9fa569dbf169fb2d51db2ea28dc410fc9e95deaa47effa485ee0ca",
        "orders": "af73e80d9cbded71d27f36c348669eeced8978421cf2ab2d345a00fd23da2492",
        "order_items": "278cfc7678b7c60fa669138e432b6482abf1287cf2478c0a834279096d18ebe4",
        "payments": "3fc77cacb210118736a5137f83d597f55565532b281b0ec2b41e71d659983a2b",
        "refunds": "365d0f88dc2e5e180eccfb7dc1adfdbcb15cca0da48313be3063f26cdf58404c",
    },
}


def _rows(directory: Path, table: str) -> list[tuple[Any, ...]]:
    with duckdb.connect(":memory:") as connection:
        return connection.read_parquet(str(directory / f"{table}.parquet")).order("ALL").fetchall()


@pytest.mark.parametrize("seed", [20260101, 7])
def test_original_six_tables_match_frozen_milestone_one_records(tmp_path: Path, seed: int) -> None:
    generate_retail_data(tmp_path, seed=seed)
    assert set(TABLE_SCHEMAS) == {
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "refunds",
    }
    assert set(BUSINESS_KEYS) == set(TABLE_SCHEMAS)
    for table, expected in M1_FINGERPRINTS[seed].items():
        encoded = json.dumps(_rows(tmp_path, table), default=str, separators=(",", ":")).encode()
        assert hashlib.sha256(encoded).hexdigest() == expected


def test_returns_are_reproducible_and_use_a_separate_seeded_stream(tmp_path: Path) -> None:
    first, second, changed = (tmp_path / name for name in ("first", "second", "changed"))
    first_counts = generate_retail_data(first)
    second_counts = generate_retail_data(second)
    generate_retail_data(changed, seed=7)
    assert _rows(first, "returns") == _rows(second, "returns")
    assert _rows(first, "returns") != _rows(changed, "returns")
    assert first_counts == second_counts
    assert first_counts["returns"] == len(_rows(first, "returns"))
    generate_retail_data(first)
    assert _rows(first, "returns") == _rows(second, "returns")


def test_generated_returns_have_explicit_schema_and_tenant_scoped_relationships(
    tmp_path: Path,
) -> None:
    generate_retail_data(tmp_path)
    assert OPTIONAL_BUSINESS_KEYS == {"returns": ("tenant_id", "return_id")}
    with duckdb.connect(":memory:") as connection:
        for table in ("orders", "order_items", "refunds", "returns"):
            connection.read_parquet(str(tmp_path / f"{table}.parquet")).create_view(table)
        returns = connection.table("returns")
        assert (
            tuple(zip(returns.columns, map(str, returns.types), strict=True))
            == (OPTIONAL_TABLE_SCHEMAS["returns"])
        )
        assert connection.execute(
            "SELECT count(*) FROM returns r WHERE NOT EXISTS "
            "(SELECT 1 FROM order_items i "
            "WHERE i.tenant_id=r.tenant_id AND i.order_item_id=r.order_item_id)"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM returns r JOIN order_items i "
            "ON i.tenant_id=r.tenant_id AND i.order_item_id=r.order_item_id "
            "WHERE r.quantity <= 0 OR r.quantity > i.quantity"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM returns WHERE "
            "(status='received' AND received_at IS NULL) "
            "OR (status<>'received' AND received_at IS NOT NULL)"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT status FROM returns GROUP BY status ORDER BY status"
        ).fetchall() == [("pending",), ("received",), ("rejected",)]
        # IDs may repeat across tenants; only the tenant-scoped pair identifies a return.
        assert connection.execute(
            "SELECT count(DISTINCT tenant_id) FROM returns WHERE return_id='ret-0000'"
        ).fetchone() == (2,)


@pytest.mark.parametrize("seed", [20260101, 7])
def test_generated_returns_exercise_physical_and_financial_distinctions(
    tmp_path: Path, seed: int
) -> None:
    generate_retail_data(tmp_path, seed=seed)
    with duckdb.connect(":memory:") as connection:
        for table in ("orders", "order_items", "refunds", "returns"):
            connection.read_parquet(str(tmp_path / f"{table}.parquet")).create_view(table)
        # At least one partial received return and multiple received items on one order.
        partial = connection.execute(
            "SELECT count(*) FROM returns r JOIN order_items i "
            "ON i.tenant_id=r.tenant_id AND i.order_item_id=r.order_item_id "
            "WHERE r.status='received' AND r.quantity < i.quantity"
        ).fetchone()
        assert partial is not None and partial[0] > 0
        multiple_items = connection.execute(
            "SELECT i.tenant_id, i.order_id FROM returns r JOIN order_items i "
            "ON i.tenant_id=r.tenant_id AND i.order_item_id=r.order_item_id "
            "WHERE r.status='received' GROUP BY i.tenant_id,i.order_id "
            "HAVING count(DISTINCT r.order_item_id)>1"
        ).fetchall()
        assert multiple_items
        physical_replays = connection.execute("SELECT count(*) FROM returns").fetchone()
        logical_events = connection.execute(
            "SELECT count(*) FROM (SELECT DISTINCT * FROM returns)"
        ).fetchone()
        assert physical_replays is not None and logical_events is not None
        assert physical_replays[0] == logical_events[0] + 1
        later_received = connection.execute(
            "SELECT count(*) FROM returns WHERE status='received' "
            "AND received_at >= DATE '2025-04-01'"
        ).fetchone()
        assert later_received is not None and later_received[0] > 0
        # Each tenant has refunded orders without a received physical return and vice versa.
        facts = connection.execute(
            "SELECT o.tenant_id, "
            "EXISTS (SELECT 1 FROM refunds f JOIN order_items i "
            "ON i.tenant_id=f.tenant_id AND i.order_item_id=f.order_item_id "
            "WHERE i.tenant_id=o.tenant_id AND i.order_id=o.order_id "
            "AND f.status='approved') AS refunded, "
            "EXISTS (SELECT 1 FROM returns r JOIN order_items i "
            "ON i.tenant_id=r.tenant_id AND i.order_item_id=r.order_item_id "
            "WHERE i.tenant_id=o.tenant_id AND i.order_id=o.order_id "
            "AND r.status='received') AS physically_returned "
            "FROM orders o WHERE o.status IN ('completed','shipped')"
        ).fetchall()
        for tenant in ("retail_demo", "other_retail"):
            assert (tenant, True, False) in facts
            assert (tenant, False, True) in facts
