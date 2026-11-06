# Enterprise structured-data analytics agent

The repository provides five governed metrics, unchanged v1/v2 contracts, deterministic retail data, and automated verification. Milestone 3 adds an Athena adapter, versioned snapshot publication, and Python CDK data infrastructure. **The user reports successful development deployment and live validation: 66 passed, 458 deselected in 111.94s.** Current hosted-CI confirmation, PR review, and merge remain separate handoff work; this is not a production-readiness claim. The default CLI/tests remain local and require no AWS credentials.

Milestone 2 was merged in PR #1 at `9dc5989` and its hosted CI passed. Bedrock/AgentCore remain milestone 4; Cube is a later separate extension. Neither is implemented here.

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

## Athena development deployment and validation

The user reports `CDKToolkit` and `enterprise-analytics-dev-data-layer` both reached `CREATE_COMPLETE`. The [deployment record](docs/aws-deployment-plan.md) retains the reviewed configuration and commands, IAM scope, cost assumptions, retention, and cleanup. The configured target is profile `analytics-dev`, account `453711491609`, region `us-west-2`, with no implicit default profile. These AWS results were executed by the user and were not rerun during this documentation update. Further AWS changes require explicit authorization.

The CDK app under `infrastructure/cdk` uses explicit configuration and makes no account lookups during synthesis. Install the repository-local CLI when needed; the existing global CLI is too old for the locked library's assembly schema:

```sh
npm ci --prefix infrastructure/cdk/tooling --ignore-scripts
JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache \
  poetry run python -m infrastructure.cdk.app \
  --config infrastructure/cdk/config.development.json --outdir artifacts/cdk.development.out
poetry run python tests/aws_fixture_data.py --output-dir artifacts/aws-datasets
```

These commands prepare local artifacts only. Source snapshots use separate `snapshots/<version>/<table>/` locations. Manifests contain version, seed, inventory, checksums, sizes, schemas, and canonical row counts; identical replays collapse and contradictory records fail validation. An absent returns source remains absent, while an empty typed source remains present. A ready manifest is published only after every file and deployed schema verifies. Athena outputs go to a separate bucket.

`AthenaSemanticAdapter` implements the same four operations as DuckDB and returns only the existing semantic contracts. AWS-specific configuration, encoded execution parameters, query lifecycle, exact numeric conversion, and diagnostics remain internal. Dataset loaders/query executors are separate narrow roles. Tenant/region filtering is application enforcement: direct access to those development roles/storage is **not** Lake Formation row-level security.

Default `poetry run pytest` skips explicitly marked live tests without creating SDK sessions. An intentionally requested live run fails if its configuration is missing. The user executed this live command from the repository root:

```sh
poetry run pytest tests --run-aws --aws-config=infrastructure/cdk/config.development.json -m aws_integration -q
```

The user-reported result was **66 passed, 458 deselected in 111.94 seconds**. The live gate compares **each** adapter with independent literal expectations, including missing/empty returns, original-period adjustments, boundaries, authorization, grouped/ungrouped results, and zero denominators. Query IDs, scanned bytes, timings, dataset/metric versions are written to ignored `artifacts/aws-parity-diagnostics.jsonl`. The cancellation fix and its offline regressions are present in `ae68d2c`; recorded offline checks cover the current code and were not rerun for this documentation update. See [progress](docs/progress.md) for evidence and remaining handoff work.

- [Architecture](docs/architecture.md)
- [Metric definitions and worked example](docs/metric-definitions.md)
- [Implementation plan](docs/implementation-plan.md)
- [Progress and verification](docs/progress.md)
