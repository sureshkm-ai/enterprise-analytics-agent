"""Small authored parity data; expected metric answers live separately in tests.

Run with ``poetry run python tests/aws_fixture_data.py --output-dir artifacts/aws-datasets``.
This prepares local files only and never creates an AWS session.
"""

import argparse
from datetime import date
from pathlib import Path

import duckdb

from enterprise_analytics_agent.data import (
    DEFAULT_SEED,
    OPTIONAL_TABLE_SCHEMAS,
    TABLE_SCHEMAS,
    DataRow,
    generate_retail_data,
)


def parity_rows() -> dict[str, list[DataRow]]:
    jan1, jan2, jan3 = date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)
    feb1, feb15, mar3 = date(2025, 2, 1), date(2025, 2, 15), date(2025, 3, 3)
    dec31 = date(2024, 12, 31)
    rows: dict[str, list[DataRow]] = {
        "customers": [
            ("t1", "c1", "Synthetic North", "North"),
            ("t1", "c2", "Synthetic South", "South"),
            ("t1", "c3", "Synthetic East", "East"),
            ("t2", "c1", "Synthetic other tenant", "North"),
        ],
        "products": [
            ("t1", "p1", "Synthetic product one", "home", 1000),
            ("t1", "p2", "Synthetic product two", "food", 800),
            ("t2", "p1", "Synthetic other product", "home", 1000),
        ],
        "orders": [
            ("t1", "o1", "c1", jan1, "completed", "USD", "North", "online", 250, 700),
            ("t1", "o2", "c2", jan2, "shipped", "USD", "South", "store", 104, 0),
            ("t1", "o3", "c1", jan3, "completed", "USD", "North", "online", 0, 0),
            ("t1", "o-empty", "c1", jan3, "completed", "USD", "North", "online", 0, 0),
            ("t1", "o-cancel", "c1", jan3, "canceled", "USD", "North", "online", 0, 0),
            ("t1", "o-pending", "c1", jan3, "pending", "USD", "North", "online", 0, 0),
            ("t1", "o-eur", "c1", jan3, "completed", "EUR", "North", "online", 0, 0),
            ("t1", "o-hidden", "c3", jan3, "completed", "USD", "East", "store", 0, 0),
            ("t1", "o-before", "c1", dec31, "completed", "USD", "North", "online", 0, 0),
            ("t1", "o-end", "c1", feb1, "completed", "USD", "North", "online", 0, 0),
            ("t2", "o1", "c1", jan1, "completed", "USD", "North", "online", 0, 0),
        ],
        "order_items": [
            ("t1", "i1", "o1", "p1", 2, 1000, 300),
            ("t1", "i2", "o1", "p2", 1, 800, 0),
            ("t1", "i3", "o2", "p1", 3, 500, 200),
            ("t1", "i4", "o3", "p1", 1, 1000, 0),
            ("t1", "i-cancel", "o-cancel", "p1", 1, 10000, 0),
            ("t1", "i-pending", "o-pending", "p1", 1, 5000, 0),
            ("t1", "i-eur", "o-eur", "p1", 1, 9000, 0),
            ("t1", "i-hidden", "o-hidden", "p1", 1, 7500, 0),
            ("t1", "i-before", "o-before", "p1", 1, 900, 0),
            ("t1", "i-end", "o-end", "p1", 1, 700, 0),
            ("t2", "i1", "o1", "p1", 1, 100000, 0),
        ],
        "payments": [
            ("t1", "pay1", "o1", jan1, "captured", 1100, "USD"),
            ("t1", "pay2", "o1", jan1, "captured", 2350, "USD"),
        ],
        "refunds": [
            ("t1", "r1", "i1", feb15, feb15, "approved", 400, "USD"),
            ("t1", "r2", "i1", feb15, feb15, "approved", 150, "USD"),
            ("t1", "refund-only", "i4", feb15, feb15, "approved", 100, "USD"),
            ("t1", "pending", "i1", jan3, None, "pending", 900, "USD"),
            ("t1", "rejected", "i1", jan3, None, "rejected", 777, "USD"),
            ("t1", "cancel", "i-cancel", feb15, feb15, "approved", 1000, "USD"),
            ("t1", "before", "i-before", feb15, feb15, "approved", 200, "USD"),
            ("t2", "r1", "i1", feb15, feb15, "approved", 5000, "USD"),
        ],
        "returns": [
            ("t1", "ret1", "i1", 1, feb15, mar3, "received"),
            ("t1", "ret2", "i1", 1, feb15, mar3, "received"),
            ("t1", "ret3", "i2", 1, feb15, mar3, "received"),
            ("t1", "return-only", "i3", 1, feb15, mar3, "received"),
            ("t1", "pending", "i4", 1, feb15, None, "pending"),
            ("t1", "rejected", "i4", 1, feb15, None, "rejected"),
            ("t1", "cancel", "i-cancel", 1, feb15, mar3, "received"),
            ("t1", "eur", "i-eur", 1, feb15, mar3, "received"),
            ("t1", "hidden", "i-hidden", 1, feb15, mar3, "received"),
            ("t1", "before", "i-before", 1, jan2, jan3, "received"),
            ("t2", "ret1", "i1", 1, feb15, mar3, "received"),
        ],
    }
    for table in ("orders", "order_items", "payments", "refunds", "returns"):
        rows[table].append(rows[table][0])
    return rows


def write_parity_snapshot(directory: Path, *, returns: str = "received") -> Path:
    """Write literal fixture records, never a production-generated expected answer."""
    if returns not in ("received", "empty", "absent"):
        raise ValueError("Unknown returns fixture mode")
    if returns == "absent" and (directory / "returns.parquet").exists():
        raise ValueError(
            "Legacy fixture destination already has returns; choose an empty directory"
        )
    rows = parity_rows()
    directory.mkdir(parents=True, exist_ok=True)
    schemas = TABLE_SCHEMAS | (OPTIONAL_TABLE_SCHEMAS if returns != "absent" else {})
    if returns == "empty":
        rows["returns"] = []
    with duckdb.connect(":memory:") as connection:
        for table, schema in schemas.items():
            columns = ", ".join(f'"{name}" {kind}' for name, kind in schema)
            connection.execute(f'CREATE TABLE "{table}" ({columns})')
            if rows[table]:
                parameters = ", ".join("?" for _ in schema)
                connection.executemany(f'INSERT INTO "{table}" VALUES ({parameters})', rows[table])
            connection.table(table).write_parquet(str(directory / f"{table}.parquet"))
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare local synthetic and independent parity data."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    generate_retail_data(args.output_dir / "retail-v1", seed=DEFAULT_SEED)
    for version, mode in (
        ("parity-v1", "received"),
        ("parity-legacy-v1", "absent"),
        ("parity-no-returns-v1", "empty"),
    ):
        write_parity_snapshot(args.output_dir / version, returns=mode)
    print(f"Prepared four local datasets under {args.output_dir}; nothing was uploaded.")


if __name__ == "__main__":
    main()
