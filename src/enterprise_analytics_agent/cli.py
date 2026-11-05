"""A trusted local application exercising the semantic boundary."""

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.catalog import METRICS, get_metric
from enterprise_analytics_agent.contracts import (
    AuthorizationContext,
    QueryMetricRequest,
    TimeRange,
)
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, TimeRangeV2
from enterprise_analytics_agent.data import (
    DATA_END,
    DATA_START,
    DEFAULT_SEED,
    DEMO_TENANT,
    REGIONS,
    generate_retail_data,
)
from enterprise_analytics_agent.errors import SemanticError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate fixed-period retail Parquet data and query a governed metric by region."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/retail"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--start", type=date.fromisoformat, default=DATA_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DATA_END)
    parser.add_argument(
        "--metric", choices=[metric.metric_id for metric in METRICS], default="net_revenue"
    )
    parser.add_argument(
        "--api-version",
        choices=("v1", "v2"),
        help="Default: v1 for net_revenue, v2 for other metrics. V2 supports all five metrics.",
    )
    args = parser.parse_args(argv)
    api_version = args.api_version or ("v1" if args.metric == "net_revenue" else "v2")
    request: QueryMetricRequest | QueryMetricRequestV2
    try:
        if api_version == "v1":
            get_metric(args.metric, api_version="v1")
            request = QueryMetricRequest(
                metric_id=args.metric,
                time_range=TimeRange(start=args.start, end=args.end),
                group_by=("region",),
            )
        else:
            request = QueryMetricRequestV2(
                metric_id=args.metric,
                time_range=TimeRangeV2(start=args.start, end=args.end),
                group_by=("region",),
            )
    except (ValidationError, SemanticError) as exc:
        parser.error(str(exc))
    # Only trusted application code constructs authorization; no identity CLI flags.
    context = AuthorizationContext(
        principal_id="local-demo-application",
        tenant_id=DEMO_TENANT,
        allowed_regions=REGIONS,
    )
    try:
        generate_retail_data(args.data_dir, seed=args.seed)
        with DuckDBSemanticAdapter(args.data_dir) as adapter:
            response = adapter.query_metric(request, context=context)
    except (SemanticError, OSError) as exc:
        print(f"analytics-demo: {exc}", file=sys.stderr)
        return 1
    print(response.model_dump_json(indent=2))
    return 0
