# Analytics Workbench

The Workbench provides three explicit execution modes and offline saved-report viewing
for the separately requested UI scope after milestones 1–5. The default **Offline
playground** creates no AWS session. **Local agent** uses the existing
`BedrockAnalyticsAgent` with DuckDB and makes billable Bedrock calls. **AWS AgentCore**
uses that agent with Athena after the matching reviewed release is deployed and verified.
The catalog, v2 contracts, question guard and semantic tools remain shared.

![Analytics Workbench with three explicit execution modes](images/analytics-workbench-shared-ui.png)

## Start the offline playground

From the repository root, use the existing environment:

```sh
conda activate enterprise-analytics
poetry run python -m enterprise_analytics_agent.ui
```

Open **http://127.0.0.1:8501**. If occupied, add `--port 8502` and use the printed URL.
Stop with Ctrl+C. No frontend build, Node installation, extra dependency, credentials
or database setup is needed. Merely opening the application, switching modes, browsing
the catalog or viewing a saved report sends no model or Runtime request.

The playground creates temporary Parquet using the existing fixed-seed generator.
The existing question guard produces validated requests; DuckDB computes the values.
Its planner is deterministic, and its generated samples are not the canonical retail
publication. The trusted scope is `retail_demo`, North/South, with reference date
`2025-04-01`. Unsupported intent receives clarification. History buttons redisplay
answers without supplying conversation history to another question.

Try these in the offline playground:

| Question | What it exercises |
| --- | --- |
| Show net_revenue for January 2025 by region. | Exact currency and regional grouping |
| Show gross_sales and net_revenue for January 2025 by region. | Multiple metrics |
| Show order_count for January 2025 by region and channel. | Count grain and two dimensions |
| Show average_order_value for March 2025 by channel. | Aggregate ratio and rounding |
| Show return_rate for January 2025 by region. | Physical returns versus refunds |
| Show net_revenue for yesterday. | March 31, 2025, from the fixed reference date |
| List available metrics. | Governed discovery |
| Describe average_order_value. | Metric definition |
| List dimensions for net_revenue. | Scoped dimension discovery |

**Results / Execution / JSON** expose the validated response. Money remains exact
decimal strings; JavaScript does not calculate metric values. Rates are fractions,
null ratios remain distinct from zero, and absent diagnostics are labeled unreported.

## Understand the modes and current deployment

| Mode | Data and reference date | Execution and cost |
| --- | --- | --- |
| Offline playground | Temporary `local-sample-seed-20260101`; `2025-04-01` | Deterministic planner, real DuckDB, no AWS/model calls |
| Local agent | Verified canonical `retail-v1`, `retail_demo`, North/South; `2025-04-01` | Shared Bedrock agent with DuckDB; billable, at most six Converse attempts per question |
| AWS AgentCore, shared release | Same reviewed retail scope/model/limits as local agent | Shared Bedrock agent with Athena; one Runtime attempt per question, no invocation retries |
| Saved runs | Whatever the saved file records | Offline typed inspection, no new execution or acceptance |

The two agent modes are disabled by default. Local agent execution is **not offline
model execution**: its button and mode notice disclose Bedrock usage before submission.

Fresh read-only checks on November 10, 2026, found the existing original/parity
Runtime and DEFAULT **READY v12**. Its original artifact differs from the local Q18
correction in `bedrock_agent.py` and `agent/questions.py`. It is not the proposed shared
retail release. The accepted frozen candidate matches all **25** audited shared source
files; it can be reused without rebuilding or uploading a ZIP. Its dependency/build,
configuration, artifact and canonical-data evidence are recorded in
[the shared-code proposal](ui-shared-code-live.md). This source comparison alone does
not prove that AWS currently executes the candidate or establish new live parity.

Read-only publication verification also checked all eight current object identities,
seven exclusive source prefixes and seven actual Glue schemas/locations. The retained
proof is `artifacts/ui-shared/preflight/20261110T212343Z/publication-proof.json`.
Every candidate deployment preflight and new shared question repeats these bounded
checks; drift blocks execution before reserving a question.

The shared deployment and live comparison remain **pending separate execution
approval**. Direct developer Bedrock access and the runtime candidate-key read grant
still need administrator evidence; denied inspection is not proof that
those permissions are absent. No new live question, deployment, upload or IAM change
has been performed for this UI preparation. Historical ledgers remain unchanged.

## Inspect saved acceptance without new calls

