# Enterprise structured-data analytics agent

Milestone 1 provides a local, governed semantic interface backed by DuckDB and Parquet. It generates synthetic retail data and queries `net_revenue` by region. No AWS calls or model calls are made.

The intended production agent uses Amazon Bedrock and runs on AgentCore. AWS-native governed metrics through Athena and a later Cube adapter will implement the same semantic contracts; they are future work.

## Run locally

Use Python 3.12 and Poetry 2 in your activated environment:

```sh
poetry install
poetry run analytics-demo --data-dir data/retail
```

The command writes six Parquet tables with seed `20260101` and order dates from `2025-01-01` inclusive through `2025-04-01` exclusive, then prints a versioned JSON response for net revenue by region. A later approved refund can restate revenue in this original-order period. Re-running with the same seed produces identical logical records. Generated files are ignored by Git.

```sh
poetry run analytics-demo --data-dir data/retail --start 2025-02-01 --end 2025-03-01
poetry run analytics-demo --help
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests
```

The CLI is a trusted local application and fixes its own demo tenant and authorized regions. Semantic requests cannot supply a principal, tenant, or authorization scope. This is an enforcement boundary demonstration, not a production authentication system.

## Semantic interface

All requests and responses carry `api_version: "v1"`, reject unknown fields, and use Pydantic v2. `SemanticAdapter` exposes `discover_metrics`, `describe_metric`, `query_metric`, and `discover_dimensions`; every method receives a separate `AuthorizationContext`. Callers provide a metric identifier, a date range, governed grouping dimensions, and optional dimension filters. They never provide SQL.

Metric and dimension descriptions expose business names and rules. The internal catalog retains execution expressions, source-field mappings, and join keys; these do not appear in semantic response payloads or JSON schemas.

`net_revenue` sums eligible merchandise sales less line discounts and approved item refunds. Money is stored as integer cents and returned as exact decimal USD strings. Grouped queries with no contributing orders return no rows; ungrouped queries return zero. See the documented assumptions before interpreting results.

- [Architecture](docs/architecture.md)
- [Metric definitions and worked example](docs/metric-definitions.md)
- [Implementation plan](docs/implementation-plan.md)
- [Progress and verification](docs/progress.md)
