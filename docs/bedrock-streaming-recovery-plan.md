# Bedrock streaming deployment recovery proposal

Status: **recovery deployed; acceptance stopped safely; campaign closed 3/40**.
The focused source correction and guarded replacement are now implemented and
prepared offline in [the completion plan](bedrock-streaming-completion-plan.md).
That separate proposal does not reopen this historical campaign or authorize
additional calls.
The user approved this recovery at **7dad05a**; the
[approval record](../evaluations/bedrock-streaming/recovery-approval.json) binds its
unchanged review/execution hashes. Fresh preflight **20261112T200119Z** passed,
the reviewed unused Nova stack was deleted, and all ten corrected replacements
verified **CREATE_COMPLETE / Runtime and DEFAULT READY v1** at **20:20:07Z**,
with exact artifact/configuration/policies and seven-day retention. The
[deployment checkpoint](../evaluations/bedrock-streaming/recovery-deployment-checkpoint-2026-11-12.json)
preserves the deployment-window identifiers and proof hashes alongside the later
failure/cleanup status. Deployment success does not establish model acceptance.

The administrator-applied saved trust at **20:22:58Z** matches the exact merged
policy SHA **3d2b5cd161956ae147c825cc71d28b977d03e24e909f21eea50d508b41203ec1**,
preserving both prior statements and adding exactly ten deployed role principals.
Release binding passed. Nova Q18 passed the complete request, **110.25 USD** and
provider streaming. Its all-five question had exact requests and golden values,
but failed `token_limit` before presentation. Only **3,215 reported tokens** were
used; offline replay reproduced an **8,369-byte** conservative conversation-input
reservation blocking the next planner turn. The actual full live transcript was
not retained; that size is an offline reproduction, not an exact live request
measurement. No permission error or higher token ceiling follows from this result.
The [acceptance failure record](../evaluations/bedrock-streaming/acceptance-failure-2026-11-12.json)
preserves exact comparisons and raw-evidence hashes, including the separate
7,514-byte minimum reservation bound established from retained content.

No other target was invoked and no accepted UI binding exists. Protected cleanup
smoke passed on unchanged legacy **v15** around **20:26Z**; the campaign is now
closed **3/40**, comprising two ordinary attempts and one cleanup. Reserve remains
untouched/unapproved. Frozen ZIP/source/version, data, goldens, existing permissions
and historical campaigns remain intact; no automatic retry occurred. Evidence:
`artifacts/bedrock-streaming/acceptance-recovery/` and `cleanup-recovery.json`.
Initial failures and the approved commands below are historical evidence, not
instructions to replay this closed campaign.

## Historical initial checkpoint

Only **analytics-dev / 453711491609 / us-west-2** may be used locally. No profile
creation or administrator assumption is permitted.

- The administrator's `streaming-directory-verification.json`, SHA-256
  `2c1b01a6e182da96dd4a155ebb5e3fb8318978c94cf01473eb86b4f616b063f6`,
  confirms the exact approved inline policy, all four preserved managed-policy
  attachments, and the unchanged directory simulation **allowed**, missing
  context empty. This is administrator readback/simulation evidence.
- Fresh operator preflight passed at `2026-11-12T19:01Z`: expected STS caller,
  retained v15, canonical publication, all native access/profile gates and Mantle
  project, source/package/templates and process guards. Before deployment, only
  the recorded conditional upload existed.
- The new ZIP was uploaded **once** with conditional creation and explicit SHA256.
  Actual VersionId: **GSY36sTbDpCNZGogULTe3cBL__bujiQK**; bytes **39298651**;
  SHA-256 **c136a3931e2af31d6453c54910ddc9e839ef03e69a6f2ddebb35b3eb7cfdc306**.
  Do not rebuild, upload again, replace the key, or reuse a historical VersionId.
- One new stack, **enterprise-analytics-stream-nova-lite**, is
  **CREATE_COMPLETE**. Its Runtime and DEFAULT are **READY v1**, but deployment
  acceptance stopped on resource-policy verification. The other nine targets
  were not deployed; no new release bindings or UI activation exist.
