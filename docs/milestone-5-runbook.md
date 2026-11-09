# Milestone 5 operator runbook

Status: the user authorized this reviewed deployment/evaluation/restoration window on
November 9, 2026, at pushed correction `850bbc8` (successful CI `42660104374`).
Execution finished:35/36 suite cases passed; Q18 failed by returning clarification for yesterday.
Corrected parity-v1 is restored, Runtime/DEFAULT READY v6, stack UPDATE_COMPLETE; the smoke passed.
M5 used 38/40 and is retail-closed; M4 remains 28/40. See progress for the retained evidence.
Commands below are the reviewed executed procedure; do not replay this closed campaign or reset a ledger.
Use the existing `enterprise-analytics` Conda environment, Poetry and repository root.
Profile `analytics-dev`, account `453711491609`, region `us-west-2`; no alternate profile.

## Evidence and intended change

- Runtime `enterprise_analytics_dev_agent-HlWywlG60h`, DEFAULT, model `us.amazon.nova-lite-v1:0`.
- Fresh read-only checkpoint confirmed parity-v1, Runtime/DEFAULT READY v4, stack
  UPDATE_COMPLETE, both reviewed policies, seven-day logs and unchanged foundation/data/trust.
- Frozen ZIP SHA `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1`;
  existing S3 VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`.
- Code bucket `enterprise-analytics-dev-453711491609-us-west-2-agent-code`, key
  `releases/51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1/agent.zip`.
- Retail ready manifest SHA `99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797`,
  VersionId `cvCWKV3bv9Ub4iZOPSh79W4TnizV6FmJ`. Exact object versions/hashes/sizes
  are in [oracle provenance](../evaluations/retail-v1/oracle-provenance.json).
- [Deployment review](../evaluations/retail-v1/deployment-review.json) proves only
  trusted JSON fields dataset (`parity-v1` → `retail-v1`), tenant (`t1` → `retail_demo`)
  and reference date (`2025-02-01` → `2025-04-01`) change. North/South, model, limits,
  roles/policies, artifact/version, networking, lifecycle and all resources stay fixed.
- Retail template SHA `ecfbfa8a2f011ce6fe3c765c29660a81e02ad1ca765ad6e497e2502f1fe46ac3`.
  Restore and original corrected base both SHA
  `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`.

No foundation/data deployment, IAM change, bootstrap, ZIP rebuild/upload or source
publication is required. All approved callers share the endpoint's fixed scope;
schedule the temporary retail change with them. Stop on checkpoint or proposed-change drift.
Existing M3 permissions and infrastructure remain untouched. The recorded M4 ledger
`artifacts/agentcore/runtime-invocations.jsonl` stays at 28/40, SHA
`f04f9cc568d4842b6c9e0118f01cf5b92e496c40658f25a9fdc364075eb17f14`.

## Local preparation and read-only preflight

These preparation commands do not generate replacement retail data or rebuild the ZIP.
The acquisition command is read-only but still needs authorized AWS access. Existing
canonical evidence refuses overwrite with different bytes. Keep downloaded Parquet and
raw checkpoints under ignored artifacts; only reviewed synthetic calculation evidence is committed.

```sh
conda activate enterprise-analytics
poetry env info
poetry install --only-root --no-interaction
aws sts get-caller-identity --profile analytics-dev --region us-west-2
poetry run python -m enterprise_analytics_agent.adapters.retail_provenance \
  --download --directory artifacts/milestone-5/canonical/retail-v1
poetry run python -m enterprise_analytics_agent.adapters.retail_provenance \
  --directory artifacts/milestone-5/canonical/retail-v1
```

The oracle freeze command is an audit/reproduction operation into a **new** directory,
not an evaluation-time recalculation or authorization to change committed goldens:

```sh
poetry run python -m enterprise_analytics_agent.retail_evaluation.oracle \
  --source-dir artifacts/milestone-5/canonical/retail-v1 \
  --provenance artifacts/milestone-5/canonical/retail-v1/provenance.json \
  --questions evaluations/retail-v1/questions.json \
  --output-dir artifacts/milestone-5/oracle-reproduction
```

Offline synthesis uses the existing frozen ZIP and locked CDK CLI. It needs no AWS
lookups or credentials; only the new proposal/restore output directories are refreshed:

```sh
export JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache
infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
  --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.retail-evaluation.json --phase runtime' \
  --no-lookups --no-telemetry --no-notices --output artifacts/milestone-5/cdk.retail.out --quiet
infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
  --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.development.json --phase runtime' \
  --no-lookups --no-telemetry --no-notices --output artifacts/milestone-5/cdk.restore.out --quiet
poetry run python -c 'from enterprise_analytics_agent.retail_evaluation.deployment import review_assemblies; print(review_assemblies())'
poetry run python -m enterprise_analytics_agent.adapters.retail_checkpoint \
  --scope parity-v1 --output artifacts/milestone-5/predeployment-unique.json