Choose **Saved runs → Choose JSON file** and select a retained `report.json` or a
downloaded AgentResponse JSON. Files go only to the loopback application, are validated,
and are not persisted by the upload route. Refreshing clears uploaded report state.
This viewer preserves recorded verdicts; it does not rejudge acceptance or infer
success from a filename. The upload limit is 16 MiB / 200 cases.

For the retained M5 report in the original checkout:

```sh
poetry run python -m enterprise_analytics_agent.ui \
  --report artifacts/milestone-5/q18-recovery-v1/operations/20261110T173634Z/live/suite/report.json
```

Ignored reports and frozen artifacts are unavailable in a fresh clone. Do not fabricate
or regenerate historical evidence to fill the view.

## Shared-release operator workflow

The concrete proposed resources, permission prerequisites, nine paired questions,
expiry, cost limits and rollback gates are in
[shared code and live testing](ui-shared-code-live.md). Its proposed review is
`evaluations/ui-shared/review.proposed.json`: **20 total question attempts**, comprising
**18 regular attempts + one protected Q18 verification + one protected original rollback
smoke**, expiring **2026-11-11T23:59:00Z**. Both agent modes share that allowance.
The historical M4/M5/repair/continuation/recovery counters cannot fund these calls.
The new proposal remains unconsumed; neither the file nor an enabling flag is approval.

`infrastructure.agentcore.ui_workflow` prepares/reviews existing assemblies and manages
bounded deployment reconciliation. It never invokes a model. Offline preparation
already created `artifacts/ui-shared/deployment/{candidate,rollback}` and its hashed
`assembly-review.json`; preserve that directory. For a separate offline reproduction,
choose an unused output directory:

```sh
poetry run python -m infrastructure.agentcore.ui_workflow prepare \
  --review evaluations/ui-shared/review.proposed.json \
  --output artifacts/ui-shared/deployment-recheck
```

The read-only preflight uses only `analytics-dev`, account `453711491609`, region
`us-west-2`, and writes new evidence without changing AWS resources:

```sh
poetry run python -m infrastructure.agentcore.ui_workflow preflight \
  --review evaluations/ui-shared/review.proposed.json --kind original \
  --output artifacts/ui-shared/preflight/fresh-original.json
```

**The following deployment and counted execution commands require approval of the
concrete proposal first. They have not been executed during preparation.** Output
paths are write-once and must be unused. Do not change campaign IDs or delete evidence
to bypass an existing reservation, failed run or unresolved process journal.

```sh
poetry run python -m infrastructure.agentcore.ui_workflow deploy \
  --review evaluations/ui-shared/review.proposed.json \
  --prepared-dir artifacts/ui-shared/deployment \
  --output artifacts/ui-shared/operations/approved-deploy \
  --execute-approved

poetry run python -m enterprise_analytics_agent.adapters.ui_shared \
  --purpose verification --invoke-live \
  --review evaluations/ui-shared/review.proposed.json \
  --release-record artifacts/ui-shared/operations/approved-deploy/release-record.json \
  --output artifacts/ui-shared/verification.json
```

Deployment binds the actual resulting version rather than assuming v13. It reconciles
CloudFormation template/parameters and full Runtime/DEFAULT artifact, configuration,
policies and readiness; READY alone is insufficient. Success leaves the shared candidate
deployed. The protected verifier fixes its own question to **“Show net_revenue for
yesterday.”** and requires the complete independent Q18 request/result: **110.25 USD**
for **[2025-03-31, 2025-04-01)**. Normal shared questions remain disabled until it passes.

After successful counted verification, launch both shared agent modes:

```sh
poetry run python -m enterprise_analytics_agent.ui \
  --allow-live \
  --shared-review evaluations/ui-shared/review.proposed.json \
  --release-record artifacts/ui-shared/operations/approved-deploy/release-record.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1
```

There is no automatic question on startup or mode selection. Browser payloads contain
only question, routing mode and deduplication ID. They cannot set profile, model,
authorization, SQL, history, reference date, runtime configuration or protected purpose.
AgentCore receives the existing question-only `AgentRequest`. Local authorization is
server-created; deployed authorization comes from trusted Runtime configuration.

Each new question verifies source/data/release, then durably reserves before dispatch.
The separate SDK journal counts local Converse attempts and Runtime invocations.
Failures and unknown outcomes stay spent and stop regular execution; no automatic
SDK invocation retry or reservation refund occurs. Successful duplicate IDs replay
saved results. **Clear workspace** affects only the browser display.

Evidence is under `artifacts/ui-shared/<campaign_id>/`: `invocations.jsonl`, exclusive
`reservations/`, `sdk-attempts.jsonl` and SDK receipts, `operator-reads.jsonl`, per-request
preflight JSON and protected verification output. Preserve the review hash binding,
all evidence and the existing operator/deployment guards across restarts.