- Exact stack to recreate:
  `arn:aws:cloudformation:us-west-2:453711491609:stack/enterprise-analytics-stream-nova-lite/89307e20-decb-11f1-81c6-0affd1492891`.
  Exact Runtime:
  `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/enterprise_analytics_stream_nova_lite-PYEiLA6Tud`.
- Retained original Nova Runtime/DEFAULT **READY v15** passed complete read-only
  verification at **2026-11-12T19:11:25Z**. Its artifact/configuration/policies,
  existing data layer, permissions and historical ledgers were preserved.
- Streaming usage remains **0/40**. No Runtime/model invocation, Athena query,
  acceptance claim, reservation or ledger reset occurred. No cleanup smoke was
  needed to restore the untouched legacy deployment.

Raw proof, both policy readbacks, CloudFormation events, CDK output and complete
CloudTrail events are retained under
`artifacts/bedrock-streaming/operations/20261112T190109Z/deployments/`.
The initial pre-dispatch callback error is separately preserved under
`artifacts/bedrock-streaming/operations/20261112T185007Z/deployments/`: it mishandled
a wrapped expected stack-not-found result before CDK started. Its local correction
passed eight offline cases and fresh empty-inventory proof before the single real
deployment. It was not an AWS authorization failure or a repeated create request.

## Diagnosed issues and exact changes

The strict verifier found two **representation** differences in both inbound
resource policies: AWS returns a single `Principal.AWS` ARN and a single
`ArnNotEquals.aws:PrincipalArn` value as strings rather than singleton arrays.
The allowed principal, resources, actions and deny conditions are unchanged.
The CDK-only fix emits scalar values for one caller and keeps arrays for multiple
callers. It does not weaken the frozen application verifier or normalize final
acceptance. The original failed exact comparison remains evidence.

Separately, CloudTrail records a real **logging** denial at **19:02:46Z**:

- Principal: assumed workload role **enterprise-analytics-stream-nova-lite**,
  session `BedrockAgentCore-ed855948-2d8a-44c8-bb73-dabbf7014b70`.
- Action: **logs:PutResourcePolicy**.
- Resource:
  `arn:aws:logs:us-west-2:453711491609:log-group:/aws/bedrock-agentcore/runtimes/enterprise_analytics_stream_nova_lite-PYEiLA6Tud-DEFAULT`.
- Reason: no identity-based Allow. This is a workload-role logging request;
  the successful CreateAgentRuntime used the reviewed CloudFormation role.
- Event ID **a2e86f89-a23e-37d3-883e-79823c5cc032**; request ID
  **a3014671-40fc-4964-88e5-20c60c1f28af**. `requestParameters` and
  `responseElements` are null; there is no `responseElements.message` to quote.
  The complete `errorMessage` is preserved. Additional session-index lookup
  returned zero rows and is not proof that no other future permission gaps exist.

AWS's [direct-deployment execution-role documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)
includes this action on the agent's own log-group namespace. The proposed addition
is **one separate statement per workload role**, with action
`logs:PutResourcePolicy`, resource
`arn:aws:logs:us-west-2:453711491609:log-group:/aws/bedrock-agentcore/runtimes/<that-model-runtime-name>-*`,
and `aws:RequestedRegion=us-west-2`. It grants no sibling-model, legacy, foreign
account/region or account-wide policy resource. No other logging action is added.
It does not change the CloudFormation execution-role policies, shared-directory
grant, S3/data/Bedrock permissions, caller trust or public semantic contracts.

## Approved recovery candidate

- [Recovery review](../evaluations/bedrock-streaming/review.recovery.proposed.json):
  **10433404c65249308e326a5867d499cabe4fab24c43201a6639a29c769b946c4**.
