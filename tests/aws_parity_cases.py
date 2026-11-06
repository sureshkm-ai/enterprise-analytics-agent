"""Independent literal expectations; no expected value calls either metric adapter."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, TimeRangeV2

type Value = Decimal | int | None
type ExpectedRow = tuple[dict[str, str], Value]


@dataclass(frozen=True)
class ParityCase:
    name: str
    metric_id: str
    expected: tuple[ExpectedRow, ...]
    dataset_version: str = "parity-v1"
    group_by: tuple[str, ...] = ()
    tenant: str = "t1"
    regions: tuple[str, ...] = ("North", "South")
    start: date = date(2025, 1, 1)
    end: date = date(2025, 2, 1)
    filters: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def request(self) -> QueryMetricRequestV2:
        return QueryMetricRequestV2(
            metric_id=self.metric_id,
            time_range=TimeRangeV2(start=self.start, end=self.end),
            group_by=self.group_by,
            dimension_filters=self.filters,
        )

    def context(self) -> AuthorizationContext:
        return AuthorizationContext(
            principal_id="independent-parity-application",
            tenant_id=self.tenant,
            allowed_regions=self.regions,
        )


# Gross: $28 + $15 + $10; net: $19.50 + $13 + ($10 - $1).
# Counts: three orders. Received returns: A and C, each once.
TOTALS: dict[str, Value] = {
    "gross_sales": Decimal("53.00"),
    "net_revenue": Decimal("41.50"),
    "order_count": 3,
    "average_order_value": Decimal("13.83"),
    "return_rate": Decimal("0.666667"),
}
NORTH: dict[str, Value] = {
    "gross_sales": Decimal("38.00"),
    "net_revenue": Decimal("28.50"),
    "order_count": 2,
    "average_order_value": Decimal("14.25"),
    "return_rate": Decimal("0.500000"),
}
SOUTH: dict[str, Value] = {
    "gross_sales": Decimal("15.00"),
    "net_revenue": Decimal("13.00"),
    "order_count": 1,
    "average_order_value": Decimal("13.00"),
    "return_rate": Decimal("1.000000"),
}
OTHER_TENANT: dict[str, Value] = {
    "gross_sales": Decimal("1000.00"),
    "net_revenue": Decimal("950.00"),
    "order_count": 1,
    "average_order_value": Decimal("950.00"),
    "return_rate": Decimal("1.000000"),
}
JAN1: dict[str, Value] = {
    "gross_sales": Decimal("28.00"),
    "net_revenue": Decimal("19.50"),
    "order_count": 1,
    "average_order_value": Decimal("19.50"),
    "return_rate": Decimal("1.000000"),
}
FEB1: dict[str, Value] = {
    "gross_sales": Decimal("7.00"),
    "net_revenue": Decimal("7.00"),
    "order_count": 1,
    "average_order_value": Decimal("7.00"),
    "return_rate": Decimal("0.000000"),
}
EMPTY: dict[str, Value] = {
    "gross_sales": Decimal("0.00"),
    "net_revenue": Decimal("0.00"),
    "order_count": 0,
    "average_order_value": None,
    "return_rate": None,
}


def cases() -> tuple[ParityCase, ...]:
    result: list[ParityCase] = []
    for metric, total in TOTALS.items():
        result.extend(
            [
                ParityCase(f"{metric}-total", metric, (({}, total),)),
                ParityCase(
                    f"{metric}-grouped",
                    metric,
                    (({"region": "North"}, NORTH[metric]), ({"region": "South"}, SOUTH[metric])),
                    group_by=("region",),
                ),
                ParityCase(
                    f"{metric}-north-scope", metric, (({}, NORTH[metric]),), regions=("North",)
                ),
                ParityCase(f"{metric}-tenant", metric, (({}, OTHER_TENANT[metric]),), tenant="t2"),
                ParityCase(f"{metric}-jan1", metric, (({}, JAN1[metric]),), end=date(2025, 1, 2)),
                ParityCase(
                    f"{metric}-feb1",
                    metric,
                    (({}, FEB1[metric]),),
                    start=date(2025, 2, 1),
                    end=date(2025, 2, 2),
                ),
                ParityCase(
                    f"{metric}-empty",
                    metric,
                    (({}, EMPTY[metric]),),
                    start=date(2030, 1, 1),
                    end=date(2030, 2, 1),
                ),
                ParityCase(
                    f"{metric}-empty-grouped",
                    metric,
                    (),
                    group_by=("region",),
                    start=date(2030, 1, 1),
                    end=date(2030, 2, 1),
                ),
                ParityCase(
                    f"{metric}-unauthorized-region",
                    metric,
                    (),
                    group_by=("region",),
                    regions=("North",),
                    filters={"region": ("South", "East")},
                ),
                ParityCase(
                    f"{metric}-unassigned-tenant",
                    metric,
                    (),
                    group_by=("region",),
                    tenant="unassigned",
                ),
                ParityCase(
                    f"{metric}-filter-encoding",
                    metric,
                    (),
                    group_by=("region",),
                    filters={"region": ("North' OR 1=1 --",)},
                ),
                ParityCase(
                    f"{metric}-empty-returns",
                    metric,
                    (({}, Decimal("0.000000") if metric == "return_rate" else total),),
                    dataset_version="parity-no-returns-v1",
                ),
            ]
        )
        if metric != "return_rate":
            result.append(
                ParityCase(
                    f"{metric}-legacy", metric, (({}, total),), dataset_version="parity-legacy-v1"
                )
            )
    return tuple(result)


PARITY_CASES = cases()
