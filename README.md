# Enterprise structured-data analytics agent

Milestone 2 provides five governed local metrics backed by DuckDB and Parquet, versioned semantic contracts, deterministic retail data, and automated verification. No AWS calls or model calls are made.

The production roadmap is an AWS data layer/Athena adapter with parity tests in milestone 3, then Bedrock and AgentCore in milestone 4. A later Cube adapter will implement the same semantic interface. These integrations are outside the current milestone.

## Run locally

Use Python 3.12 and Poetry 2 in the existing Conda environment. Check that Poetry reports the same environment before running tests:

```sh
conda activate enterprise-analytics
python --version
poetry env info
poetry install --with dev --no-interaction
poetry run analytics-demo --data-dir data/retail
```

The default command still queries v1 `net_revenue` by region. It now writes seven Parquet tables with seed `20260101` and order dates from `2025-01-01` inclusive through `2025-04-01` exclusive. The original six tables are unchanged for a given seed; physical returns use a separate random stream. Re-running the command reproduces logical records. Generated files are ignored by Git.

Choose any metric; new metrics select v2 automatically:

```sh
poetry run analytics-demo --data-dir data/retail --metric gross_sales
poetry run analytics-demo --data-dir data/retail --metric net_revenue
poetry run analytics-demo --data-dir data/retail --metric order_count
poetry run analytics-demo --data-dir data/retail --metric average_order_value
poetry run analytics-demo --data-dir data/retail --metric return_rate
poetry run analytics-demo --data-dir data/retail --metric net_revenue --api-version v2
poetry run analytics-demo --data-dir data/retail --start 2025-02-01 --end 2025-03-01
poetry run analytics-demo --help
poetry check --lock
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests
```

The CLI is a trusted local application and fixes its own demo tenant and authorized regions. Semantic requests cannot supply a principal, tenant, or authorization scope. This is an enforcement boundary demonstration, not a production authentication system.

## Semantic interface

`SemanticAdapter` exposes `discover_metrics`, `describe_metric`, `query_metric`, and `discover_dimensions`; every method receives a separate trusted `AuthorizationContext`. Callers provide a metric identifier, `[start, end)` UTC business dates, governed grouping dimensions, and optional dimension filters. They never provide SQL. Requests reject unknown fields and model-supplied identity.

The models in `contracts.py` preserve v1 net revenue requests/responses and discovery unchanged. The models in `contracts_v2.py` opt into v2 and support all five metrics. V2 envelopes and nested objects carry `api_version: "v2"`. Migrate by choosing the corresponding `*V2` request models and parsing the matching `*V2` response; authorization context remains the same separate application input. Explicit v1 requests for new metrics fail with a version error.

| Metric | Unit | Grain | Result precision |
| --- | --- | --- | --- |
| `gross_sales` | USD currency | order item | 2 decimal places |
| `net_revenue` | USD currency | order item | 2 decimal places |
| `order_count` | count | order | integer |
| `average_order_value` | USD currency | order | 2 decimal places or null |
| `return_rate` | ratio | order | 6 decimal places or null |

Metric and dimension descriptions expose business names and rules. The internal catalog retains execution expressions, source-field mappings, and join keys; these do not appear in semantic response payloads or JSON schemas.

All metrics use completed/shipped USD orders with valid items and trusted tenant/region restrictions. Money is integer cents at rest. Currency and ratio values serialize as exact decimal strings; counts are JSON integers. Nonmonetary v2 results carry `currency: null`. Ratios divide aggregated numerators by aggregated denominators and round only the final result using ROUND_HALF_UP; zero denominators return null. Grouped empty queries return no rows; ungrouped sums/counts return zero.

Refunds and physical returns are independent. Only approved refunds reduce net revenue, and only received physical returns contribute to return rate. Both restate the original order period using the loaded snapshot, with no as-of cutoff. `returns.parquet` is optional for the other four metrics; `return_rate` without it raises `MissingMetricDataError`. An empty, typed returns table produces a zero rate when orders exist. See the metric definitions before interpreting results.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes and pull requests with Python 3.12, SHA-pinned checkout/setup-python actions, pinned Poetry 2.3.1, and `poetry sync --with dev --no-interaction` from the committed lockfile. It runs the same five checks listed above and needs no AWS credentials. GitHub execution begins when the branch is pushed; local verification does not imply a hosted run has occurred.

The workflow follows current official [checkout releases](https://github.com/actions/checkout/releases/tag/v7.0.1), [setup-python documentation](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/README.md), and [Poetry CI guidance](https://python-poetry.org/docs/#ci-recommendations).

- [Architecture](docs/architecture.md)
- [Metric definitions and worked example](docs/metric-definitions.md)
- [Implementation plan](docs/implementation-plan.md)
- [Progress and verification](docs/progress.md)