## Failure, expiry and original rollback

A failed candidate deployment triggers the operator's mandatory original restoration
when process guards allow. A failed Q18 or paired-comparison gate requires explicit
original restoration and the protected smoke under the approved procedure:

```sh
poetry run python -m infrastructure.agentcore.ui_workflow restore \
  --review evaluations/ui-shared/review.proposed.json \
  --prepared-dir artifacts/ui-shared/deployment \
  --output artifacts/ui-shared/operations/approved-rollback \
  --execute-approved

poetry run python -m enterprise_analytics_agent.adapters.ui_shared \
  --purpose rollback_smoke --invoke-live \
  --review evaluations/ui-shared/review.proposed.json \
  --release-record artifacts/ui-shared/operations/approved-rollback/rollback-record.json \
  --output artifacts/ui-shared/rollback-smoke.json
```

The smoke checks original parity North **28.50 USD** / South **13.00 USD**. Restoration
binds its actual resulting version, preserves the frozen original artifact/version and
disables shared UI execution. It does not claim that the original matches local Q18 code.
Inspect retained controller/process diagnostics before restoring after interruption;
never overlap deployments or bypass an unresolved journal. Retain primary and rollback
failures separately. Expiry blocks new billable calls, including a smoke; nonbillable
original cleanup remains available. If a required smoke cannot run within approval,
record that gap and obtain a new decision rather than resetting the allowance.

## Legacy original-v12 UI path

The initial UI implementation used the existing original/parity v12 deployment. This
remains a separate **legacy** option; it does not establish shared-code equivalence.
Its `local-ui-live-v1` review requires the exact original v12 checkpoint and a separately
approved cap/expiry under an unused `ui-demo-...` campaign. The old launch form is:

```sh
poetry run python -m enterprise_analytics_agent.ui \
  --allow-live --live-review artifacts/ui-demo/review.json
```

Do not combine `--live-review` with shared-release arguments. The v12-only gate must
fail after any version-changing deployment, even when the original artifact is restored.
Its historical evidence stays under `artifacts/ui-demo/<campaign_id>/`, separate from
shared and milestone campaigns. This command and an old allowance are not permission
for the new release proposal.

Historical screenshot from the initial deterministic/legacy UI implementation:

![Initial Workbench showing a deterministic local DuckDB answer](images/analytics-workbench-ui.png)

## Code map and verification

| Read in order | Responsibility |
| --- | --- |
| `ui/assets/index.html`, `style.css`, `app.js` | Three-mode presentation, exact tables, safe text rendering |
| `ui/server.py`, `ui/models.py`, `ui/__main__.py` | Loopback HTTP, strict payloads, explicit startup gates |
| `ui/local.py`, `agent/questions.py` | AWS-free playground and shared question scope |
| `adapters/ui_local_agent.py`, `adapters/bedrock_agent.py` | Injected local runner and existing shared agent |
| `contracts_v2.py`, `catalog.py`, `agent/tools.py` | Semantic contracts, definitions and tool dispatch |
| `adapters/duckdb.py`, `adapters/athena.py` | Backend calculations and trusted restrictions |
| `ui/shared.py`, `adapters/ui_shared.py`, `adapters/ui_release.py` | Shared budget, SDK attempts, release/data proof and protected gates |
| `ui/live.py`, `adapters/ui_live.py` | Historical original-v12 review/ledger path |
| `hosting/application.py` | Existing workload-credential runtime using the shared agent |
| `infrastructure/agentcore/ui_workflow.py`, `source_audit.py` | Offline assembly/source review and guarded release operator |

Package paths are relative to `src/enterprise_analytics_agent/`, except infrastructure.
See [architecture](architecture.md), [metric definitions](metric-definitions.md) and
[progress](progress.md) for decisions and actual verification results. UI tests cover
HTTP isolation, independent DuckDB expectations, injected shared-agent behavior, source
and release drift, actual publication bindings, durable quotas/SDK receipts, failure
recovery, protected full-Q18 judging, and offline complete CLI flows.

The server binds only `127.0.0.1`, checks Host/Origin and a per-process POST token,
serves an asset allowlist and applies a restrictive content policy. There are no external
fonts, scripts or trackers. It is a single-user development application. The standard
library [HTTP server](https://docs.python.org/3.12/library/http.server.html) is used only
for this local scope; AWS dispatch uses the existing
[AgentCore invocation API](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html).
