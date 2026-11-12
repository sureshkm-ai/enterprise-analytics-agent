# Streaming completion correction and remaining acceptance

Status: the exact replacement was approved at **f591498**, uploaded and deployed.
Nova Q18 and all-five regional acceptance passed with exact results and real
provider-word streaming. Sonnet Q18 then failed its first Converse call with
**AccessDeniedException / model_error**. The operation stopped and completed
mandatory restoration. Multi-model acceptance **did not pass**; no new UI binding
is enabled. This executed plan must **not be replayed**.

## Actual execution and restored checkpoint — November 12, 2026

[Approval](../evaluations/bedrock-streaming/completion-fix-approval.json) binds the
exact review and preparation below. The
[outcome record](../evaluations/bedrock-streaming/completion-fix-outcome-2026-11-12.json)
contains actual releases, all ten deployment/restoration proofs, case results,
usage and raw-evidence checksums. Evidence directory:
`artifacts/bedrock-streaming/completion-fix/operations-20261112T220820Z/`.

Fresh preflight passed; one conditional upload returned actual VersionId
**PQbNv3gkC1HwVYNNiAe95r1XuQDkfKvb**. All ten existing targets verified
**UPDATE_COMPLETE / Runtime and DEFAULT READY v2**. Exactly three acceptance
questions ran: Nova Q18 passed **110.25 USD [2025-03-31, 2025-04-01)**; Nova all-five
regional metrics passed every complete request/result and word-streaming gate;
Sonnet Q18 failed with no semantic query. The other **17** cases did not run.

All ten targets were then restored to the exact original **c136a393… / GSY36sTbDpCNZGogULTe3cBL__bujiQK**
artifact/configuration, verified **UPDATE_COMPLETE / Runtime and DEFAULT READY v3**.
The untouched legacy **v15** passed its one protected Q18 smoke at **22:29:52Z**.
Final operator status is **failed-restored**, exit **1**, preserving the original
acceptance failure. No model retry, speculative grant or additional campaign ran.

Child usage is **4/37** (ordinary 3, protected cleanup 1), prior **3**, aggregate
**7/40**. It is failed/blocked with no incomplete receipt. Its numerical 32 remaining
ordinary slots are unusable; the reserve is unavailable and cleanup is spent.
All 352 protected historical files remain unchanged, including prior claims,
ledgers and frozen assets. New approved child records are stored separately. The new upload
is retained, not promoted or deleted. M1–M5 completion remains unchanged.

