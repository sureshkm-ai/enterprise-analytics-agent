from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from enterprise_analytics_agent.data import (
    DATA_END,
    DATA_START,
    DEFAULT_SEED,
    TABLE_SCHEMAS,
    generate_retail_data,
)


def read_sorted_rows(directory: Path, table: str) -> list[tuple[Any, ...]]:
    with duckdb.connect(":memory:") as connection:
        return connection.read_parquet(str(directory / f"{table}.parquet")).order("ALL").fetchall()


def test_generator_is_reproducible_and_seed_is_effective(tmp_path: Path) -> None:
    first, second, changed = (tmp_path / name for name in ("first", "second", "changed"))
    first_counts = generate_retail_data(first)
    second_counts = generate_retail_data(second)
    generate_retail_data(changed, seed=7)
    assert DEFAULT_SEED == 20260101
    assert first_counts == second_counts
    assert set(first_counts) == {
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "refunds",
    }
    for table in TABLE_SCHEMAS:
        rows = read_sorted_rows(first, table)
        assert rows == read_sorted_rows(second, table)
        assert len(rows) == first_counts[table]
        assert rows
    assert read_sorted_rows(first, "order_items") != read_sorted_rows(changed, "order_items")
    # Regeneration into an existing directory must also be supported.
    assert generate_retail_data(first) == first_counts
    assert read_sorted_rows(first, "orders") == read_sorted_rows(second, "orders")


def test_generated_dates_schemas_and_relationships(tmp_path: Path) -> None:
    directory = tmp_path / "generated"
    generate_retail_data(directory)
    assert DATA_START == date(2025, 1, 1)
    assert DATA_END == date(2025, 4, 1)
    with duckdb.connect(":memory:") as connection:
        for table, schema in TABLE_SCHEMAS.items():
            relation = connection.read_parquet(str(directory / f"{table}.parquet"))
            assert tuple(zip(relation.columns, map(str, relation.types), strict=True)) == schema
            relation.create_view(table)
        assert connection.execute(
            "SELECT min(ordered_at), max(ordered_at) FROM orders"
        ).fetchone() == (date(2025, 1, 1), date(2025, 3, 31))
        for child, parent, key in (
            ("orders", "customers", "customer_id"),
            ("order_items", "orders", "order_id"),
            ("order_items", "products", "product_id"),
            ("payments", "orders", "order_id"),
            ("refunds", "order_items", "order_item_id"),
        ):
            assert connection.execute(
                f"SELECT count(*) FROM {child} c WHERE NOT EXISTS "
                f"(SELECT 1 FROM {parent} p WHERE p.tenant_id = c.tenant_id AND p.{key} = c.{key})"
            ).fetchone() == (0,)
        assert connection.execute("SELECT count(DISTINCT tenant_id) FROM orders").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM order_items WHERE quantity < 1 OR unit_price_cents < 0 "
            "OR discount_cents < 0 OR discount_cents > quantity * unit_price_cents"
        ).fetchone() == (0,)
        late_refunds = connection.execute(
            "SELECT count(*) FROM refunds WHERE status = 'approved' "
            "AND approved_at >= DATE '2025-04-01'"
        ).fetchone()
        assert late_refunds is not None
        assert late_refunds[0] > 0
