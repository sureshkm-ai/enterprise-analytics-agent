"""Independent, offline integer-ledger oracle for the retail evaluation.

This is an audit implementation, intentionally independent of the governed adapter,
catalog, generator and production rounding helpers. DuckDB is used only to decode
Parquet rows. All relationships, contributions and aggregates are ordinary Python.
"""

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Self

import duckdb

from enterprise_analytics_agent.contracts_v2 import (
    MetricRowV2,
    QueryMetricRequestV2,
    QueryMetricResponseV2,
)
from enterprise_analytics_agent.retail_evaluation.cases import load_suite
from enterprise_analytics_agent.retail_evaluation.models import GoldenCase, RetailGolden

type SourceRow = dict[str, object]
type SourceTables = Mapping[str, Sequence[Mapping[str, object]]]
type BusinessKey = tuple[str, str]

# The independently transcribed storage specification is deliberately not imported
# from production data/catalog code. Changing it requires a provenance review.
SCHEMAS: dict[str, tuple[tuple[str, str], ...]] = {
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
KEY_FIELDS = {
    "customers": "customer_id",
    "products": "product_id",
    "orders": "order_id",
    "order_items": "order_item_id",
    "payments": "payment_id",
    "refunds": "refund_id",
    "returns": "return_id",
}
_OPTIONAL_FIELDS = {("refunds", "approved_at"), ("returns", "received_at")}


class OracleInputError(ValueError):
    """A source is missing, malformed, conflicting or relationally invalid."""


def _text(row: Mapping[str, object], column: str) -> str:
    value = row[column]
    if not isinstance(value, str):
        raise OracleInputError(f"{column} must be text")
    return value


def _integer(row: Mapping[str, object], column: str) -> int:
    value = row[column]
    if type(value) is not int:
        raise OracleInputError(f"{column} must be an integer")
    return value


def _day(row: Mapping[str, object], column: str) -> date:
    value = row[column]
    if type(value) is not date:
        raise OracleInputError(f"{column} must be a business date")
    return value


def _key(row: Mapping[str, object], field: str) -> BusinessKey:
    return (_text(row, "tenant_id"), _text(row, field))


def _canonical_rows(table: str, rows: Sequence[Mapping[str, object]]) -> tuple[SourceRow, ...]:
    indexed: dict[BusinessKey, SourceRow] = {}
    expected = dict(SCHEMAS[table])
    for original in rows:
        row = dict(original)
        if set(row) != set(expected):
            raise OracleInputError(f"Unexpected columns in {table}")
        for column, kind in expected.items():
            value = row[column]
            if value is None:
                if (table, column) not in _OPTIONAL_FIELDS:
                    raise OracleInputError(f"Null required field {table}.{column}")
                continue
            if kind == "VARCHAR":
                _text(row, column)
            elif kind == "DATE":
                _day(row, column)
            else:
                _integer(row, column)
            if column.endswith("_cents") and _integer(row, column) < 0:
                raise OracleInputError(f"Negative amount {table}.{column}")
        business_key = _key(row, KEY_FIELDS[table])
        if not all(part.strip() for part in business_key):
            raise OracleInputError(f"Blank business key in {table}")
        previous = indexed.get(business_key)
        if previous is not None and previous != row:
            raise OracleInputError(f"Conflicting business key in {table}: {business_key}")
        indexed[business_key] = row
    return tuple(indexed[key] for key in sorted(indexed))


@dataclass(frozen=True)
class ItemContribution:
    """Reviewable merchandise contribution; tax/payment amounts are not operands."""

    tenant_id: str
    order_id: str
    order_item_id: str
    ordered_at: date
    status: str
    currency: str
    region: str
    channel: str
    eligible: bool
    gross_cents: int
    discount_cents: int
    approved_refund_cents: int
    net_cents: int
    approved_refund_ids: str
    received_return_ids: str
    has_received_return: bool


@dataclass(frozen=True)
class _OrderContribution:
    tenant_id: str
    order_id: str
    ordered_at: date
    region: str
    channel: str
    gross_cents: int
    net_cents: int
    has_received_return: bool


class OracleSnapshot:
    """A validated, independently indexed snapshot with no provider clients."""

    def __init__(self, tables: SourceTables) -> None:
        missing = set(SCHEMAS) - {"returns"} - set(tables)
        unknown = set(tables) - set(SCHEMAS)
        if missing or unknown:
            raise OracleInputError(
                f"Invalid source inventory: missing={missing}, unknown={unknown}"
            )
        self._tables = {table: _canonical_rows(table, rows) for table, rows in tables.items()}
        self._indexes = {
            table: {_key(row, KEY_FIELDS[table]): row for row in rows}
            for table, rows in self._tables.items()
        }
        self._validate_relationships_and_values()
        self._items, self._orders = self._build_ledger()

    @classmethod
    def from_rows(cls, tables: SourceTables) -> Self:
        return cls(tables)

    @classmethod
    def from_parquet(cls, directory: Path) -> Self:
        """Decode seven/six explicit files only; no SQL joins/aggregates are used."""
        tables: dict[str, list[SourceRow]] = {}
        with duckdb.connect(":memory:") as connection:
            for table, schema in SCHEMAS.items():
                path = directory / f"{table}.parquet"
                if table == "returns" and not path.exists():
                    continue
                if not path.is_file():
                    raise OracleInputError(f"Missing source: {path.name}")
                relation = connection.read_parquet(str(path))
                actual = tuple(zip(relation.columns, map(str, relation.types), strict=True))
                if actual != schema:
                    raise OracleInputError(f"Unexpected Parquet schema for {table}")
                tables[table] = [
                    dict(zip(relation.columns, values, strict=True))
                    for values in relation.fetchall()
                ]
        return cls(tables)

    @property
    def table_inventory(self) -> dict[str, int]:
        return {table: len(rows) for table, rows in self._tables.items()}

    def contribution_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(asdict(item) for item in self._items)

    def worksheet(self, request: QueryMetricRequestV2) -> tuple[dict[str, object], ...]:
        """Record independently inspectable operands for each reviewed retail cohort."""
        groups: dict[tuple[str, ...], list[ItemContribution]] = defaultdict(list)
        for item in self._items:
            dimensions = {"region": item.region, "channel": item.channel}
            if (
                not item.eligible
                or item.tenant_id != "retail_demo"
                or item.region not in {"North", "South"}
                or not request.time_range.start <= item.ordered_at < request.time_range.end
                or any(
                    dimensions[name] not in values
                    for name, values in request.dimension_filters.items()
                )
            ):
                continue
            groups[tuple(dimensions[name] for name in request.group_by)].append(item)
        if not request.group_by and not groups:
            groups[()] = []
        return tuple(
            {
                "group": dict(zip(request.group_by, key, strict=True)),
                "gross_cents": sum(item.gross_cents for item in items),
                "discount_cents": sum(item.discount_cents for item in items),
                "approved_refund_cents": sum(item.approved_refund_cents for item in items),
                "net_cents": sum(item.net_cents for item in items),
                "order_count": len({item.order_id for item in items}),
                "returned_order_count": len(
                    {item.order_id for item in items if item.has_received_return}
                ),
            }
            for key, items in sorted(groups.items())
        )

    def _validate_relationships_and_values(self) -> None:
        relations = (
            ("orders", "customer_id", "customers"),
            ("order_items", "order_id", "orders"),
            ("order_items", "product_id", "products"),
            ("payments", "order_id", "orders"),
            ("refunds", "order_item_id", "order_items"),
            ("returns", "order_item_id", "order_items"),
        )
        for source, field, target in relations:
            for row in self._tables.get(source, ()):
                if _key(row, field) not in self._indexes[target]:
                    raise OracleInputError(f"Broken tenant-scoped relationship: {source}.{field}")
        for item in self._tables["order_items"]:
            if _integer(item, "quantity") <= 0 or _integer(item, "discount_cents") > (
                _integer(item, "quantity") * _integer(item, "unit_price_cents")
            ):
                raise OracleInputError("Invalid item quantity or discount")
        for refund in self._tables["refunds"]:
            if refund["status"] == "approved" and refund["approved_at"] is None:
                raise OracleInputError("Approved refund requires approval date")
        for event in self._tables.get("returns", ()):
            item = self._indexes["order_items"][_key(event, "order_item_id")]
            if (
                event["status"] not in {"received", "pending", "rejected"}
                or not 0 < _integer(event, "quantity") <= _integer(item, "quantity")
                or (event["status"] == "received" and event["received_at"] is None)
            ):
                raise OracleInputError("Invalid physical return quantity, status or received date")

    def _build_ledger(self) -> tuple[tuple[ItemContribution, ...], tuple[_OrderContribution, ...]]:
        refunds: dict[BusinessKey, list[SourceRow]] = defaultdict(list)
        returns: dict[BusinessKey, list[SourceRow]] = defaultdict(list)
        for refund in self._tables["refunds"]:
            if refund["status"] == "approved" and refund["currency"] == "USD":
                refunds[_key(refund, "order_item_id")].append(refund)
        for event in self._tables.get("returns", ()):
            if event["status"] == "received":
                returns[_key(event, "order_item_id")].append(event)
        items: list[ItemContribution] = []
        orders: dict[BusinessKey, list[ItemContribution]] = defaultdict(list)
        for item in self._tables["order_items"]:
            order_key = _key(item, "order_id")
            order = self._indexes["orders"][order_key]
            item_key = _key(item, "order_item_id")
            gross = _integer(item, "quantity") * _integer(item, "unit_price_cents")
            discount = _integer(item, "discount_cents")
            refund_cents = sum(_integer(row, "amount_cents") for row in refunds[item_key])
            contribution = ItemContribution(
                tenant_id=order_key[0],
                order_id=order_key[1],
                order_item_id=item_key[1],
                ordered_at=_day(order, "ordered_at"),
                status=_text(order, "status"),
                currency=_text(order, "currency"),
                region=_text(order, "region"),
                channel=_text(order, "channel"),
                eligible=order["status"] in {"completed", "shipped"} and order["currency"] == "USD",
                gross_cents=gross,
                discount_cents=discount,
                approved_refund_cents=refund_cents,
                net_cents=gross - discount - refund_cents,
                approved_refund_ids="|".join(_text(row, "refund_id") for row in refunds[item_key]),
                received_return_ids="|".join(_text(row, "return_id") for row in returns[item_key]),
                has_received_return=bool(returns[item_key]),
            )
            items.append(contribution)
            if contribution.eligible:
                orders[order_key].append(contribution)
        order_ledger = tuple(
            _OrderContribution(
                tenant_id=key[0],
                order_id=key[1],
                ordered_at=group[0].ordered_at,
                region=group[0].region,
                channel=group[0].channel,
                gross_cents=sum(item.gross_cents for item in group),
                net_cents=sum(item.net_cents for item in group),
                has_received_return=any(item.has_received_return for item in group),
            )
            for key, group in sorted(orders.items())
        )
        return tuple(items), order_ledger

    def query(
        self,
        request: QueryMetricRequestV2,
        *,
        tenant_id: str,
        allowed_regions: tuple[str, ...],
    ) -> QueryMetricResponseV2:
        """Compute an independently formed request with exact final precision."""
        if (
            not tenant_id.strip()
            or not allowed_regions
            or any(not r.strip() for r in allowed_regions)
        ):
            raise OracleInputError("Trusted tenant and region scope are required")
        if request.metric_id not in {
            "gross_sales",
            "net_revenue",
            "order_count",
            "average_order_value",
            "return_rate",
        }:
            raise OracleInputError("Unsupported oracle metric")
        if (set(request.group_by) | set(request.dimension_filters)) - {"region", "channel"}:
            raise OracleInputError("Unsupported oracle dimension")
        if request.metric_id == "return_rate" and "returns" not in self._tables:
            raise OracleInputError("return_rate requires the physical returns source")
        grouped: dict[tuple[str, ...], list[_OrderContribution]] = defaultdict(list)
        for order in self._orders:
            dimensions = {"region": order.region, "channel": order.channel}
            if (
                order.tenant_id != tenant_id
                or order.region not in allowed_regions
                or not request.time_range.start <= order.ordered_at < request.time_range.end
                or any(
                    dimensions[name] not in values
                    for name, values in request.dimension_filters.items()
                )
            ):
                continue
            grouped[tuple(dimensions[name] for name in request.group_by)].append(order)
        if not request.group_by and not grouped:
            grouped[()] = []
        unit = (
            "count"
            if request.metric_id == "order_count"
            else ("ratio" if request.metric_id == "return_rate" else "currency")
        )
        rows = tuple(
            MetricRowV2(
                dimensions=dict(zip(request.group_by, key, strict=True)),
                value=_aggregate(request.metric_id, orders),
            )
            for key, orders in sorted(grouped.items())
        )
        return QueryMetricResponseV2(
            metric_id=request.metric_id,
            definition_version="1.0.0",
            time_range=request.time_range,
            group_by=request.group_by,
            unit=unit,
            currency="USD" if unit == "currency" else None,
            rows=rows,
        )


def _aggregate(metric_id: str, orders: list[_OrderContribution]) -> Decimal | int | None:
    count = len(orders)
    if metric_id == "order_count":
        return count
    if metric_id in {"average_order_value", "return_rate"} and not count:
        return None
    # Integer source values and counts remain exact before the final division.
    # DECIMAL(38,0) source sums plus an int32 count fit well inside this context.
    with localcontext() as context:
        context.prec = 120
        if metric_id == "return_rate":
            numerator = sum(order.has_received_return for order in orders)
            return (Decimal(numerator) / Decimal(count)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
        cents = sum(
            order.gross_cents if metric_id == "gross_sales" else order.net_cents for order in orders
        )
        denominator = 100 * count if metric_id == "average_order_value" else 100
        return (Decimal(cents) / Decimal(denominator)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


def _json_object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise OracleInputError(f"Expected JSON object: {path.name}")
    return value


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OracleInputError(f"Expected provenance/manifest object: {name}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_local_provenance(
    source_dir: Path, provenance_path: Path
) -> tuple[OracleSnapshot, dict[str, object]]:
    """Recheck downloaded bytes before freezing; this utility makes no AWS calls.

    The acquisition record supplies the version-specific read-only AWS evidence.
    Local verification cannot substitute for that read-only acquisition step.
    """
    provenance = _json_object(provenance_path)
    if (
        provenance.get("provenance_version") != "retail-input-v1"
        or provenance.get("verified") is not True
        or provenance.get("profile") != "analytics-dev"
        or provenance.get("account") != "453711491609"
        or provenance.get("region") != "us-west-2"
        or provenance.get("dataset_version") != "retail-v1"
        or provenance.get("seed") != 20260101
    ):
        raise OracleInputError("Verified retail acquisition provenance is required")
    manifest_path = source_dir / "manifest.json"
    manifest = _json_object(manifest_path)
    manifest_object = _object(provenance.get("manifest"), "manifest")
    if (
        manifest.get("manifest_version") != "v1"
        or manifest.get("state") != "ready"
        or manifest.get("dataset_version") != "retail-v1"
        or manifest.get("seed") != 20260101
        or manifest_object.get("bucket") != "enterprise-analytics-dev-453711491609-us-west-2-data"
        or manifest_object.get("key") != "manifests/retail-v1.json"
        or manifest_object.get("sha256") != _sha256(manifest_path)
        or manifest_object.get("size_bytes") != manifest_path.stat().st_size
        or not manifest_object.get("version_id")
    ):
        raise OracleInputError("Ready manifest bytes/identity do not match provenance")
    manifest_tables = _object(manifest.get("tables"), "tables")
    source_objects = _object(provenance.get("objects"), "objects")
    if set(manifest_tables) != set(SCHEMAS) or set(source_objects) != set(SCHEMAS):
        raise OracleInputError("Retail provenance requires exactly seven source tables")
    for table, schema in SCHEMAS.items():
        entry = _object(manifest_tables[table], table)
        source = _object(source_objects[table], table)
        path = source_dir / f"{table}.parquet"
        expected_key = f"snapshots/retail-v1/{table}/part-00000.parquet"
        if (
            source.get("bucket") != "enterprise-analytics-dev-453711491609-us-west-2-data"
            or source.get("key") != expected_key
            or entry.get("key") != expected_key
            or not source.get("version_id")
            or source.get("sha256") != entry.get("sha256")
            or source.get("sha256") != _sha256(path)
            or source.get("size_bytes") != entry.get("size_bytes")
            or source.get("size_bytes") != path.stat().st_size
            or entry.get("columns") != [{"name": name, "type": kind} for name, kind in schema]
        ):
            raise OracleInputError(f"Canonical source bytes/identity/schema mismatch: {table}")
    snapshot = OracleSnapshot.from_parquet(source_dir)
    for table, row_count in snapshot.table_inventory.items():
        entry = _object(manifest_tables[table], table)
        if entry.get("row_count") != row_count:
            raise OracleInputError(f"Canonical row inventory mismatch: {table}")
    return snapshot, provenance


def freeze_retail_evidence(
    *, source_dir: Path, provenance_path: Path, questions_path: Path, output_dir: Path
) -> RetailGolden:
    """Prepare new review evidence without overwriting previously frozen answers."""
    snapshot, provenance = verify_local_provenance(source_dir, provenance_path)
    suite = load_suite(questions_path)
    manifest_object = _object(provenance["manifest"], "manifest")
    manifest_sha = _text(manifest_object, "sha256")
    golden = RetailGolden(
        manifest_sha256=manifest_sha,
        cases=tuple(
            GoldenCase(
                case_id=case.id,
                results=tuple(
                    snapshot.query(
                        query, tenant_id="retail_demo", allowed_regions=("North", "South")
                    )
                    for query in case.expected_queries
                ),
            )
            for case in suite.cases
        ),
    )
    result_json = golden.model_dump_json(indent=2) + "\n"
    csv_stream = io.StringIO(newline="")
    contributions = snapshot.contribution_rows()
    writer = csv.DictWriter(
        csv_stream, fieldnames=list(contributions[0]) if contributions else [], lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(contributions)
    contribution_csv = csv_stream.getvalue()
    audit_lines = [
        "# Independent retail oracle evidence",
        "",
        "Schema: `retail-oracle-notes-v1`. The input files are exact version-pinned canonical",
        "publication downloads, verified again by byte hash, size, physical schema, row inventory,",
        "required fields, tenant-scoped relationships and duplicate/conflict rules.",
        "These results are independent expected values, not agent/adapter outputs or live results.",
        "No model invocation, Athena query, source regeneration or publication was used.",
        "",
        f"Manifest SHA-256: `{manifest_sha}`; seed `20260101`; tenant `retail_demo`;",
        "authorized regions North/South; reference date `2025-04-01`.",
        "",
        "## Method and review",
        "",
        "`oracle.py` decodes Parquet rows without metric SQL, imports only public contracts and",
        "operator case models, and builds its own dictionaries and integer-cent ledger.",
        "Exact duplicates collapse; conflicting business keys and invalid relationships fail.",
        "Completed/shipped USD orders with items are counted once. Gross minus line discounts",
        "minus approved USD item refunds gives net; tax, shipping and payments are excluded.",
        "Received physical returns flag distinct orders independently of refunds. Event dates",
        "never filter original order-date contributions; the snapshot has no as-of cutoff.",
        "Use aggregate net cents/(100 × aggregate order count) for AOV and returned-order",
        "count/order count for return rate, final HALF_UP at 2/6 places in a local precision-120",
        "Decimal context. Zero denominator is null; empty grouped output has no rows.",
        "",
        "Handwritten fixture proofs establish $53.00 gross, $41.50 net, 3 orders, $13.83 AOV",
        "and 0.666667 returns. AOV tie $0.005 rounds to $0.01; 1/128=.0078125 rounds",
        "to .007813. The tests do not obtain expected values from this utility or production code.",
        "`contributions.csv` retains every canonical item, including excluded scopes/statuses;",
        "`eligible` reflects business status/currency only. Apply tenant/region/date/filter scope",
        "before summing. Multiple item rows must be deduplicated by order ID for both counts.",
        "",
        "The cohort worksheet below records every operand. Currency sums divide cents by 100;",
        "for each ratio divide these aggregate numerators/denominators before final rounding.",
        "Literal goldens remain frozen during evaluation; reviewed changes require a new freeze.",
        "An independent reviewer must inspect selected sums and cohort coverage before",
        "live acceptance; the provenance record captures this implementation/audit evidence.",
        "",
        "## Cohort contribution worksheet",
        "",
        "| Case/query | Metric and group | Gross cents | Discount cents | Approved refund cents |"
        " Net cents | Distinct orders | Distinct received-return orders |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in suite.cases:
        for index, query in enumerate(case.expected_queries, start=1):
            cohorts = snapshot.worksheet(query)
            for cohort in cohorts:
                label = f"{case.id}/{index}"
                group = json.dumps(cohort["group"], sort_keys=True)
                audit_lines.append(
                    f"| {label} | {query.metric_id} {group} | {cohort['gross_cents']} |"
                    f" {cohort['discount_cents']} | {cohort['approved_refund_cents']} |"
                    f" {cohort['net_cents']} | {cohort['order_count']} |"
                    f" {cohort['returned_order_count']} |"
                )
            if not cohorts:
                audit_lines.append(
                    f"| {case.id}/{index} | {query.metric_id}: no groups | — | — | — | — | 0 | 0 |"
                )
    evidence = dict(provenance)
    evidence.update(
        {
            "oracle_version": "retail-oracle-v1",
            "oracle_source_sha256": _sha256(Path(__file__)),
            "questions_sha256": _sha256(questions_path),
            "expected_results_sha256": hashlib.sha256(result_json.encode()).hexdigest(),
            "contributions_sha256": hashlib.sha256(contribution_csv.encode()).hexdigest(),
            "canonical_inventory": snapshot.table_inventory,
            "independent_checks": [
                "schema",
                "required fields",
                "tenant-scoped relationships",
                "duplicate/conflict rules",
                "handwritten fixture arithmetic",
            ],
        }
    )
    # A new directory prevents a command from silently adjusting accepted goldens.
    output_dir.mkdir(parents=True)
    (output_dir / "expected-results.json").write_text(result_json)
    (output_dir / "contributions.csv").write_text(contribution_csv, newline="")
    (output_dir / "oracle-provenance.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (output_dir / "oracle-notes.md").write_text("\n".join(audit_lines) + "\n")
    return golden


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze new independent retail audit evidence offline"
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    golden = freeze_retail_evidence(
        source_dir=args.source_dir,
        provenance_path=args.provenance,
        questions_path=args.questions,
        output_dir=args.output_dir,
    )
    print(f"Prepared {len(golden.cases)} independent case records for review; no AWS calls.")


if __name__ == "__main__":
    main()
