# Connect the existing accepted Nova Runtime

This is a proposed **AWS-only UI connection**, using the already accepted Nova
Lite Runtime and the existing interactive-session-02 allowance. It does not deploy
code, upload a ZIP, change permissions or create another question budget. Enabling
it requires approval of the [binding review](../evaluations/ui-shared/accepted-nova-runtime.proposed.json).
Preparation and read-only preflight have passed; activation is pending that approval.

## What this fixes

The plain UI launch command starts the offline playground. Its tabs do not connect
an AgentCore backend. The old shared launcher also checks that current local agent
source matches the frozen Runtime; subsequent streaming work changed that source.
An old in-memory server could misleadingly display readiness despite that mismatch.

The new binding verifies the **actual frozen remote code** independently from the
current operator code. Local Bedrock is disabled, so this does not claim current
local/AWS source equivalence. Default/offline mode remains AWS-free. Unconfigured
modes now show their actual unavailable state, without invented parity/v12 metadata.

Only **Amazon Nova Lite**, `us.amazon.nova-lite-v1:0`, is available through this
binding. It provides progress updates followed by the validated final answer;
the accepted JSON Runtime does **not** stream provider words. The failed separate
multi-model rollout stays stopped and restored; this connection cannot reopen it.

## Exact scope and evidence

| Item | Reviewed value |
|---|---|
| Profile / account / region | `analytics-dev` / `453711491609` / `us-west-2` |
| Binding | `accepted-nova-interactive02-v1`, AWS only |
| Runtime / endpoint | Existing `enterprise_analytics_dev_agent-HlWywlG60h` / `DEFAULT`, READY v15 |
| Data / trusted scope | `retail-v1`, `retail_demo`, North/South; reference date `2025-04-01` |
| Existing campaign | `ui-shared-retail-v1-02`; 2/20 used, **17 regular questions remaining** at preflight |
| Expiry | `2026-11-13T23:59:00Z` — November 13, 5:59 p.m. CST |
| Protected slot | Unavailable for ordinary questions; this no-deployment binding cannot spend it |
| ZIP SHA-256 | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` |
| Actual S3 VersionId | `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` |
| Frozen 25-file source SHA-256 | `aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be` |
| Current operator source SHA-256 | `98d1521be7e35c6a89a6d7e5ad537bcdb92851306a40a6725c2a8086988eebc9` |
| New review semantic SHA-256 | `e6fdf1354c736f07b54807978af8af4e0612c85e6c091c5b162cbef25b2003a8` |

Read-only preflight passed at **2026-11-12T23:54:52.538325Z**. It verified the
selected STS caller/account, exact Runtime/DEFAULT artifact and configuration,
CloudFormation template/parameters and stack status, both resource policies,
seven-day retention, S3 version/checksum/size, and canonical S3/Glue bindings.
Local checks verified the archive's 25-file source closure, locked dependencies,
canonical bytes/provenance and goldens. All 352 protected historical files stayed
unchanged. No model/Runtime invocation, Athena query or resource mutation occurred.

Raw evidence is retained locally at
`artifacts/ui-shared/accepted-nova-runtime/preflight-20261112T235400Z.json`, SHA-256
`b4c782bd419092c7c36a5c1d7ef4a3edfd7042a40e2c33911f536b6a8165ca35`,
with its `.reads.jsonl` operation journal. The committed
[readiness summary](../evaluations/ui-shared/accepted-nova-runtime.readiness.json)
records the pins and observed budget. This proof is a dated observation; each
question performs fresh checks before reservation and dispatch.

## Activation after exact binding approval

The new approval is needed because this AWS-only connection verifies the frozen
remote source directly, replacing the old launcher's local/remote source-equality
requirement. It does not renew, extend or reset the existing approval or allowance.
Record the actual approval in
`artifacts/ui-shared/accepted-nova-runtime/approval.json` using the strict
`ui-accepted-runtime-approval-v1` schema and this review SHA. Do not create that
record before the owner approves this binding.

Recheck the task-owned process on port 8501 before replacing it; preserve unrelated
servers and logs. From the repository root:

```sh
conda activate enterprise-analytics
poetry run python -m enterprise_analytics_agent.ui --port 8501 \
  --accepted-runtime-review evaluations/ui-shared/accepted-nova-runtime.proposed.json \
  --accepted-runtime-approval artifacts/ui-shared/accepted-nova-runtime/approval.json \
  --allow-live
```

Open **http://127.0.0.1:8501/?mode=live**. Nova should be selected, the target
should show retail-v1/v15, and the remaining regular allowance should reflect the
existing ledger. This page load and mode/model selection send no question. Enter
a question and click **Ask AWS** to make a billable call. The composer clears
immediately; progress precedes the exact validated final response.

The operator verifies the browser's model, target, status and submission control
without submitting a question. The 17 remaining questions belong to the user:
do not repeat Q18, run a demonstration, or automate these slots. Every attempted
question and SDK dispatch is durably counted before the single invocation; there
are no automatic billable retries. Scope/model/identity/configuration remain
server-owned, and the Runtime payload contains only `question` with a fresh session.

On any drift, expiry, SDK failure or incomplete receipt, stop dispatch and retain
diagnostics. Preserve v15; do not deploy, restore another artifact, change IAM,
reset a ledger, relabel the protected slot or retry a question automatically.
Stopping this local UI does not change the deployed Runtime.

## Verification and remaining work

Current local checks passed: **2,141 tests, 85 deselected, zero selected skips**;
Poetry lockfile validation, Ruff, formatting (**201 files**) and mypy (**159 files**).
Behavioral tests cover stale readiness, unconfigured metadata, real JavaScript
states, explicit approval/expiry, frozen archive/configuration mismatch, scope,
sessions, durable existing-budget accounting, process guards and no billable
retries. Private error diagnostics now retain redacted SDK code/message/request ID,
including wrapped setup errors, without changing public semantic contracts. These
local diagnostics changes have not been deployed into any frozen Runtime.

The exact next task is owner approval of the new AWS-only binding, followed by
local activation and a zero-invocation browser check. Multi-model acceptance and
provider-word streaming remain incomplete; no further permission change or model
retry is justified by this proposal. Earlier hosted CI covers its named commits,
not these new source changes.

SDK reference: [Boto3 InvokeAgentRuntime](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html).
