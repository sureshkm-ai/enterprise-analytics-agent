"""Fixed-seed, fixed-period synthetic retail snapshots, written without PyArrow."""

from datetime import date, timedelta
from pathlib import Path
from random import Random
from typing import Final, cast

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

# Optional sources extend snapshots without changing the six-table legacy format.
OPTIONAL_TABLE_SCHEMAS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "returns": (
        ("tenant_id", "VARCHAR"),
        ("return_id", "VARCHAR"),
        ("order_item_id", "VARCHAR"),
        ("quantity", "INTEGER"),
        ("returned_at", "DATE"),
        ("received_at", "DATE"),
        ("status", "VARCHAR"),
    ),
}
OPTIONAL_BUSINESS_KEYS: Final = {"returns": ("tenant_id", "return_id")}

type DataValue = str | int | date | None
type DataRow = tuple[DataValue, ...]


def _generate_return_events(tables: dict[str, list[DataRow]], *, seed: int) -> list[DataRow]:
    """Use an independent stream and never mutate existing sales or refund records."""
    rng = Random(f"{seed}:physical-returns")
    items = {(str(row[0]), str(row[1])): row for row in tables["order_items"]}
    orders = {(str(row[0]), str(row[1])): row for row in tables["orders"]}
    refunded_items = {
        (str(row[0]), str(row[2])) for row in tables["refunds"] if row[5] == "approved"
    }
    refunded_orders = {
        (tenant, str(items[(tenant, item_id)][2])) for tenant, item_id in refunded_items
    }
    events: list[DataRow] = []
    for tenant in (DEMO_TENANT, "other_retail"):
        eligible = [
            item
            for item in items.values()
            if item[0] == tenant and orders[(tenant, str(item[2]))][4] in ("completed", "shipped")
        ]
        # Reserve a refunded order with no physical return, even on its other items.
        refund_only_order = next(
            str(item[2]) for item in eligible if (tenant, str(item[2])) in refunded_orders
        )
        candidates = [item for item in eligible if item[2] != refund_only_order]
        used: set[str] = set()
        event_index = 0

        def add_event(
            item: DataRow,
            status: str,
            *,
            partial: bool = False,
            event_tenant: str = tenant,
            touched_items: set[str] = used,
        ) -> None:
            nonlocal event_index
            item_id = str(item[1])
            purchased_quantity = cast(int, item[4])
            quantity = 1 if partial else rng.randint(1, purchased_quantity)
            order_date = cast(date, orders[(event_tenant, str(item[2]))][3])
            returned_at = order_date + timedelta(days=rng.randint(6, 28))
            received_at = returned_at + timedelta(days=2) if status == "received" else None
            events.append(
                (
                    event_tenant,
                    f"ret-{event_index:04d}",
                    item_id,
                    quantity,
                    returned_at,
                    received_at,
                    status,
                )
            )
            event_index += 1
            touched_items.add(item_id)

        # Multiple received items on one order still count as one returned order.
        multi_order = next(
            str(item[2])
            for item in candidates
            if sum(other[2] == item[2] for other in candidates) > 1
        )
        for item in [item for item in candidates if item[2] == multi_order][:2]:
            add_event(item, "received")
        partial_item = next(
            item for item in candidates if item[1] not in used and cast(int, item[4]) > 1
        )
        add_event(partial_item, "received", partial=True)
        return_only_item = next(
            item
            for item in candidates
            if item[1] not in used and (tenant, str(item[2])) not in refunded_orders
        )
        add_event(return_only_item, "received")
        # Late received events demonstrate snapshot restatement beyond the order period.
        late_item = max(
            (item for item in candidates if item[1] not in used),
            key=lambda item: cast(date, orders[(tenant, str(item[2]))][3]),
        )
        add_event(late_item, "received")
        for status in ("pending", "rejected"):
            add_event(next(item for item in candidates if item[1] not in used), status)
        for item in candidates:
            if item[1] not in used and rng.randrange(8) == 0:
                add_event(item, rng.choice(("received", "pending", "rejected")))
    # Replay an identical event, preserving its tenant-scoped business identifier.
    events.append(events[0])
    return events


def generate_retail_data(output_dir: Path, *, seed: int = DEFAULT_SEED) -> dict[str, int]:
    """Write seven reproducible tables; preserve the original six for the same seed.

    Includes two tenants, replayed records, partial refunds, noneligible orders,
    multiple items, and separate physical returns after the fixed order period.
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
    tables["returns"] = _generate_return_events(tables, seed=seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        for table, schema in (TABLE_SCHEMAS | OPTIONAL_TABLE_SCHEMAS).items():
            columns = ", ".join(f"{name} {sql_type}" for name, sql_type in schema)
            connection.execute(f"CREATE TABLE {table} ({columns})")
            placeholders = ", ".join("?" for _ in schema)
            connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", tables[table])
            connection.table(table).write_parquet(str(output_dir / f"{table}.parquet"))
    return {table: len(rows) for table, rows in tables.items()}
