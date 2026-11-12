# Enterprise structured-data analytics agent

**Milestones 1–5 are complete for the agreed development proof of concept.** Further development requires a separately defined scope; this is not a production-readiness claim.

The repository provides five governed metrics, unchanged v1/v2 contracts, deterministic retail data, DuckDB/Athena adapters, and automated verification. Milestone 3 is merged and its hosted CI passed; the user's AWS parity result was **66 passed, 458 deselected in 111.94s**. Milestone 4 adds a bounded Bedrock Converse agent hosted on AgentCore Runtime. **Milestone 4 is implemented, deployed, live-validated, merged into main and verified by hosted CI for the agreed development scope.** [PR #4](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/4) merged on November 8, 2026. Recorded live acceptance remains 18 + 3 + 3 tests plus warm-up, 28/40 invocations, corrected parity-v1 restored and Runtime/DEFAULT READY on version 4, with the runtime stack UPDATE_COMPLETE. The default CLI/tests remain local and require no AWS credentials.

Milestone 3 merged in [PR #2](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/2) at `ae378e4`, with [successful hosted CI](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42166641840); the merge-status documentation followed in PR #3 at `6bf1220`. Milestone 4 subsequently merged through PR #4; its merge and CI evidence are recorded below. Cube, a UI, and additional AgentCore services remain outside milestone 4.

The separately approved shared UI merged through [PR #8](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/8) on November 11, 2026, at `e22287538e22e1917eb2a21efbeadc4cec5c6d75`. Full-live validation merged through [PR #9](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/9) at `1dfd788a9b773fbf8abd39a554033cccd683c4ee` that day. [Main CI 43100659276](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43100659276) passed for that merge: 1,570 offline tests, zero skips, plus lockfile, lint, formatting, types and offline synthesis. The 85 live items were verified separately during approved execution.

## Run locally

For the new **Analytics Workbench** browser UI, run this from the repository root
after installing the existing Poetry environment:

```sh
poetry run python -m enterprise_analytics_agent.ui
```

Open **http://127.0.0.1:8501**. The professional local interface includes
three explicit modes, suggested questions, exact result tables, execution details,
a metric catalog, saved-run viewer and code guide. **Offline playground** uses a
deterministic planner and temporary DuckDB samples with no AWS sessions. **Local
agent** uses the existing BedrockAnalyticsAgent with canonical DuckDB data and makes
billable Bedrock calls. **AWS AgentCore** uses the same agent with Athena. Both
billable modes require a separately approved release/allowance and show cost notices
before submission. Approved live acceptance on November 11, 2026, passed Q18
(**110.25 USD** for March 31 inclusive to April 1 exclusive) and **all 18 paired UI
outcomes** against independent goldens. That UI acceptance window verified the frozen
candidate/retail release on Runtime/DEFAULT **READY v13**, stack **UPDATE_COMPLETE**.
Later full-live validation restored the same candidate/retail configuration on v15.
This establishes the tested behavior for the nine reviewed questions, not identical
model prose or general production equivalence. See [UI setup](docs/local-ui.md)
and [shared-code acceptance evidence](docs/ui-shared-code-live.md).
This follow-on UI scope does not change completed M1–M5 acceptance or their ledgers.

Submitting a question clears the text box immediately. The accepted Nova release
streams truthful progress and returns its validated final answer; its frozen AWS
runtime remains JSON-based. The separate **local implementation** now adds actual
provider word streaming and a Bedrock-only model catalog: Anthropic Claude, OpenAI
GPT through Bedrock, Google **Gemma through Bedrock Mantle**, Meta Llama, DeepSeek,
Qwen and Mistral, plus Nova. Additional choices stay disabled until the separate
release is deployed and accepted. Directory-policy/model prerequisites are now
verified; one new Nova stack was created, but policy-shape verification and a
workload logging denial stopped that attempt. The user approved the
[scoped recovery](docs/bedrock-streaming-recovery-plan.md) at **7dad05a**. Fresh
preflight passed, the reviewed unused Nova stack was deleted, and all ten corrected
stacks verified **CREATE_COMPLETE / Runtime and DEFAULT READY v1**, with exact
artifact/configuration/policy proofs and seven-day retention. Administrator trust
application/readback and actual release binding passed. Nova Q18 passed with
provider streaming, but the all-five question failed an input-reservation guard
after producing the correct requests/results. Acceptance stopped; new choices
remain disabled. Protected legacy v15 cleanup passed, and the campaign is closed
**3/40**. The [focused completion correction and replacement](docs/bedrock-streaming-completion-plan.md)
are now implemented and offline-verified, with fresh read-only preflight passed.
The replacement is not uploaded/deployed or live-accepted. Parent **3/40** is
closed; the separate proposed child is **0/37**, aggregate **3/40**. Execution
approval is required before the new package or model choices are enabled.

The new streaming runner reuses the unchanged semantic agent loop with at most
five planning calls and one tool-free presentation call. It releases actual
provider words only while they exactly match the canonical answer from validated
semantic results, keeping amounts, units, dates and private reasoning safe. A
rejected stream is labeled and is never retried or replaced with a typing animation.
The [deployment and live-evaluation proposal](docs/bedrock-multimodel-streaming-plan.md)
covers ten new isolated runtimes/roles, a new artifact and a separate approved
40-attempt outer ceiling, including an unavailable reserve. The
[administrator steps](docs/bedrock-streaming-administrator-steps.md) record completed
policy evidence and completed query-trust handoff. New model acceptance is
**incomplete**; the retained legacy **v15** passed cleanup verification and remains
the accepted release. Do not replay the closed campaign or reuse its remaining
quota/reserve.

The separate UI campaign used **19/20 attempts**: Q18 verification 1 and all 18
regular slots; the protected rollback smoke was unused. No regular live allowance
remains, and the completed review cannot restart billable mode. Additional billable
questions cannot reuse that completed review. The user approved [interactive session 02](docs/ui-interactive-session-02.md) at `319a872`; its launch enables Local agent and AWS AgentCore with Nova Lite at **http://127.0.0.1:8501**. Its counted Q18 verification passed **110.25 USD [2025-03-31,2025-04-01)** after a fresh **READY v15** proof at **21:52:13Z** on November 11, 2026. At activation, usage was **1 verification / 1 Runtime invocation / 0 ordinary questions / 0 direct local Converse calls**, leaving **18 user-owned questions across both modes** until **2026-11-13T23:59Z**. A later local ledger inspection found **2/20 used and 17 regular questions remaining**; read that persistent counter for subsequent usage. The protected original-rollback slot stays unavailable. This streaming preparation does not spend or expand that Nova allowance, update v15 or alter its historical artifacts. See the session plan for the exact restart command; restarting does not reset its counter. Inspect the saved historical AWS acceptance responses offline without spending another call:

```sh
conda activate enterprise-analytics
poetry run python -m enterprise_analytics_agent.ui \
  --report artifacts/ui-shared/replay-aws-agentcore.json --port 8501
```

This derived report is explicitly replayed evidence, not fresh agent execution.
It is retained in the original checkout; generated reports are not included in a
fresh clone. The default launch above remains fully offline.

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

Default pytest and CI explicitly select offline tests and fail if any selected test
skips. The 85 live items are separately selected for approved execution; deselection
does not mean they passed. The [full-live validation plan](docs/full-live-validation-plan.md)
stages all 66 Athena, 18 AgentCore and one 36-request retail campaign test. The approved
run and [corrected continuation](docs/full-live-continuation-proposal.md) completed on
November 11, 2026: **1,570 offline + all 85 live items passed, zero skipped**; all 36
retail requests and protected restoration smoke passed too. Accepted candidate-retail
Runtime/DEFAULT were restored and finally verified **READY v15**, stack UPDATE_COMPLETE.
Usage is **20/20 continuation, 57/57 aggregate Runtime calls**; no allowance remains.
See the [acceptance evidence](evaluations/full-live/acceptance-2026-11-11.json).
The earlier UI acceptance and every historical ledger remain unchanged. This implementation
and its evidence are merged through PR #9 with successful main CI, while the live
results remain separate from the AWS-free hosted checks.

The CLI is a trusted local application and fixes its own demo tenant and authorized regions. Semantic requests cannot supply a principal, tenant, or authorization scope. This is an enforcement boundary demonstration, not a production authentication system.

## Retail demonstration and evaluation

**Milestone 5 is implemented, live-validated, merged into main and verified by hosted CI for the agreed development proof of concept.** [PR #6](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/6) merged November 10, 2026, at [`c0d2c5a`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/c0d2c5a569e2d242bf840a715c31050888b579ab), containing completion [`7905d13`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/7905d13f59e13d0b5a1b11231348721471a19411); [main CI 42872516193](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42872516193) passed for that exact merge. The approved `q18-recovery-v1` passed the Q18 probe/warm-up (**110.25 USD**, March 31 inclusive to April 1 exclusive), **all 36 frozen suite requests**, diagnostics/latency/authorization/session gates and mandatory original-restoration smoke. Candidate Runtime/DEFAULT were READY **v11**; the recorded original parity-v1 restoration checkpoint is **Runtime/DEFAULT READY v12**, runtime stack UPDATE_COMPLETE. Suite client p95 was **13.381s** against the unchanged 90s threshold. See [recovery results](docs/milestone-5-q18-recovery-proposal.md) and [progress](docs/progress.md) for reports, exact pins and verification.

The recovery used **38/38** calls (probe 1 + suite 36 + smoke 1), exhausting aggregate repair **40/40** including two historical smoke calls. No invocation retries, failures or incomplete reservations occurred. Historical M5 **35/36 / closed 38/40**, repair **closed 1/40**, continuation **closed 1/39**, and M4 **28/40** evidence remain unchanged. Do not rerun any closed campaign or borrow/reset quota. No new deployment or invocation is authorized by this documentation.

Reviewed checkpoint `f2238775e724630af14bcc0c14ac4cdc150f821c` passed [push CI 42861036450](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42861036450) and [PR CI 42861051831](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42861051831); these cover preparation, not the later outcome-documentation commit. Published retail inputs, independent expectations and contribution worksheets remain frozen in [evaluations/retail-v1](evaluations/retail-v1/oracle-notes.md). No production-readiness claim is made.

```sh
poetry install --only-root --no-interaction
poetry run analytics-ask --help
poetry run analytics-evaluate --help
poetry run analytics-ask --response-file path/to/saved-agent-response.json --format json
poetry run analytics-evaluate --target-config evaluations/retail-v1/target.json \
  --response-dir path/to/saved-responses --report-dir artifacts/milestone-5/runs/replay-unique
```

Replay does not construct AWS clients. Question answers display exact values, units, periods, metric/dataset versions and diagnostics; exit codes are 0 for answers, 2 for clarification and 1 for errors. The evaluator grades complete structured plans/results, clarification and isolation, and writes JSON, durable attempt JSONL and Markdown reports. Missing diagnostics remain missing. Replay demonstrates tooling behavior and makes no live-quality claim.

The [operator runbook](docs/milestone-5-runbook.md) records the first environment-only retail campaign and corrected-base restoration. The existing ZIP/version is reused; only dataset `retail-v1`, tenant `retail_demo` and reference date `2025-04-01` change in trusted configuration. The operational endpoint is restored to the corrected parity base after this campaign. The approved M5 campaign used 38/40 calls: warm-up 1, suite 36, restored smoke 1. Q18 returned clarification instead of yesterday's 110.25 USD. At that historical checkpoint, corrected parity-v1 was restored, Runtime/DEFAULT were READY v6 and the stack was UPDATE_COMPLETE; both policies, seven-day retention, artifact/version and retained infrastructure verify. M4 remains 28/40. The M5 ledger is retail-closed; do not replay the campaign or reset either ledger. Live CLI/pytest gates require approval, and calls share the persistent counter. See [the plan](docs/milestone-5-plan.md) for acceptance criteria.

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

`.github/workflows/ci.yml` runs on pushes and pull requests with Python 3.12, SHA-pinned checkout/setup-python actions, pinned Poetry 2.3.1, and `poetry sync --with dev --no-interaction` from the committed lockfile. It runs the five checks above and offline data-layer/AgentCore foundation synthesis without AWS credentials. The user confirmed successful [hosted CI run 42279109681](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42279109681) for pushed readiness commit `5e72b51`. Completion commit [`51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf) passed [push CI 42515746487](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515746487) and [PR CI 42515722610](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515722610). [PR #4](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/4) merged it into main at [`47c3afc1dd948fa8ddcb074151b9f22af31dad48`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/47c3afc1dd948fa8ddcb074151b9f22af31dad48), which passed [main CI 42516820774](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42516820774). These M4 runs cover their named commits. The separate M5 push result above covers `e6f4325`, not the subsequent serialization correction. Historical checkpoint evidence remains in [progress](docs/progress.md).

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

The build downloads only checksum-locked Linux ARM64 wheels from the package index and writes local ignored artifacts; `--offline` reuses them. Runtime synthesis requires the actual archive SHA recorded in the deployment configuration. Explicit deployed-agent evaluations require both flags below, a real reviewed runtime ARN, and approval; default tests explicitly exclude them without creating AWS clients:

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

Default `poetry run pytest` explicitly selects offline tests without creating SDK sessions; selected skips fail verification. An intentionally requested live run fails if its configuration is missing. The user executed this live command from the repository root:

```sh
poetry run pytest tests --run-aws --aws-config=infrastructure/cdk/config.development.json -m aws_integration -q
```

The user-reported result was **66 passed, 458 deselected in 111.94 seconds**. The live gate compares **each** adapter with independent literal expectations, including missing/empty returns, original-period adjustments, boundaries, authorization, grouped/ungrouped results, and zero denominators. Query IDs, scanned bytes, timings, dataset/metric versions are written to ignored `artifacts/aws-parity-diagnostics.jsonl`. The cancellation fix and its offline regressions are present in `ae68d2c`; recorded offline checks cover the current code and were not rerun for this documentation update. See [progress](docs/progress.md) for evidence and remaining handoff work.

- [Architecture](docs/architecture.md)
- [Metric definitions and worked example](docs/metric-definitions.md)
- [Implementation plan](docs/implementation-plan.md)
- [Progress and verification](docs/progress.md)