- [Preparation and per-template diff proof](../evaluations/bedrock-streaming/recovery-preparation.proposed.json).
- [Exact execution/resource/helper pins](../evaluations/bedrock-streaming/recovery-execution.proposed.json).
- Assembly: `artifacts/bedrock-streaming/cdk.recovery.proposed.out`.
  Separate reproduction: `artifacts/bedrock-streaming/cdk.recovery.verification.out`.

All ten templates reproduce byte-for-byte. Comparing each to its original
template proves that only the two singleton representations and the one scoped
workload logging statement changed. All other resources/properties are identical.
Original templates/reviews/configuration and every historical artifact remain
unchanged. The frozen **76-file** source closure and ZIP still match; this change
is solely in CDK and its infrastructure tests, outside the packaged agent source.
The real uploaded VersionId remains a required deployment parameter, not a new
default or a guessed value.

## Approved execution sequence — executed; do not replay

1. Repeat read-only preflight. Require the exact untouched legacy v15 and the
   exact unused new Nova v1/stack above, its original template/parameters and
   source/artifact/configuration. The baseline helper accepts only the two known
   singleton representation changes for **inspection**, preserving all raw
   responses; this is not final acceptance. Require all other nine targets absent,
   matching source/data/model bindings, valid expiry and process guards.
2. Inspect the preserved failed process journal. Require its pinned bytes,
   inactive/reaped task-owned process and exact observed Nova baseline. Archive
   it before recording explicit inspection resolution. Do not clear an unknown
   process or bypass a retained unresolved journal.
3. Delete **only the exact unused new Nova stack ID above**, once. Its five CFN
   resources have no Retain policy; they are its role, inline policy, Runtime and
   two inbound policies. Keep the manually created seven-day log group,
   uploaded code, evidence, shared directory, foundation, M3 data layer,
   query-role trust and legacy v15. Poll deletion for at most **1200 seconds**,
   then require the old Runtime absent within **300 seconds** before any create.
   This fresh creation ensures logging initialization first sees the corrected
   workload permission. There is no description-only forced version update.
4. Create the ten corrected stacks sequentially with the same uploaded VersionId.
   Use the pinned supervisor: **900 seconds** per CDK deployment, bounded reads,
   exact template/parameters/configuration/Runtime/DEFAULT/policies/S3/log-retention
   proof before and after bounded owned-process cleanup. Preserve logs and
   actual identifiers. Never accept READY alone or rerun a mutation after timeout.
   CDK publishes corrected template assets; it does not upload another ZIP.
5. Apply seven-day retention only to each actual new target's log group. Once
   all ten roles exist, the administrator applies the already reviewed
   [query-role trust addition](../infrastructure/cdk/streaming-query-trust-additions.proposed.json),
   comparing current trust and preserving developer/legacy principals. Do not
   apply it while nine roles are absent. The prepared merged handoff under
   `artifacts/bedrock-streaming/query-trust-handoff/` is based on historical trust;
   it must match current trust before use. Obtain actual readback before calls.
6. Bind all ten actual releases with the unchanged production verifier. Perform
   the original **20** AWS questions, with every receipt reserved before dispatch
   and no automatic billable retries. Enable the new UI only after every exact
   structured-result and provider-word gate passes.

## Historical operator commands — closed campaign

Use the existing Conda Python/Poetry environment. These operator files are pinned
local preparation artifacts, not new runtime-package files. Stop if a required
file is missing/different; do not reconstruct a fake checkpoint or rewrite pins.
The recovery driver has an explicit execution gate and needs a separately
approved recovery record at `artifacts/bedrock-streaming/approval.recovery.json`.
The execution copy now exists following explicit approval; the committed
[approval record](../evaluations/bedrock-streaming/recovery-approval.json) preserves
the authorization. Both bind the recovery review SHA, unchanged maximum/expiry, and
`execution_proposal_sha256` **ee90ac77cd3c689e23c150d0e7f1e1ca2032cca3ffd2f52595f2b4c9e17bf0f7**.
The driver verifies that exact proposal and all six non-aliased operator-source
checksums before importing helpers, creating its claim or constructing a session.