```

Keep the original corrected base/foundation/data assemblies retained from M4. Missing
or mismatched retained evidence is a stop condition, not permission to recreate it.
The preflight compares live stack templates, code/version, settings, both resource
policies and retention. It inspects no administrator IAM API. Review supplied admin
evidence if access changes; never automatically broaden permissions.

## Reviewed deployment and counted campaign procedure

**Do not execute this section without deployment and billable-call approval.**
The approved maximum was 40 M5 calls: warm-up 1 + questions 34 + session 2 +
restored parity smoke 1 + controlled retry/demo reserve 2. Recorded M5 usage is38/40 (warm-up 1 + suite 36 + restored smoke 1); no retries occurred.
Every call uses the same persistent `artifacts/milestone-5/runtime-invocations.jsonl`,
anchored to this repository, across runs/CLI/test processes. Never delete/reset it.
Reservations are locked/fsynced before dispatch, SDK total attempts = 1, failures and
interruptions count, non-restoration dispatch refuses at 39, and verified restoration
closes retail dispatch. Never manually invoke the Runtime or use M4's counter helpers.

After recording a unique preflight and reviewing the environment-only proposal:

```sh
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/milestone-5/cdk.retail.out enterprise-analytics-dev-agent-runtime \
  --parameters ArtifactVersionId=HSRXiFjg0w2W77InULH4.fn32Y.JH8b9 \
  --profile analytics-dev --region us-west-2 --require-approval never \
  --no-telemetry --no-notices --outputs-file artifacts/milestone-5/retail.outputs.json
poetry run python -m enterprise_analytics_agent.adapters.retail_checkpoint \
  --scope retail-v1 --output artifacts/milestone-5/retail-ready-unique.json
poetry run analytics-ask --invoke-live --warmup \
  --target-config evaluations/retail-v1/target.json \
  --question 'Show net_revenue for January 2025 by region.' --format json
poetry run analytics-evaluate --invoke-live \
  --target-config evaluations/retail-v1/target.json \
  --report-dir artifacts/milestone-5/runs/live-unique
```

The runner executes all 34 questions and S01A/B (36 requests); S01 shares one session,
other questions use fresh sessions. It reserves a unique report directory before any
dispatch, journals each completed attempt durably, retains failure/unrun denominators,
and stops further dispatch on an infrastructure failure. Warm-up is a separately labeled
ledger entry excluded from suite latency. Expected business clarifications do not stop it.
For a pytest gate **instead of** the evaluator command (never both for the same campaign):

```sh
poetry run pytest tests --run-retail-live --retail-config=evaluations/retail-v1/target.json \
  -m retail_live -q
```

Missing live config fails before any call. This gate runs the same evaluator and persistent
counter. Re-running cases/tests costs additional reservations; diagnose failures first.
No selective omission or automatic retry turns a failed campaign into acceptance.

## Mandatory restoration and failure handling

After **any attempted retail deployment**, restore the corrected base even if deployment,
warm-up, evaluation or the shell session fails. Do not start more questions after an
infrastructure fault. Preserve failed-attempt JSONL/ledger and stack events; capture full
parent/nested CloudTrail denial messages before proposing any permission correction.
If interrupted, resume directly with restoration after inspecting current state/ledger.
Restoration itself is not an invocation and must not be abandoned to save call budget.

```sh
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/milestone-5/cdk.restore.out enterprise-analytics-dev-agent-runtime \
  --parameters ArtifactVersionId=HSRXiFjg0w2W77InULH4.fn32Y.JH8b9 \
  --profile analytics-dev --region us-west-2 --require-approval never \
  --no-telemetry --no-notices --outputs-file artifacts/milestone-5/restored.outputs.json
poetry run python -m enterprise_analytics_agent.adapters.retail_checkpoint \
  --scope parity-v1 --output artifacts/milestone-5/restored-ready-unique.json
poetry run analytics-ask --invoke-live --restoration-smoke \
  --target-config evaluations/retail-v1/target.restore.json \
  --question 'Show net_revenue for January 2025 by region.' --format json
```

The smoke obtains another fresh read-only proof immediately before reservation; JSON
proof files or caller flags cannot bypass it. It checks independent literal North 28.50 /
South 13.00 USD. A failed smoke still counts. Stop and report if the protected allowance
is exhausted; do not reset it or borrow M4 calls. Restored Runtime/DEFAULT must be READY
on the same actual live/latest version, with the exact corrected base config/policies,
retention and artifact. An update creates a **later version**, not version 4 again.

## Acceptance and report review

Actual campaign:35/36 cases, all diagnostic/latency/security/session gates passed, and
restoration/smoke succeeded. Q18 alone missed its numeric answer; M5 is not complete.
Client p95 10.403s; suite 77 model calls, 114378 input / 9301 output tokens, 33 unique
Athena queries and 179826 scanned bytes. Root operation evidence is
`artifacts/milestone-5/operations/20261109T171341Z/`. Keep the failed report unchanged;
review Q18 offline before proposing any new artifact/deployment/campaign scope.

Require 36/36 cases: exact complete requests and numeric values/units/precision/versions,
all planned clarifications, no authorization/session leaks, no missing/extra results.
Require complete reported model/token/query diagnostics where work occurred and client
nearest-rank p95 ≤90s (warm-up excluded; SDK read timeout 150s is not a billing deadline).
Reports distinguish missing diagnostics from zero and deduplicate Athena query IDs/scans.
Inspect unique-run `report.json`, durable `attempts.jsonl`, `summary.md` and campaign ledger;
include restored checkpoint/smoke evidence in the final reviewed campaign record. A suite
pass alone cannot complete M5. Record actual versions, usage, failures, recovery and
restoration in `docs/progress.md` before a later completion commit. No production-readiness claim.

Official SDK references consulted during implementation: [S3 GetObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html),
[HeadObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/head_object.html),
[InvokeAgentRuntime](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html),
[GetAgentRuntime](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/get_agent_runtime.html),
[GetAgentRuntimeEndpoint](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/get_agent_runtime_endpoint.html),
[GetResourcePolicy](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/get_resource_policy.html),
and [SDK retry configuration](https://docs.aws.amazon.com/boto3/latest/guide/retries.html).
