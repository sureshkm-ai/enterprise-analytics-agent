# Progress

Updated: 2026-11-06 (America/Chicago).

## Current milestone and repository state

**Milestone 4 — implemented and verified offline; deployment and live-agent acceptance pending approval.** Work is on `feat/milestone-4-bedrock-agentcore`, created from clean `main` at `6bf1220` (PR #3 status-document merge). Existing work was preserved. This checkpoint records local readiness; Git history identifies its local commit; no milestone 4 push, hosted CI, deployment, IAM mutation, code upload, or billable model/runtime call has occurred. Milestone 4 is **not complete** and production readiness is not claimed.

**Milestone 3 is complete: implemented, deployed, live-validated, merged, and hosted-CI verified.** The user confirmed [PR #2](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/2), merge [`ae378e4c289144164a8a7a6a85fa8c71ae5bcacc`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/ae378e4c289144164a8a7a6a85fa8c71ae5bcacc), and successful [CI run 42166641840](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42166641840). Local starting main `6bf1220` contains that merge and its documentation update. Historical AWS/live results below retain their user-executed attribution; that parity suite was not rerun during milestone 4 preparation.

**Milestone 2 remains implemented, merged into `main`, and verified by hosted CI.** [PR #1](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/1) merged implementation commit `e13b1ea` at merge commit `9dc5989353459e2651ba5cced882534d8d573783`. [GitHub Actions run 42113416826](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42113416826) passed for that merge commit, as confirmed by the user.

## Milestone 4 readiness work and decisions

- Read AGENTS, README, architecture, metric definitions, implementation plan, progress and deployment record; inspected Git/history and asserted the existing `enterprise-analytics` Conda interpreter, Python 3.12.16 and Poetry 2.3.1. Baseline lockfile, pytest (**458 passed, 66 skipped in 45.67s**), Ruff lint/format and mypy all passed before implementation.
- Added an injected, bounded Bedrock Converse loop exposing exactly the four existing semantic operations through validated v2 requests. Existing v1/v2 semantic schemas, catalog calculations, and adapter query semantics are unchanged. Multiple tool IDs, malformed responses/arguments, recovery, failures and time/iteration/tool/token limits are covered offline.
- Typed agent answers render exact validated tool numbers, units, nulls, groups, periods and metric/dataset versions. A deliberately conservative question guard clarifies ambiguity/unsupported requests, anchors relative periods to server configuration, and rejects model plans that change requested scope. Independent review fixed exclusion wording interpreted as inclusion, combined comparison results, ignored unsupported metrics/time grains, and unrequested catalog searches. Catalog search remains available to direct semantic callers; the initial agent lists the full catalog.
- Added a stateless manual HTTP runtime with only `question` accepted in payloads. IAM-approved callers share fixed server scope `t1` / North+South; prompts, sessions, headers and history never authorize access. Workload credentials assume the narrow query role with expiry refresh. No local profile/SSO credentials enter the package. Logs record configuration, tokens, latency, tools and Athena execution diagnostics.
- Prepared a Poetry-locked Python 3.12 Linux ARM64 ZIP, checksum manifest, separate CDK foundation/runtime stacks, explicit caller policies, scoped model/log permissions, immutable/versioned code publication, and an additive query-role trust change. Offline comparison with the deployed data-layer template found only query-role trust changed. The data layer is reused; no bootstrap or dataset republishing is planned.
- Ordinary pytest/CI remains AWS-free. Added offline agent/runtime/packaging/CDK regressions and explicit live-agent gates with authored literal expectations, all five metrics, period/filter/grouping validation, missing/empty returns and same-session isolation. Missing live configuration fails instead of reporting skipped acceptance. Live evaluation artifacts record semantic plans/results rather than grade prose.
- Updated README, architecture, metric definitions, implementation plan, root instructions, and milestone 3 deployment handoff. [AgentCore deployment/live plan](agentcore-deployment-plan.md) specifies the exact resources, IAM changes, usage allowance, commands, costs, retention and cleanup. No Cube, UI, Gateway, Memory or other additional AgentCore services were implemented.

## Milestone 4 read-only AWS evidence

The user explicitly selected `analytics-dev` and renewed SSO after expiration. Subsequent read-only STS verified account `453711491609` / `us-west-2`; no default-profile fallback occurred. Existing data-layer stack is `CREATE_COMPLETE`. Ready manifests, 27 Glue schemas and object checksum/length metadata verified all four snapshots, including `retail-v1`; ignored evidence is `artifacts/m4-snapshot-verification.json`. These are metadata checks, not rerun live metric queries or a retail agent demonstration.

Selected configurable profile `us.amazon.nova-lite-v1:0` is ACTIVE; Nova Lite model availability reports AVAILABLE/AUTHORIZED. Official Converse/tool-use support was checked. US inference may route to us-west-2/us-east-1/us-east-2; model access is not yet proved by invocation. `iam:GetRole` remains denied to the operator, so an administrator must verify existing attachments/trust and attach the proposed narrow M4 CloudFormation execution policy. Read-only Access Analyzer found two invalid S3 action names initially; corrections were verified against official S3 permissions and revalidation returned **zero findings**. No permissions were changed.

## Milestone 4 local verification

All Python/Poetry commands below use `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python`. Current final results are recorded after the full check run; live AWS/agent suites are intentionally excluded pending approval.

| Command | Actual result |
| --- | --- |
| Interpreter assertion, `poetry --version` | Existing Conda Python **3.12.16**, Poetry **2.3.1**. |
| `poetry check --lock` | Passed: All set. `poetry lock` refreshed only the content hash for the explicit packaging development dependency; no locked package versions changed. An attempted `poetry lock --offline` was unsupported by Poetry and was replaced by the successful cached `poetry lock`. |
| `poetry run pytest` | **617 passed, 84 skipped in 54.65s**. Skips: 66 existing live AWS cases and 18 new base live-agent cases. No live acceptance claimed. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: **75 files** already formatted. |
| `poetry run mypy src tests` | Passed: **56 source files**. |
| `poetry run mypy src tests infrastructure/cdk infrastructure/agentcore` | Passed: **66 source files**. |
| `poetry run pytest tests --run-agent-live --collect-only -q` | Expected exit **4**: `--run-agent-live requires --agent-config; no live agent acceptance was run`. No AWS call. |
| `poetry run python -m infrastructure.agentcore.package --config infrastructure/agentcore/runtime.development.json --output artifacts/agentcore/agent.zip --offline` | Passed; 13 locked main dependency wheels, **39,115,757 compressed / 85,640,244 unpacked bytes**. Initial wheels were downloaded from PyPI; final builds reused the cache. |
| Same packaging command with `--output artifacts/agentcore/agent.repeat.zip --project-wheel artifacts/agentcore/project-dist/enterprise_analytics_agent-0.1.0-py3-none-any.whl --offline` | Passed; archive bytes identical. SHA-256 **`843bf34fdde1d471bcf7b4741536e04c3fa08cdc5651f677f9804146ecaa55b6`**; both native libraries verified AArch64 ELF. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.development.json --phase all' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.agentcore.reviewed.out --quiet` | Passed offline: **4 foundation + 3 runtime resources**, no missing lookup context. Nonblocking CDK dependency deprecation and feature-flag advisories emitted. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.m4-data-trust.cli.out --quiet` | Passed; **41 existing resources**, deployed-template comparison proves only the additive query-role trust statement changes. |
| `poetry run python -m infrastructure.cdk.agentcore_app --config artifacts/agentcore/deploy.<version>.json --phase runtime --outdir artifacts/cdk.agentcore.<version>.out` | Passed once for each of `parity-legacy-v1` and `parity-no-returns-v1`; three resources each. No AWS calls. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/cdk.ci-final.out` | Passed, matching offline CI's existing-data synthesis. |
| `poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.example.json --phase foundation --outdir artifacts/cdk.agentcore-ci-final.out` | Passed, matching offline CI's new foundation synthesis. |
| `aws accessanalyzer validate-policy --profile analytics-dev --region us-west-2 --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json --output json --no-cli-pager` | Read-only verification passed: **zero findings**, after fixing the initial invalid S3 actions. |
| `git diff --check` / `git diff --cached --check` | Both passed; the 44-file implementation/test/documentation diff was reviewed before the local readiness commit. Eight deployment-plan shell blocks passed `zsh -n` syntax validation without execution. |

Packaging evidence is in ignored `artifacts/agentcore/agent.manifest.json`; deployment configuration pins the reviewed archive SHA-256. Native wheel ABI/platform checks passed. Foundation/runtime and existing-data trust synthesis use no account lookups. Offline readiness is not hosted CI or deployed-agent acceptance.

## Historical milestone 3 merge-status documentation update verification

Read AGENTS, this progress log, and the implementation plan. Inspected `git status --short`, `git log -5 --oneline`, the current branch and tracking refs, and `git rev-parse HEAD main origin/main` before describing the checkout. GitHub merge/CI details are the user's confirmed evidence. `git diff --check -- docs/progress.md` passed and the document diff was reviewed. Only `docs/progress.md` changed. Historical local checks and user-reported live results were preserved; no application tests, lint/type checks, hosted workflows, or AWS operations were rerun. No other files, branch switches, commits, or pushes are part of this update.

## User-executed AWS deployment and live validation

| Operation | Result reported by the user |
| --- | --- |
| `CDKToolkit` bootstrap | `CREATE_COMPLETE` |
| `enterprise-analytics-dev-data-layer` | `CREATE_COMPLETE` |
| Live parity suite | **66 passed, 458 deselected in 111.94 seconds** |

Exact user-executed command from the repository root:

```sh
poetry run pytest tests --run-aws --aws-config=infrastructure/cdk/config.development.json -m aws_integration -q
```

The suite compares both Athena and DuckDB independently with authored literal expectations across all five metrics and the three parity snapshot variants. This reported run satisfies the development live-parity gate. It does not independently establish synthetic `retail-v1` publication, exact deployed IAM attachments/resource outputs, measured costs, or live cancellation fault injection; those were not reported or audited here. The [deployment record](aws-deployment-plan.md) retains the reviewed configuration and cleanup behavior. No AWS operations were repeated for this update.

## Historical deployment documentation checkpoint and offline-check coverage

The user requested a local commit after the documentation review found no actionable issues. The six reviewed Markdown files were committed in `3424d07`, with commit-status wording reconciled beforehand. `git diff --check` and `git diff --cached --check` passed. No application checks or AWS operations were rerun then; existing results below covered unchanged code. That checkpoint was subsequently pushed and merged through PR #2.

Read AGENTS and all project documentation; inspected Git status/log, the `ae68d2c` commit, executor cleanup logic, and its regression tests. The committed executor blob `1c8f729d9e29dea65155689d6f8be6d8e70f0021` and lifecycle-test blob `a040fd1241f7abe84028bc9536c598acc0167de1` match the versions covered by the recorded checks below. All other code/tests, infrastructure, dependencies/lockfile, and CI configuration are unchanged from readiness commit `7edd010`.

Offline evidence available at that checkpoint was **458 passed, 66 skipped**, 61 lifecycle tests passed, lockfile validation passed, Ruff lint/format passed, and mypy passed. These checks were **not rerun** during that documentation update or commit preparation. At that stage, milestone 3 hosted CI had been confirmed for `7edd010`; newer hosted results had not been checked or inferred from local/live results. Only README and project documentation changed then; no source, tests, infrastructure, dependencies, or AWS operations changed. The preceding documentation-only update made no commits or pushes; the later user request authorized local commit `3424d07`, with no agent push. The completed merge and merge-commit CI are recorded in the current status above.

## Historical cancellation fix verification — now committed in `ae68d2c`

The local fix session started at `54d868a` (`update progress.md with milestone 3`) with a clean working tree and left the fix uncommitted as requested at that time. The user subsequently committed it in `ae68d2c`. During that fix session, read AGENTS, implementation plan, progress, executor/adapter code, and lifecycle tests; inspected Git status/log. Verified Poetry 2.3.1 and `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python` (Python 3.12.16) before tests; all checks used this existing Conda environment. No existing work was discarded. The following are recorded results, not reruns in this update.

- Abnormal exits after receiving a query ID now request best-effort cancellation while the query may still be running, including exhausted polling service/connection errors and malformed responses. Separate terminal-state tracking is reset for each execution attempt. Known SUCCEEDED/FAILED/CANCELLED executions are never stopped, including result-fetch failures/timeouts and failed-query retry backoff. Polling errors never resubmit a potentially running query.
- Cleanup reuses lifecycle retries with a fresh `min(query timeout, 5 seconds)` scheduling budget, independent of the expired main deadline. Existing Athena SDK client factories retain finite connect/read timeouts (at most 5/10 seconds) and disable nested SDK retries. An in-flight call can outlast the scheduling budget; cleanup is not a hard wall-clock guarantee. No follow-up terminal-state polling is added.
- Original exceptions/causes survive cleanup failure. Internal diagnostics add cancellation attempt counts and `REQUEST_ACCEPTED`, `REQUEST_FAILED`, or `DEADLINE_EXCEEDED`; acceptance does **not** assert confirmed CANCELLED status. Malformed statistics cannot replace the primary exception during diagnostic recording. Semantic contracts and legitimate terminal-failure query retries are unchanged.

| Command | Actual local result |
| --- | --- |
| `poetry run pytest tests/test_athena_execution.py -q` | Baseline **39 passed**; after fix/regressions **61 passed in 0.05s**. |
| `poetry run pytest tests/test_athena_execution.py -q -k exhausted_poll_retries_cancel_running_query` | **2 failed against the original implementation**: service/connection retry exhaustion produced no stop call. Same tests **2 passed after the fix**, preserving original error causes and issuing one stop request without resubmission. |
| `poetry check --lock` | Passed: All set. Dependencies/lockfile unchanged. |
| `poetry run pytest` | **458 passed, 66 skipped in 33.22s**. Only explicitly gated live AWS tests skipped; no live acceptance claimed. |
| `poetry run ruff check .` | Passed after fixing test formatting found by the initial checks. |
| `poetry run ruff format --check .` | Passed: 50 files already formatted. |
| `poetry run mypy src tests` | Passed: 38 source files. |
| `git diff --check` | Passed; final implementation, tests, and progress diff reviewed. |

Regression coverage includes malformed polling responses/statistics, permanent/transient/connection polling errors, failed cleanup preserving the original exception object, retry/time budgets, cleanup after main timeout, per-attempt query IDs, and no stop without an ID or after a known terminal state. Independent read-only review found no additional actionable defects. Checked official [StopQueryExecution](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/stop_query_execution.html), [query-state](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/get_query_execution.html), and [SDK timeout/retry](https://docs.aws.amazon.com/botocore/latest/reference/config.html) documentation during that session. No live AWS calls, IAM changes, deployments, publications, live tests, commits, or pushes were made by the agent during that local fix session; only the executor, its lifecycle tests, and this document changed then.

## Historical milestone 3 hosted CI and documentation update

[GitHub Actions CI run 42152288133](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42152288133), triggered by the push to `feat/milestone-3-athena`, completed with **success** for commit `7edd01079fb7ee606305cebd62f5123d1fbc14cf` on 2026-11-05 (America/Chicago). GitHub's run/job records confirm the lockfile check, locked dependency installation, pytest, Ruff lint/format, mypy, and offline CDK synthesis all passed. This is hosted offline verification; it does not establish AWS deployment or live Athena parity.

For that earlier documentation-only update, read AGENTS, implementation plan, and progress; inspected `git status --short`, `git log -5 --oneline`, branch tracking, and remotes; verified the remote branch SHA and successful CI job steps through the GitHub connector. The working tree was clean before editing. `git diff --check` passed and the document diff was reviewed. Only `docs/progress.md` changed then; application tests, linting, type checks, synthesis, and AWS verification were not rerun. No AWS operations, commits, or pushes were performed during that update.

## Historical milestone 3 preparation and decisions — before deployment

This section records the original readiness checkpoint. Its missing-stack/permission findings and lack of uploads/live queries describe that earlier stage; the user-reported deployment and live results above supersede the pending-deployment status.

- Python CDK v2 defines retained private/versioned/SSE-S3 source and result buckets, explicit Glue schemas for four versioned snapshots (27 tables), an engine 3 Athena workgroup, a 10 MiB per-query cutoff, metrics/alarm, and separate exact-key loader/query roles. Results expire after 7 days; incomplete uploads after 1 day. Offline synthesis has 41 application resources and no missing lookup context.
- Canonical publication freezes and validates schema, tenant-scoped relationships, required fields, and event conflicts; collapses exact replays; records version/seed/inventory/checksums; verifies deployed schemas and uploaded bytes; conditionally publishes the ready manifest last. Existing or partially uploaded versions fail rather than overwrite. Absent versus empty returns and legacy six-table support are preserved. At that readiness checkpoint, candidate manifests/data existed only under ignored `artifacts/`; the agent had not uploaded them.
- Athena implements all four semantic operations and five metrics behind unchanged v1/v2 contracts and catalog definitions. Parameters are encoded SQL literals, identifiers governed, and trusted tenant/region predicates mandatory. DECIMAL(38,0) aggregates and exact integer final rounding avoid float and join fanout. Bounded polling/retries, timeout cancellation, pagination, strict result parsing, and private diagnostic records are tested offline.
- Added 64 authored parity cases with independent literal answers, plus live missing-source and v1/dimension checks. Both adapters must independently match the literals. Totals are gross $53.00, net $41.50, count 3, AOV $13.83, return rate 0.666667. Default pytest/CI use no AWS; explicitly requested live runs fail on missing configuration. CI adds offline synthesis.
- The user selected `analytics-dev`; read-only STS verified account `453711491609`, region `us-west-2`. At initial verification, `CDKToolkit` was absent and Athena listed only `primary`. `iam:GetRole` was denied, so bootstrap/admin privileges and the derived stable SSO trust ARN needed administrator confirmation then. No implicit default-profile fallback is allowed.
- Prepared a resource-scoped CloudFormation execution policy instead of default AdministratorAccess, including read-only access to the assembly's exact bootstrap-version SSM parameter. Read-only IAM Access Analyzer returned no findings; this was not proof of deployment compatibility/privileges. At that stage, bootstrap required separate approval and IAM permission. Tenant filtering is application enforcement, **not Lake Formation row-level security**; direct data-role access can read all approved snapshot rows.
- The existing global CDK CLI 2.1138.0 could not read library 2.275.0's assembly. Kept it unchanged; added repository-local CLI 2.1148.0 with npm lockfile. Its synthesis passed. During readiness preparation, no account lookups, credential output, resource creation, publication, or Athena queries occurred.

## Historical milestone 3 readiness verification

All application commands used the existing `enterprise-analytics` Conda interpreter `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python` (Python 3.12.16), explicitly asserted before final checks; Poetry 2.3.1 reused that environment. Before changes, all five required checks passed, including **212 tests in 21.91s**. Locked installation added 24 packages with no updates/removals; a later install registered the publication entry point.

| Command | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **436 passed, 66 skipped in 49.07s**. Skips are the explicitly gated live AWS tests, not acceptance evidence. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 50 files already formatted. |
| `poetry run mypy src tests` | Passed: 38 source files. |
| `poetry run mypy src tests infrastructure/cdk` | Passed: 42 source files. Two test-only typing failures found during final checks were fixed. |
| `poetry run pytest tests/test_aws_runtime.py -q` | Passed: 7 tests in 0.53s after the test-only typing fix. |
| `poetry run pytest --run-aws --collect-only -q` (historical missing-config guard, not a live-run command) | Expected exit 4: `--run-aws requires --aws-config; no live acceptance was run`. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/cdk.out` | Passed offline. Local CDK commands used `JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache` for sandbox-safe caching. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json --outdir artifacts/cdk.development.out` | Passed offline. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.reviewed.out --quiet` | Passed; 41 resources, no missing context. Template SHA-256 is recorded in the deployment plan. Only a feature-flag advisory was emitted. |
| Repository-local `cdk bootstrap --show-template --profile analytics-dev --region us-west-2 --no-telemetry --no-notices` | Displayed bootstrap YAML locally; did not create resources. |
| `npm ci --prefix infrastructure/cdk/tooling --ignore-scripts --offline --cache /private/tmp/enterprise-analytics-npm-cache` | Passed after approved initial installation; local CLI version 2.1148.0. |
| `poetry run python tests/aws_fixture_data.py --output-dir artifacts/aws-datasets` | Prepared local retail, independent parity, legacy, and empty-return snapshots. Canonical inventories/checksums inspected locally. |
| `poetry run analytics-publish --help` | Passed without AWS calls; no publication command executed. |
| `aws sts get-caller-identity`, profile region inspection, `aws cloudformation describe-stacks --stack-name CDKToolkit`, `aws athena list-work-groups`, `aws iam get-role` | Explicit `analytics-dev`/`us-west-2`: identity verified; bootstrap absent; only primary workgroup; IAM inspection denied. |
| `aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/deployment-policy.development.json --profile analytics-dev --region us-west-2` | Passed with `findings: []`; read-only policy validation. |
| `git diff --check` and `git diff --cached --check` | Passed; diff reviewed before the local readiness commit. |

Focused CDK, publication, lifecycle, contract, runtime, and fixture checks also passed during implementation. Review tightened source IAM to exact canonical keys (preventing append-after-readiness), added account guards, and rejected a stale returns file when preparing a legacy fixture. No live acceptance was attempted at that readiness checkpoint.

Historical milestone 2 baseline: inspection read AGENTS, README, and all four docs; `main` was clean at `64cbea4`. Before implementation, all five required checks passed, including 68 tests in 7.07s. Python and Poetry both used `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python` (Python 3.12.16, Poetry 2.3.1). A second explicit environment assertion confirmed the same existing Conda environment before final tests. No local environment replacement or dependency upgrade was needed; milestone 2 did not change `pyproject.toml` or `poetry.lock`.

## Historical milestone 2 completed work

- Documented all five metric definitions before calculations; preserved net revenue definition 1.0.0 and its eligibility/time semantics.
- Added all five metrics through separate v2 contracts: exact currency/count/nullable-ratio values, appropriate grains, units, precision, and public business metadata. V1 contracts remain byte-unchanged; nine frozen schema fingerprints and literal net revenue JSON protect compatibility.
- Added optional deterministic physical return events, statuses, quantities, tenant-scoped references, duplicate handling, and missing-return-data errors. Six-table snapshots remain usable for the other metrics.
- Preserved all original six logical datasets for the same seed, verified with twelve frozen milestone 1 fingerprints (six tables, two seeds). Return generation uses a separate random stream and guarantees financial/physical return distinctions at the order level.
- Added item/order aggregation without join fanout; distinct received-return order flags; exact aggregate ratios rounded only at the end. The CLI preserves default v1 net revenue and adds metric/API selection.
- Retained the original accounting, contract, and authorization coverage and added independent multi-metric, return, precision, compatibility, filtering, and CLI tests.
- Added push/PR GitHub Actions CI with SHA-pinned official actions, Python 3.12, Poetry 2.3.1, read-only permissions, locked dependency sync, and the five required checks. README, all four docs, and root instructions reflect milestone 2 and the new roadmap.

## Historical milestone 2 decisions and reasons

- V1 remains net-revenue-only. V2 supports currency, count, and ratio results without changing published v1 schemas. Currency and ratio values are decimal strings; counts are integers. Nonmonetary v2 results have `currency: null`.
- Completed/shipped USD orders with at least one valid item qualify. Invalid snapshot records fail validation. Tenant/region scope comes only from trusted application context; purchase-time region/channel control grouping and authorization.
- Refunds and physical returns are independent facts. Approved refunds reduce net revenue; received physical returns count an order once, even with partial returns or multiple returned items. Both use the original order date and loaded snapshot with no as-of cutoff.
- Average order value uses aggregate net revenue / aggregate order count; return rate uses returned-order count / eligible order count. Integer rational arithmetic applies final ROUND_HALF_UP at 2/6 places independently of Decimal context. Zero denominators are null. Payment events never join metric aggregates.
- The generated-table assertion was extended from six to seven; legacy schemas and fixture helpers stay six-table-compatible. Golden dataset fingerprints are compatibility checks, never expected answers for metrics; metric tests use authored data and literal arithmetic.
- CI configuration follows current official action releases and Poetry docs, linked in README/architecture. Local `poetry sync --help` confirmed the pinned Poetry supports the flags; sync was not executed against the existing Conda environment.

## Historical local verification — milestone 2 implementation

These commands and results were recorded during milestone 2 implementation. They were not rerun during the earlier documentation-only merge update. The separate milestone 3 baseline/final checks are recorded above.

| Command | Recorded result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **212 passed in 23.71s**. |
| `poetry run ruff check .` | Passed: all checks passed. |
| `poetry run ruff format --check .` | Passed: 28 files already formatted. |
| `poetry run mypy src tests` | Passed: no issues in 22 source files. |
| `poetry sync --help` | Confirmed support for `--with dev --no-interaction`. |
| `git diff --check` and `git diff --cached --check` | Passed. Reviewed the 19-file milestone diff; v1 contracts, project dependencies, and lockfile are unchanged. |

During milestone 2 implementation, all five CLI commands below exited 0 using the fixed default period/seed. They were executed sequentially against `data/retail`; these are historical demo outputs, not test oracles. The demonstrations were not rerun during this update:

`poetry run analytics-demo --data-dir data/retail --metric <metric>` was run once for each row:

| Metric | East | North | South | West |
| --- | ---: | ---: | ---: | ---: |
| gross_sales (USD, v2) | 1294.75 | 1150.50 | 733.50 | 1233.50 |
| net_revenue (USD, v1) | 1158.41 | 1023.15 | 643.88 | 1119.27 |
| order_count (v2) | 16 | 18 | 9 | 17 |
| average_order_value (USD, v2) | 72.40 | 56.84 | 71.54 | 65.84 |
| return_rate (fraction, v2) | 0.000000 | 0.166667 | 0.111111 | 0.117647 |

Independent worked fixture: gross $53.00, net $42.50, three orders, AOV $14.17, return rate 0.333333; the regional ratios are not averaged. Tests also cover half-up ties ($0.005 -> $0.01 and 1/128 -> 0.007813), caller Decimal precision 2, missing versus empty return sources, received returns without refunds, refunds without returns, multiple items/events, exact/conflicting replays, empty queries, boundaries, and tenant/region isolation for every metric.

Focused verification was run while implementing; initial formatting/lint issues were fixed. Independent read-only source/CI review found no concrete blockers. No required local checks were skipped.

## Historical documentation-only merge update

Read AGENTS, this progress log, and the implementation plan. Inspected `git status --short`, `git log -5 --oneline`, the current branch, HEAD, and local `main` before describing the repository state. `git diff --check` passed and the document diff was reviewed. Only `docs/progress.md` changed; local application tests, linting, and type checks were not rerun. No application changes, AWS operations, commits, or pushes were made during this update.

## Completion status and known limitations

Milestones 1–3 are complete; historical implementation, user-run AWS parity, merge and hosted CI evidence remain separate. Milestone 4 is locally implemented and tested, pending approval, administrator IAM prerequisites, deployment, live agent acceptance, later hosted CI/review/merge. The prepared runtime has not been deployed or called. The conservative vocabulary covers named metrics/months, explicit exclusive ISO ranges, region/channel inclusions and side-by-side results; change/exclusion calculations, arbitrary time grains and broader natural language may clarify. Numeric answers use deterministic rendering rather than model prose. Session history is intentionally not retained.

Runtime packaging targets Linux ARM64, not the local macOS native libraries. API/CloudFormation/model compatibility is checked offline and against official documentation but requires approved live acceptance. Scheduling deadlines and Athena cancellation remain best effort; an in-flight SDK call can outlast them. The operator's denied IAM inspection is an administrator prerequisite, not a reason to broaden permissions automatically. Initial acceptance uses parity snapshots even though retail publication metadata is now verified. No production isolation/policy service or measured-cost claim is made.

Source versions are immutable through the approved loader protocol; partial publication is deliberately not resumed automatically. New dataset versions require reviewed infrastructure inventory changes. Athena aggregates have a 38-digit bound. Application authorization is not a database security boundary, and 10 MiB per-query limits do not cap aggregate spend. Stored data is retained by default; no explicit cleanup was reported or performed in this update.

Historical milestone 2 branch creation was initially denied by the sandbox's read-only Git metadata restriction; the approved retry succeeded. Its implementation commit, merge, and hosted CI verification are complete.

Milestone 2 introduced no AWS credentials, calls, deployment, Athena adapter, or Bedrock/AgentCore integration. Milestone 2 used an application-controlled in-memory snapshot; there is no production policy service, FX, as-of history, streaming, or complete financial/cumulative physical-return ledger. Over-refunds can produce negative net revenue/AOV. Present optional return files are validated even when another metric is queried.

## Exact next task

**Milestone 4 remains open.** Review the completed [AgentCore deployment and live-test plan](agentcore-deployment-plan.md) and request approval for its exact development resources, IAM/trust changes, immutable code upload and at most 40 billable Runtime invocations. An explicitly selected administrator must verify/attach the scoped CloudFormation execution policy first; the current operator lacks IAM inspection privileges. Do not repeat bootstrap or publish datasets.

After approval, deploy foundation, apply the reviewed trust-only existing-stack update, upload the checksum-pinned archive and record its S3 VersionId, deploy the Runtime, run the three authored parity-snapshot agent suites, set log retention and restore `parity-v1`. Record actual results and leave the milestone open if any gate fails. Keep the readiness commit local; no push is authorized. Do not begin Cube, a UI, or other AgentCore services.