```sh
poetry run python -m enterprise_analytics_agent.adapters.model_stream_cli \
  --review evaluations/bedrock-streaming/review.recovery.proposed.json verify-offline

# Read-only fresh baseline; no upload, deployment or invocation.
poetry run python artifacts/bedrock-streaming/recovery/operator/preflight.py

# Only after the exact recovery review has been explicitly approved and recorded.
poetry run python artifacts/bedrock-streaming/recovery/operator/deploy.py --execute-approved
```

The driver holds the global operator/deployment lease, creates a single durable
recovery claim before dispatch, pins the exact old stack and S3 version, and
preserves an unresolved-delete guard on failure. It stops after deployment for
the administrator trust handoff. Do not rerun it on interruption: inspect the
claim/journal and actual AWS state first, then prepare a resume checkpoint without
repeating deletion/creation or changing counters.

After all deployments, actual query trust and authorization are verified:

```sh
poetry run python -m enterprise_analytics_agent.adapters.model_stream_cli \
  --review evaluations/bedrock-streaming/review.recovery.proposed.json \
  bind-releases --read-only-aws \
  --upload-response artifacts/bedrock-streaming/upload-response.json \
  --output artifacts/bedrock-streaming/releases.recovery.actual.json
poetry run python -m enterprise_analytics_agent.adapters.model_stream_cli \
  --review evaluations/bedrock-streaming/review.recovery.proposed.json \
  --releases artifacts/bedrock-streaming/releases.recovery.actual.json \
  --approval artifacts/bedrock-streaming/approval.recovery.json \
  evaluate --invoke-live --output artifacts/bedrock-streaming/acceptance-recovery
```

Only after all twenty checks pass, use this separate reviewed UI configuration:

```sh
poetry run python -m enterprise_analytics_agent.ui --port 8501 \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1 \
  --streaming-review evaluations/bedrock-streaming/review.recovery.proposed.json \
  --streaming-releases artifacts/bedrock-streaming/releases.recovery.actual.json \
  --streaming-approval artifacts/bedrock-streaming/approval.recovery.json --allow-live
```

Use fresh report paths once; never replace a partial acceptance claim or retry a
failed question. If a new denial occurs, stop, collect complete parent/nested
CloudTrail events and diagnose its principal/action/resource/context before any
new permission proposal. Keep the failed attempt and remaining protected slot.
The legacy v15 is never redeployed by this recovery. Its protected cleanup smoke
is available only for the original approved failure/cleanup purpose and within
expiry; no extra warm-up, demonstration or reserve use is included.

## Budget, expiry and remaining gates

Campaign **bedrock-stream-models-v1-01** is closed **3/40**, after two ordinary
attempts and the protected v15 cleanup. Do not reopen/reset its claim or ledger.
Its original approved allocation was: authored acceptance
**20**, later user-owned questions **18**, protected v15 cleanup **1**, controlled
reserve **1 unapproved**. Each model's Q18 is its warm-up. Same expiry
**2026-11-15T23:59:00Z**. The approved driver required sufficient bounded execution
time plus cleanup allowance, conservatively five hours remaining before starting.
Neither unexpired time nor unused quota reopens this closed attempt. No budget
extension or dollar-cost guarantee is requested.
Model/AgentCore/Athena/storage prices and the original per-question limits remain
those of the [original approved plan](bedrock-multimodel-streaming-plan.md).

Offline checks establish implementation/preparation readiness. They do not prove
that logging delivery or all ten model integrations pass live acceptance. This
plan is not a production-readiness claim. The exact corrected templates, narrow
workload logging grant and scoped recreation sequence were approved and executed;
all ten deployment proofs and administrator trust readback passed. Live acceptance
failed safely and cleanup passed. Next prepare the focused offline source
correction/regressions and a new candidate/review. No remaining quota, reserve,
upload, deployment, retry or new live allowance is authorized here.
