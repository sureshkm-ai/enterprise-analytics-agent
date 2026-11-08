# Enterprise structured-data analytics agent

The repository provides five governed metrics, unchanged v1/v2 contracts, deterministic retail data, DuckDB/Athena adapters, and automated verification. Milestone 3 is merged and its hosted CI passed; the user's AWS parity result was **66 passed, 458 deselected in 111.94s**. Milestone 4 adds a bounded Bedrock Converse agent hosted on AgentCore Runtime. **Milestone 4 is implemented, deployed, live-validated, merged into main and verified by hosted CI for the agreed development scope.** [PR #4](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/4) merged on November 8, 2026. Recorded live acceptance remains 18 + 3 + 3 tests plus warm-up, 28/40 invocations, corrected parity-v1 restored and Runtime/DEFAULT READY on version 4, with the runtime stack UPDATE_COMPLETE. The default CLI/tests remain local and require no AWS credentials.

Milestone 3 merged in [PR #2](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/2) at `ae378e4`, with [successful hosted CI](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42166641840); the merge-status documentation followed in PR #3 at `6bf1220`. Milestone 4 subsequently merged through PR #4; its merge and CI evidence are recorded below. Cube, a UI, and additional AgentCore services remain outside milestone 4.

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

`.github/workflows/ci.yml` runs on pushes and pull requests with Python 3.12, SHA-pinned checkout/setup-python actions, pinned Poetry 2.3.1, and `poetry sync --with dev --no-interaction` from the committed lockfile. It runs the five checks above and offline data-layer/AgentCore foundation synthesis without AWS credentials. The user confirmed successful [hosted CI run 42279109681](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42279109681) for pushed readiness commit `5e72b51`. Completion commit [`51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf) passed [push CI 42515746487](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515746487) and [PR CI 42515722610](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515722610). [PR #4](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/4) merged it into main at [`47c3afc1dd948fa8ddcb074151b9f22af31dad48`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/47c3afc1dd948fa8ddcb074151b9f22af31dad48), which passed [main CI 42516820774](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42516820774). These runs cover those earlier commits; they do not cover this new documentation-only commit. Historical checkpoint evidence remains in [progress](docs/progress.md).

The workflow follows current official [checkout releases](https://github.com/actions/checkout/releases/tag/v7.0.1), [setup-python documentation](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/README.md), and [Poetry CI guidance](https://python-poetry.org/docs/#ci-recommendations).

## Bedrock agent and AgentCore development runtime

`BedrockAnalyticsAgent` uses an injected Converse client and exposes exactly the four semantic operations through existing v2 Pydantic contracts. It handles matching tool-result IDs, multiple tools, invalid arguments, model/tool failures, and iteration/time/token limits. Every request starts fresh. Final numeric answers are rendered from validated tool results, preserving decimal strings, units, nulls, groups, `[start,end)` boundaries, metric definition versions, and dataset version. Generated model numbers are discarded.

The development question vocabulary is deliberately conservative: governed metric IDs/names; a named month and year, an explicit `[YYYY-MM-DD, YYYY-MM-DD)` period, last month, or yesterday; and supported region/channel grouping and filters. Ambiguous metrics, periods, comparisons, and unsupported calculation requests ask for clarification. Every clause must fit this development vocabulary: unknown measures/dimensions and unresolved date refinements require clarification. Filters support alternatives within one dimension and conjunction across dimensions; region OR channel cannot be substituted with AND. Relative periods use a server-configured reference date, currently `2025-02-01` for fixed acceptance data.

The deployed development runtime uses a Python 3.12 Linux ARM64 ZIP, built from Poetry's locked main dependencies and verified wheel hashes. A standard HTTP entry point serves `/ping` and `/invocations`; no additional agent framework or packaging lockfile replaces Poetry. Invocation payloads contain only `{"question": "..."}`. AgentCore SigV4/resource policies restrict approved callers, and all callers of this development endpoint share server-owned tenant `t1`, regions North/South. This is a fixed development scope, not per-user production authorization. The runtime uses workload credentials and a refreshed assumption of the existing Athena query role; no local profile or SSO credentials are packaged.

Read the [AgentCore deployment and live-test plan](docs/agentcore-deployment-plan.md) before any AWS mutation or model call. It records the selected Nova Lite profile and its three US routing regions, scoped IAM/trust changes, code packaging, two deployment phases, evaluation commands, costs, and cleanup. Acceptance passed on the three published parity snapshots; the corrected base is restored on Runtime/DEFAULT version 4. Full results and retained artifact/version evidence are in [progress](docs/progress.md). Read-only checks also verified `retail-v1` readiness, schemas, and object checksums before any future retail demonstrations.

Offline verification/build commands:

```sh
poetry run pytest tests/test_agent.py tests/test_agent_limits.py tests/test_runtime_hosting.py tests/test_agentcore_packaging.py tests/test_agentcore_cdk.py tests/test_agent_evaluation.py
poetry run python -m infrastructure.agentcore.package --config infrastructure/agentcore/runtime.development.json
JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache \
  poetry run python -m infrastructure.cdk.agentcore_app \
  --config infrastructure/cdk/agentcore.config.development.json --outdir artifacts/cdk.agentcore.out
```

The build downloads only checksum-locked Linux ARM64 wheels from the package index and writes local ignored artifacts; `--offline` reuses them. Runtime synthesis requires the actual archive SHA recorded in the deployment configuration. Explicit deployed-agent evaluations require both flags below, a real reviewed runtime ARN, and approval; default tests skip them without creating AWS clients:

```sh
poetry run pytest tests --run-agent-live --agent-config=artifacts/agentcore/live.parity-v1.json -m agent_live -q
```

Evaluation judges inspect selected tools, validated arguments, dates/filters, exact values, versions, errors, and request/session isolation rather than exact prose. Evidence includes model configuration, token usage, latency, semantic calls, and Athena execution diagnostics. Skips and fake-client tests do not establish deployed acceptance.

## Athena development deployment and validation

The user reports `CDKToolkit` and `enterprise-analytics-dev-data-layer` both reached `CREATE_COMPLETE`. The [deployment record](docs/aws-deployment-plan.md) retains the reviewed configuration and commands, IAM scope, cost assumptions, retention, and cleanup. The configured target is profile `analytics-dev`, account `453711491609`, region `us-west-2`, with no implicit default profile. Milestone 4 preparation did not repeat its deployment or live parity; read-only checks reverified the stack outputs and all four ready snapshots. Further AWS changes require explicit authorization.

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
