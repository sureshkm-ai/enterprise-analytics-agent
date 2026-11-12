# Streaming completion correction and remaining acceptance

Status: local implementation and replacement preparation; **not deployed or
live-accepted**. This plan supersedes neither the historical approvals nor the
closed campaign. The exact replacement and remaining allocation need approval
before upload, IAM inline-policy changes, deployment or billable execution.

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

## Exact proposed replacement

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
| New VersionId | **Not uploaded; bind only the actual returned VersionId** |
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

## Remaining allowance

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

The child ceiling is **37**, with **35 ordinary** slots, one protected cleanup and
one unavailable reserve. Thus at most **36 new question attempts** can run under the proposed
usable allocation, aggregate **39**; the reserve needs separate approval. The
original 18 user slots become 15 to fund complete replacement acceptance and a
fresh protected cleanup. This reallocation is proposed, not already approved.
Expiry remains **2026-11-15T23:59:00Z** (5:59 p.m. CST). Expiry does not reset a
counter. Require at least **ten hours** for bounded sequential updates and rollback before
starting. No automatic billable retry or additional warm-up is included; Q18 is
each model's warm-up. Limits remain six model calls, 12,000 combined tokens and
90 seconds per question. These are usage limits, not a dollar-cost guarantee;
model, AgentCore, Athena and retained-storage costs still apply as documented in
the [original cost plan](bedrock-multimodel-streaming-plan.md).

## Proposed execution and restoration

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

Run from the original checkout with `enterprise-analytics` activated. Do not use
these execution commands before approval. The operator records approval from the
owner's explicit response, binding both hashes above; no approval file exists yet.

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

Only after approval, use one fresh operation directory. The command repeats fresh
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

The application opens at **http://127.0.0.1:8501**. Local Bedrock usage remains an
explicit billable choice; default playground and saved reports remain offline.
The fifteen interactive questions belong to the user and are not automated demos.

## References

The existing implementation and proposed operator were checked against current
official [CDK deployment options](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-deploy.html),
[AgentCore runtime updates](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_UpdateAgentRuntime.html)
and [Boto3 conditional/checksummed S3 uploads](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html).
Offline results and exact executable preparation/execution commands are recorded
in [progress](progress.md) and the preparation manifest. No hosted CI or deployed
acceptance is claimed for the replacement by these local checks.
