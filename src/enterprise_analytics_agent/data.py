"""Fixed-seed, fixed-period synthetic retail snapshots, written without PyArrow."""

from datetime import date, timedelta
from pathlib import Path
from random import Random
from typing import Final

import duckdb

DEFAULT_SEED: Final = 20260101
DATA_START: Final = date(2025, 1, 1)
DATA_END: Final = date(2025, 4, 1)
DEMO_TENANT: Final = "retail_demo"
REGIONS: Final = ("East", "North", "South", "West")
CHANNELS: Final = ("online", "store")

# Types are explicit, including empty tables. These are storage schemas, not tool contracts.
TABLE_SCHEMAS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
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
}
BUSINESS_KEYS: Final = {
    "customers": ("tenant_id", "customer_id"),
    "products": ("tenant_id", "product_id"),
    "orders": ("tenant_id", "order_id"),
    "order_items": ("tenant_id", "order_item_id"),
    "payments": ("tenant_id", "payment_id"),
    "refunds": ("tenant_id", "refund_id"),
}

type DataValue = str | int | date | None
type DataRow = tuple[DataValue, ...]


def generate_retail_data(output_dir: Path, *, seed: int = DEFAULT_SEED) -> dict[str, int]:
    """Write the same six logical tables for the same seed; return physical row counts.

    Includes two tenants, replayed records, partial refunds, noneligible orders,
    multiple items, and refunds approved after the fixed order period.
    """
    rng = Random(seed)
    tables: dict[str, list[DataRow]] = {table: [] for table in TABLE_SCHEMAS}
    for tenant in (DEMO_TENANT, "other_retail"):
        customers = [(f"c{i:03d}", REGIONS[i % len(REGIONS)]) for i in range(24)]
        products = [(f"p{i:03d}", 500 + i * 275) for i in range(12)]
        for customer_id, region in customers:
            tables["customers"].append((tenant, customer_id, f"Customer {customer_id}", region))
        for i, (product_id, price) in enumerate(products):
            tables["products"].append(
                (
                    tenant,
                    product_id,
                    f"Product {product_id}",
                    ("home", "apparel", "food")[i % 3],
                    price,
                )
            )
        for index in range(120):
            order_id = f"o{index:04d}"
            customer_id, region = rng.choice(customers)
            # The first and last order dates are guaranteed to exercise the fixed interval.
            offset = index if index < 90 else rng.randrange((DATA_END - DATA_START).days)
            ordered_at = DATA_START + timedelta(days=offset)
            status = ("completed", "shipped", "pending", "canceled")[index % 4]
            channel = CHANNELS[(index // 4) % 2]
            line_net = 0
            for line in range(1 + index % 3):
                product_id, price = rng.choice(products)
                quantity = rng.randint(1, 3)
                discount = (quantity * price * rng.choice((0, 5, 10))) // 100
                item_id = f"{order_id}-i{line}"
                net = quantity * price - discount
                line_net += net
                tables["order_items"].append(
                    (tenant, item_id, order_id, product_id, quantity, price, discount)
                )
                if status in ("completed", "shipped") and (index + line) % 5 == 0:
                    refund_date = ordered_at + timedelta(days=12)
                    tables["refunds"].append(
                        (
                            tenant,
                            f"r-{item_id}",
                            item_id,
                            refund_date,
                            refund_date + timedelta(days=2),
                            "approved",
                            net // 4,
                            "USD",
                        )
                    )
                    tables["refunds"].append(
                        (tenant, f"rp-{item_id}", item_id, refund_date, None, "pending", 50, "USD")
                    )
            tax = line_net * 8 // 100
            shipping = 500 if channel == "online" else 0
            tables["orders"].append(
                (
                    tenant,
                    order_id,
                    customer_id,
                    ordered_at,
                    status,
                    "USD",
                    region,
                    channel,
                    tax,
                    shipping,
                )
            )
            tables["payments"].append(
                (
                    tenant,
                    f"pay-{order_id}",
                    order_id,
                    ordered_at,
                    "captured" if status in ("completed", "shipped") else "pending",
                    line_net + tax + shipping,
                    "USD",
                )
            )
    # Repeated ingestion of a business event must not increase revenue.
    for table in ("orders", "order_items", "payments", "refunds"):
        tables[table].append(tables[table][0])
    output_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        for table, schema in TABLE_SCHEMAS.items():
            columns = ", ".join(f"{name} {sql_type}" for name, sql_type in schema)
            connection.execute(f"CREATE TABLE {table} ({columns})")
            placeholders = ", ".join("?" for _ in schema)
            connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", tables[table])
            connection.table(table).write_parquet(str(output_dir / f"{table}.parquet"))
    return {table: len(rows) for table, rows in tables.items()}