Commit **f591498** is pushed, with successful
[push CI 43316129337](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43316129337)
and [PR CI 43316722939](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43316722939):
**2055 passed, 85 deselected, zero skipped**, lint/format/types/lock/synthesis passed.
Those runs cover the implementation, not later outcome documentation.
[PR #13](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/13) stays draft
and unmerged because complete multi-model acceptance is missing.

## Correction and preserved checkpoint

The [recovery checkpoint](../evaluations/bedrock-streaming/recovery-deployment-checkpoint-2026-11-12.json)
records ten verified streaming stacks, Runtime/DEFAULT READY v1, and the applied
query-role trust addition. Nova Q18 passed with real provider streaming. The
all-five question returned the exact independent requests/results, but a byte-bound
reservation for an unnecessary planner turn produced `token_limit`. The protected
legacy-v15 smoke passed. The [failure evidence](../evaluations/bedrock-streaming/acceptance-failure-2026-11-12.json)
and closed **3/40** ledger remain immutable.

The production correction runs only at a pre-dispatch input-reservation boundary
or the planning-round limit, with a trusted streaming-only option. Existing
successful queries must form a scope-valid semantic subset without duplicates or
errors, with one validated result per query. Only missing queries are then really
executed through the existing server-resolved semantic-tool path, using the same
trusted authorization, real server-operation IDs and tool/deadline checks. Every
requested query/result must be present before a numeric answer. This supports
both parallel and sequential models without another planning call or fabricated
model turns. Every numeric answer is independently checked at the streaming
boundary before presentation; reordered grouping/filter sets retain their existing
semantics. Provider truncation, actual token overruns, invalid/error plans and
expired deadlines remain failures. No token ceiling/reservation is weakened. The
base-agent default and public v1/v2 contracts remain unchanged. Presentation still
requires its own reservation and real canonical-prefix-validated provider words.

The existing legacy v15 deployment is not updated. Original ZIPs, uploaded object
versions, old templates, canonical bytes, golden answers and all historical
ledgers/claims remain preserved. Changing the local planner changes the historical
core-source fingerprint: **new local code is not asserted equal to legacy v15**.
The replacement archive matches all 76 current source/assets and its explicit
streaming entry point. Its 24 shared core modules match local source; the legacy
source-audit entry point intentionally differs from this streaming entry point.

## Exact approved replacement

Only **analytics-dev / 453711491609 / us-west-2** may be used locally.

| Pin | Value |
|---|---|
| Review | [review.completion-fix.proposed.json](../evaluations/bedrock-streaming/review.completion-fix.proposed.json) |
| Preparation | [completion-fix.preparation.json](../evaluations/bedrock-streaming/completion-fix.preparation.json) |
| Preparation file SHA-256 | `e9fc7e4711290b058f849b15bbfb4c0786ca083caf1819bfb1b92d8468597e79` |
| Review semantic SHA-256 | `67f3f3aab2a086ad16633e6cdc2195edbe02543065a4b5934c7b1177345ea58c` |
| ZIP | `artifacts/bedrock-streaming/completion-fix/candidate/agent.zip` |
| ZIP SHA-256 | `8cfe8d9bd667c29c871342844898061f986107d94f309f1eef471f09582a4ae8` |
| ZIP bytes | `39302720` |
| Full source SHA-256 | `cc4a0c06b1b8d9ea672d2fd048e56eea7ecdfb2216cf6570c8c7a7076ff98a35` |
| New S3 key | `releases/8cfe8d9bd667c29c871342844898061f986107d94f309f1eef471f09582a4ae8/agent.zip` |
| New VersionId | **PQbNv3gkC1HwVYNNiAe95r1XuQDkfKvb**, actual one-time upload; retained after restoration |
| Retained streaming ZIP SHA | `c136a3931e2af31d6453c54910ddc9e839ef03e69a6f2ddebb35b3eb7cfdc306` |
| Retained streaming VersionId | `GSY36sTbDpCNZGogULTe3cBL__bujiQK` |
| Candidate assembly | `artifacts/bedrock-streaming/completion-fix/cdk.proposed.out` |
| Reproduction assembly | `artifacts/bedrock-streaming/completion-fix/cdk.verification.out` |
| Original assembly | `artifacts/bedrock-streaming/cdk.recovery.proposed.out` |
| Configuration | [streaming.completion-fix.proposed.json](../infrastructure/cdk/streaming.completion-fix.proposed.json) |

Both archive reproductions are byte-identical. Both syntheses reproduce all ten
templates and assembly files byte-for-byte. Each template differs from its deployed
baseline only in the new ZIP prefix/checksum output and the workload role's exact
old-plus-new ZIP read resources. Runtime names/roles, models/routing, trusted scope,
retail publication, limits, networking and both inbound policies are unchanged.
`ArtifactVersionId` remains a required parameter with no default; no guessed
VersionId or edited post-upload template is necessary.

There are **no new stacks, roles, query-trust additions or administrator managed
policy attachments** in this proposal. The ten existing workload inline policies
add `s3:GetObject`/`s3:GetObjectVersion` on only the new key while retaining the old
key for rollback. The supplied active M4 policy already contains execution-role
code reads on `releases/*/agent.zip`; the streaming role policy already covers
inline-policy updates on these ten roles. This is policy-content/attachment
evidence from the recorded administrator reports, not a fresh effective-access
simulation. Do not repeat denied IAM inspection or add speculative grants.

## Approved allocation — historical execution, now blocked

The versioned continuation selector is **bedrock-stream-completion-v1-01**. Its
review pins the original review, closed journal, acceptance claim and complete
16-file parent inventory. Read-only verification creates neither a ledger nor a
claim. An approved operator must acquire one exclusive parent-keyed continuation
claim before deployment; a different selector or repeated operator claim fails.
Every question/SDK reservation rechecks the immutable parent. Neither the parent
nor any earlier campaign is reopened or reset.

| Allocation | Attempts |
|---|---:|
| Historical repair usage, already closed | 3 |
| New unchanged acceptance: Q18 plus all-five, for each of ten models | 20 |
| Later user questions across local Bedrock/AWS modes | 15 |
| New protected retained-v15 cleanup smoke | 1 |
| Unapproved reserve, unavailable | 1 |
| Aggregate ceiling | **40** |

The approved child ceiling was **37**, with **35 ordinary** slots, one protected
cleanup and one unavailable reserve. The usable allocation allowed at most **36
new question attempts**, aggregate **39**, and reduced the original 18 user slots
to 15 to fund fresh acceptance and cleanup. This reallocation was explicitly
approved. The failed execution used four calls and is now blocked; its numerical
remaining slots are not available for questions or another operator attempt.
Expiry remains **2026-11-15T23:59:00Z** (5:59 p.m. CST). Expiry does not reset a
counter. Require at least **ten hours** for bounded sequential updates and rollback before
starting. No automatic billable retry or additional warm-up is included; Q18 is
each model's warm-up. Limits remain six model calls, 12,000 combined tokens and
90 seconds per question. These are usage limits, not a dollar-cost guarantee;
model, AgentCore, Athena and retained-storage costs still apply as documented in
the [original cost plan](bedrock-multimodel-streaming-plan.md).

## Reviewed execution and restoration sequence — executed once

1. Verify the exact source/archive/configuration/assembly and preservation pins,
   closed parent, current process guards and sufficient remaining time offline.
2. With explicit read-only mode, verify STS identity, canonical S3/Glue publication,
   exact retained legacy v15, and all ten existing v1 StackIds, templates,
   parameters, Runtime/DEFAULT configuration/artifact/policies and seven-day
   retention. Stop on unexplained drift or unavailable proof.
3. After approval binding both review and preparation hashes, acquire the exclusive
   operator/continuation claims. Conditionally upload the new ZIP once with
   `IfNoneMatch=*`, explicit SHA256 and SDK retries disabled. Preserve intent before
   dispatch and record/read back the actual S3 VersionId; never retry an ambiguous
   upload or overwrite an existing key.
4. Update existing targets sequentially under the global lease. Reuse the bounded
   deployment controller with each exact StackId/template and the existing
   CloudFormation execution role. Reconcile the full template/parameters and
   Runtime/DEFAULT artifact/configuration/policies before and after owned-process
   cleanup. READY or a local CDK exit code alone is insufficient.
5. Bind all actual resulting versions only after all ten strict proofs pass. Run
   the unchanged twenty acceptance questions once, reserving every attempted SDK
   call durably before dispatch. Require independent complete requests/results and
   real validated provider words; stop on the first failure.
6. On success, retain the matching candidate and enable the UI only after its
   review-bound all-ten acceptance record exists. Startup and model selection
   submit no question. The fifteen interactive attempts remain user-owned.

After **any attempted update** followed by failure/interruption, stop ordinary
dispatch. Once the process guard and CloudFormation state permit safe restoration,
restore every attempted target using the original corrected assembly and retained
streaming ZIP VersionId. Observe and verify actual resulting Runtime/DEFAULT
versions; restoring old code does not restore the number `1`. Then perform one
counted protected Q18 smoke against the untouched legacy v15, requiring **110.25
USD [2025-03-31, 2025-04-01)**. Preserve primary and restoration diagnostics. If a
process/update remains unresolved, record restoration-required and stop instead of
overlapping another mutation. Collect complete denial evidence before proposing
permissions. No source publication, data-layer deployment or old-ledger use occurs.

## Concrete commands

The following commands record the completed approved execution from the original
checkout with `enterprise-analytics` activated. The actual approval is retained at
`artifacts/bedrock-streaming/completion-fix/approval.json`, binding both hashes.
**Do not repeat execute, evaluation, restoration or smoke:** the one-time claim is
held, the child is blocked, and restoration already passed. Offline inspection is
read-only; quota or expiry cannot reopen this execution.

```sh
conda activate enterprise-analytics
export PYTHONPATH=.
export AWS_EC2_METADATA_DISABLED=true
export AWS_MAX_ATTEMPTS=1

poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan evaluations/bedrock-streaming/completion-fix.preparation.json verify-offline

streaming_check_id="$(date -u +%Y%m%dT%H%M%SZ)"
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan evaluations/bedrock-streaming/completion-fix.preparation.json \
  preflight --read-only-aws \
  --output "artifacts/bedrock-streaming/completion-fix/preflight-$streaming_check_id"
```

Historical approved invocation: one fresh operation directory was used. The command repeats fresh
preflight, uploads once, updates sequentially, evaluates and performs mandatory
failure restoration as one guarded operation. It requires at least ten hours
before expiry to start and records the actual returned versions.

```sh
streaming_run_id="$(date -u +%Y%m%dT%H%M%SZ)"
streaming_run_dir="artifacts/bedrock-streaming/completion-fix/operations-$streaming_run_id"
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan evaluations/bedrock-streaming/completion-fix.preparation.json \
  execute --execute-approved \
  --approval artifacts/bedrock-streaming/completion-fix/approval.json \
  --output "$streaming_run_dir"
```

If interrupted, inspect the retained operation claim, process journal and actual
CloudFormation state first. Do not repeat `execute`. When the process is resolved
and all targets permit restoration, the already approved restoration-only command
uses the same original operation, a new report directory, and the unused protected
smoke. It does not upload, evaluate, reacquire the continuation claim or reopen a
ledger. A completed/spent restoration cannot repeat its smoke.

```sh
streaming_restore_id="$(date -u +%Y%m%dT%H%M%SZ)"
poetry run python -m infrastructure.agentcore.streaming_completion \
  --plan evaluations/bedrock-streaming/completion-fix.preparation.json \
  restore --execute-approved \
  --approval artifacts/bedrock-streaming/completion-fix/approval.json \
  --operation "$streaming_run_dir" \
  --output "artifacts/bedrock-streaming/completion-fix/restoration-$streaming_restore_id"
```

After the operation reports acceptance and its review-bound twenty-question proof
exists, use the actual release record produced by that operation. Stop only a
verified task-owned previous UI process if port8501 is occupied; do not kill an
unrelated process. Starting this server makes no question or model call.

```sh
poetry run python -m enterprise_analytics_agent.ui --port 8501 \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1 \
  --streaming-review evaluations/bedrock-streaming/review.completion-fix.proposed.json \
  --streaming-releases "$streaming_run_dir/releases.actual.json" \
  --streaming-approval artifacts/bedrock-streaming/completion-fix/approval.json --allow-live
```

This live launch is currently **unavailable**: all twenty gates did not pass. Do
not start it with partial acceptance. The default offline playground remains
available at **http://127.0.0.1:8501**. Local Bedrock usage remains an
explicit billable choice; default playground and saved reports remain offline.
The proposed fifteen interactive questions never became available; the child is
blocked after failure. They are not permission for another operator attempt.

## Read-only Sonnet authorization handoff

Observed: **Converse → AccessDeniedException at 2026-11-12T22:19:28.946Z** on the
configured Sonnet Runtime. Its application metadata/logs retain only the exception
class, not the original SDK Error.Message or RequestId. The denied session
principal, resource and conditions cannot be identified from that class alone.
Bounded CloudTrail samples and the operator's 444-event failure capture did not
contain the underlying invocation denial. Duplicate/conflicting log-resource
operations in that capture are not evidence of the Bedrock failure's cause.

Read-only developer checks show the Sonnet profile is ACTIVE with exactly the
three reviewed US foundation-model ARNs, and agreement/entitlement/region are
AVAILABLE with authorization AUTHORIZED. Those are control-plane observations;
they are not the workload role's effective-access proof. The developer identity's
previously denied IAM inspection was not repeated. No new grant is proposed.

An administrator should inspect the **actual role** below read-only, preserving
all existing policies:

- Role: `arn:aws:iam::453711491609:role/enterprise-analytics-stream-claude-sonnet-5-5`.
- Active inline policy documents, attached managed policies' default versions,
  permissions boundary and role tags; verify the actual policy against the
  reviewed restored template. PowerUser SSO policy coverage does not substitute
  for this separate workload role.
- Simulate `bedrock:InvokeModel` for the failed Converse path, and
  `bedrock:InvokeModelWithResponseStream` for the prospective presenter, against
  each of these exact resources:

```text
arn:aws:bedrock:us-west-2:453711491609:inference-profile/us.anthropic.claude-sonnet-5-5
arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-5-5
arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-5-5
arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-sonnet-5-5
```

Return full simulator decisions, resource-specific results, matched statements,
missing context and boundary/organization details, plus any actual full invocation
denial available to the administrator. Query required context first and supply
only real observed context: requested region **us-west-2**, the Sonnet role ARN,
and any actual required tags/profile context. Do not override/exclude policies or
invent missing context to obtain an allowed result. A missing-context implicit
deny is not proof of a missing grant, and an allowed simulation is not live
acceptance. No grant, trust edit, model retry or permission change is requested.

The API/action relationship and simulator limitations are documented in the
[AWS Converse reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
and [IAM simulator guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_testing-policies.html).
[Model availability](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock/client/get_foundation_model_availability.html)
is a separate read-only control-plane check. Preserve the sealed review and
failed attempt. After evidence establishes a concrete cause, prepare a separately
reviewed correction/checkpoint/allocation before asking to execute again; no
replay or new cleanup is authorized by the unused numerical quota.

## References

The existing implementation and proposed operator were checked against current
official [CDK deployment options](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-deploy.html),
[AgentCore runtime updates](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_UpdateAgentRuntime.html)
and [Boto3 conditional/checksummed S3 uploads](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html).
Offline checks retain their historical attribution. Actual execution and exact
f591498 hosted CI are recorded above and in [progress](progress.md); the replacement
passed only the two Nova live gates and failed full multi-model acceptance.
