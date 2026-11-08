# Milestone 4 AgentCore deployment and live-test plan

Recovery checkpoint **2026-11-08 — Version 4 attempt**. The administrator-reported active M4 policy V4 exactly matches pushed `a5b690c`. The approved corrected assembly was retried once after preserving/deleting the empty failed stack. **Creation failed on default workload-identity directory tagging. Milestone 4 remains open; 0/40 Runtime invocations used.** The directory-only permission below is prepared locally and unapplied. No warm-up, retention update, live suite or variant restoration ran. The corrected templates, ZIP and uploaded VersionId remain unchanged and already approved.

## Current recovery result and minimum additional IAM correction

The user confirmed `a5b690c` was pushed and hosted CI runs [42502992593](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42502992593) and [42502997060](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42502997060) passed. Those hosted offline results cover that commit, separately from the new local proposal and unrun live acceptance. All current AWS calls used only `analytics-dev`, account `453711491609`, region `us-west-2`, after explicit STS identity verification. V4 application/default-version evidence is administrator-reported; the supplied JSON exactly matches the committed file (SHA `edda39f7f695cc44b763eea12598c7ce5b501048a0ab445c0204889a7cb94fb9`). No IAM write was performed by the agent.

The old runtime stack was ROLLBACK_COMPLETE with no surviving resources or matching Runtime. Its full evidence was preserved in ignored `artifacts/agentcore/v4.before-delete.json` before approved deletion, which completed. The corrected base assembly `artifacts/cdk.agentcore.endpoint-fix.out`, SHA `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`, was then deployed with verified existing S3 VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`. Creation failed; new stack is **ROLLBACK_COMPLETE**, suffix `d2c0dc90-db99-11f1-81e0-02cde3d69019`. Final full service pagination finds no matching Runtime; the denied identity returns ResourceNotFoundException. Foundation remains CREATE_COMPLETE and data layer UPDATE_COMPLETE. Reviewed template comparisons confirm retained foundation/query trust/data state. No bootstrap, publication, upload, foundation/trust update or M3 permission change was repeated.

Complete parent and child CloudTrail records are retained in `artifacts/agentcore/v4.denials.json` (sanitized access-key identifiers), with failure events and final state alongside them. The parent's full **`responseElements.message`** is:

> User: arn:aws:sts::453711491609:assumed-role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2/AWSCloudFormation is not authorized to perform: bedrock-agentcore:TagResource on resource: arn:aws:bedrock-agentcore:us-west-2:453711491609:workload-identity-directory/default because no identity-based policy allows the bedrock-agentcore:TagResource action (Service: BedrockAgentCoreControl, Status Code: 403, Request ID: 79af8502-c9ee-4003-8315-bd0bb29a0f61) (SDK Attempt Count: 1)

| Fact | Verified evidence |
| --- | --- |
| Time | `2026-11-08T17:28:44Z` (11:28:44 America/Chicago) |
| Parent CreateAgentRuntime request | `bfe5f689-1552-443f-892d-7baf1c4ddcbd` |
| Nested CreateWorkloadIdentity request | `79af8502-c9ee-4003-8315-bd0bb29a0f61` |
| Actual CloudFormation execution role | `arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`, confirmed by stack RoleARN and CloudTrail issuer |
| Nested tags / identity | `Project=enterprise-analytics-dev`, `Milestone=4`, CloudFormation tags; `enterprise_analytics_dev_agent-RRZqgv4r4W` |
| Child message field | `responseElements.Message` (uppercase); full same identity/action/resource/reason denial without parent's service/status/request/attempt suffix |
| Cause | V4 authorizes tagging the named identity, but lacks TagResource on the exact directory ARN also checked during its creation. |

**Prepared proposal:** add only this separate statement to [the existing M4 policy](../infrastructure/cdk/agentcore-deployment-policy.development.json):

```json
{
  "Sid": "TagAutomaticRuntimeWorkloadIdentityDirectory",
  "Effect": "Allow",
  "Action": ["bedrock-agentcore:TagResource"],
  "Resource": "arn:aws:bedrock-agentcore:us-west-2:453711491609:workload-identity-directory/default",
  "Condition": {
    "StringEquals": {
      "aws:RequestedRegion": "us-west-2",
      "aws:PrincipalAccount": "453711491609",
      "aws:RequestTag/Project": "enterprise-analytics-dev"
    }
  }
}
```

All V4 statements and M3 permissions remain intact. Removing only this addition reproduces the entire supplied V4 (canonical SHA `7160dae5f016fa634e29fdf9c88a8278914efd270f53a7b0d849636413a14143`), independently guarded alongside V1/V2/V3 preservation. Proposed full file SHA **`ac2942537a6d917b899d3a156efd328953d6176f152b9db925b5e5a13c104419`**. The new regression fails on active V4 and passes with the proposal. Read-only Access Analyzer reports zero findings; this is not live authorization proof.

The [official authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html) lists both identity and directory resources for CreateWorkloadIdentity, and request-tag conditions for directory TagResource. Keep the Project condition: the nested request supplies it. The default directory is a **shared account/region resource**; its exact ARN cannot limit this new tagging grant by runtime name. Submitted Project tags constrain requests, not directory ownership. This is an explicit shared-directory exception, with no directory wildcard or unrelated actions. Reattaching unchanged V4 cannot resolve the missing grant.

An administrator must review/approve this additional permission and apply it as a new default version of the existing M4 policy, retaining V4 for rollback. The proposal is **local and unapplied**; no further retry followed this failure. The already-approved corrected templates/code need no changes or renewed template approval. Recovery continuation awaits that IAM approval/application and authorization to resume.

Then use the scoped failed-stack recovery commands below after rechecking/preserving the latest empty stack. Reuse the corrected base assembly and retained VersionId. Do not repeat foundation, trust, upload, bootstrap or publication. Require Runtime/DEFAULT READY before ledger-counted warm-up, seven-day log retention and the three authored suites (18 + 3 + 3 tests). After any variant attempt restore only the **corrected** parity-v1 base and verify READY, even if a suite fails. Original ledger remains **0/40**, with failed calls and retries included in the unchanged 40-call maximum. Successful planned execution uses 28 invocations. Capture complete parent/nested denial messages before proposing further grants. No current live result is claimed.

## Historical Version 3 identity-tagging recovery (`4727b1c` → `a5b690c`)

User-confirmed pushed `4727b1c` passed hosted CI [42297147399](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42297147399) and [42297155475](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42297155475). Supplied V3 matched that commit. Its corrected recovery failed at `2026-11-08T16:43:46Z`, parent request `84fd1184-9e49-4321-92df-c4eb5b58dc79`, nested request `4d57cf38-f993-4a41-9b63-36630bf41275`, on TagResource for `workload-identity-directory/default/workload-identity/enterprise_analytics_dev_agent-PUtFzA3UY3`. The same CloudFormation role and expected Project tag were confirmed. Stack `8b484200-db93-11f1-afab-0279724cff07` rolled back with no Runtime or denied identity; it was preserved/deleted in the V4 attempt above.

Commit `a5b690c` prepared `TagAutomaticRuntimeWorkloadIdentity`: TagResource on the existing runtime-name identity prefix, with exact region/account/Project conditions. Removing it reproduces supplied V3 canonical SHA `ece7e0db64342e9dce9994c0d8c832cdfcad38de3416fe357f53f6320f7f209f`. The administrator subsequently applied this as V4 and the user authorized recovery; it is applied historical evidence, not the current pending directory-only proposal. All earlier templates/code stayed frozen, and no invocation allowance was consumed.

## Historical Version 2 tagging recovery (`7360cc4` → `4727b1c`)

The user confirmed `7360cc4` was pushed and hosted CI runs [42292758353](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42292758353) and [42292764712](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42292764712) passed. V2 exactly matched that commit. Its approved recovery failed at `2026-11-06T21:14:23Z`, parent request `4074f7e9-3e5d-4278-a0d7-d48fe5f1a8b6`, on `bedrock-agentcore:TagResource` against `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/*`, under the same CloudFormation execution role. That failed stack ended ROLLBACK_COMPLETE with suffix `0357ee30-da27-11f1-be37-0a8587e72127`; it was preserved/deleted during the V3 recovery above.

Commit `4727b1c` added only TagResource to `CreateTaggedDefaultEndpointDuringRuntimeCreation`, preserving its runtime resource and region/account/Project conditions. Removing that action reproduces supplied V2 (canonical SHA `48939891d9f2183a398aa2918a8dcc374e33c6b3a1fbb821c135e31fc03dbac9`). The administrator subsequently applied this correction as V3, source file SHA `bf418e5de83729ecb5916b76d14ae7fd760187628fa77f9a5427c4cf42ddc35b`, and the user authorized continuation. It is historical applied evidence, not the current pending proposal. No Runtime was created and no invocation allowance was consumed in that attempt.

## Historical first failure and endpoint-creation correction (`c29e8cb` → `7360cc4`)

This section records the first denial and the earlier one-action endpoint correction. That endpoint-ARN template is now approved and the administrator reports its IAM correction active as V2. Current failure/correction status is above; do not treat the historical approval gates below as a request to reapprove unchanged templates.

Actual stack states: foundation `CREATE_COMPLETE`, data layer `UPDATE_COMPLETE`, runtime stack `ROLLBACK_COMPLETE`. No matching Runtime was returned by the service. The uploaded approved archive has S3 VersionId **`HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`**; its SHA-256 remains `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1`. No warm-up, retention update, dataset variant update, or live evaluation ran: **0/40 Runtime invocations**. There was no Runtime to restore; `parity-v1` remains the intended initial server configuration, not a verified running state.

CloudTrail records the failed `CreateAgentRuntime` at `2026-11-06T20:27:49Z`, request ID `8dcb800c-7f91-4598-8d0d-b9dc5d74c61e`. The detailed denial is in **`responseElements.message`**, not `errorMessage`:

| Authorization fact | Verified value |
| --- | --- |
| CloudFormation stack `RoleARN` | `arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2` |
| Denied session principal | `arn:aws:sts::453711491609:assumed-role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2/AWSCloudFormation` |
| Denied dependent action | `bedrock-agentcore:CreateAgentRuntimeEndpoint` |
| Denied resource | `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/*` |
| Reported reason | No identity-based policy allows that action on that resource. |

The user retrieved active default policy **Version 1** from the administrator console. It matches the committed policy at `c29e8cb`, independently corroborated by its successful CloudTrail `CreatePolicy` record at `20:07:58Z`. Global IAM audit events were read in `us-east-1`; deployment stayed in `us-west-2`. The execution role is confirmed both by CloudFormation and the CloudTrail session issuer. Reattaching the same policy will not change this denial.

The top-level `CreateAgentRuntime` statement allows `Resource: "*"` with exact region/account/Project request-tag conditions, which match the recorded request. The separate `NamedDevelopmentRuntimeLifecycle` statement allows endpoint creation only on `runtime/enterprise_analytics_dev_agent-*`; it does **not** match the `runtime/*` creation-time resource in the denial. There is no evidence for changing PassRole, runtime/query-role access, or optional feature permissions.

**Historical V2 IAM correction (now administrator-reported active):** commit `7360cc4` added one statement, `CreateTaggedDefaultEndpointDuringRuntimeCreation`, allowing only `bedrock-agentcore:CreateAgentRuntimeEndpoint` on `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/*`, with the same exact `aws:RequestedRegion`, `aws:PrincipalAccount` and `aws:RequestTag/Project` values. All original Version 1 statements are unchanged, protected by a frozen canonical-policy regression. The milestone 3 policy and its attachment are unchanged.

This widens only this action from a runtime-name prefix to the required account/region namespace. The supplied Project tag is a scope condition, not an ownership boundary. The [official authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html) supports the request-tag condition; the parent request has the expected tag. Propagation to automatic endpoint authorization still requires approved live validation. Keep the condition fail-closed; do not weaken it speculatively. Read-only Access Analyzer validation returned **zero findings**, which does not prove effective live authorization.

The administrator subsequently applied that endpoint-creation correction as default V2 of the **existing M4 managed policy**, with V1 retained for rollback; `analytics-dev` lacks the required IAM access. The V2 source at `7360cc4` had file SHA-256 `5687259426158d8e761554a0308718a0fdf7c42b266f46be7cc933930daac5c6`; a separate runtime-tagging correction at `4727b1c` was subsequently applied as V3. A separate identity-tagging correction at `a5b690c` was subsequently applied as V4. The working source now additionally proposes only the separate directory-tagging statement described above. Do not reattach policies or edit the existing M3 permissions. After approval, an explicitly selected administrator can use:

```sh
: "${ADMIN_PROFILE:?Set an explicitly approved administrator profile}"
test "$(aws sts get-caller-identity --profile "$ADMIN_PROFILE" --region us-west-2 --query Account --output text)" = 453711491609
aws iam create-policy-version \
  --policy-arn arn:aws:iam::453711491609:policy/enterprise-analytics-dev-agentcore-cdk-execution \
  --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json \
  --set-as-default --profile "$ADMIN_PROFILE" --region us-west-2
```

The original maximum of 40 Runtime invocations remains unchanged, with zero used. At that earlier checkpoint the resource-scope exception and corrected recovery awaited approval and no IAM update/retry had been executed. The administrator later applied V2 and the user approved the corrected recovery; current tagging results are recorded above. No extra model/runtime calls are requested. The complete sanitized denial and read-only audit evidence are retained under ignored `artifacts/agentcore/`.

A separate defect was found in the approved runtime template: DEFAULT endpoint ARNs use **`/runtime-endpoint/DEFAULT`**, according to the [official resource ARN reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html), but the template used `/endpoint/DEFAULT`. The local correction and SDK-pattern regression are prepared; they do not establish the cause of the earlier creation denial. The existing IAM runtime-name wildcard already covers the correct descendant, so this correction does not widen IAM permissions.

| Runtime proposal | SHA-256 / location |
| --- | --- |
| Originally approved and attempted at `c29e8cb` | `a287c414f51bec59051bec51c44c006fcc0118326195b63a377e2718dbe07799`; `artifacts/cdk.agentcore.reviewed.out` remains frozen |
| Corrected, approved for recovery; creation attempted and failed before policy creation | `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`; `artifacts/cdk.agentcore.endpoint-fix.out` |

Only three paths differ: the DEFAULT endpoint policy's `ResourceArn`, its JSON policy's endpoint resources, and `DefaultEndpointArn` output. Foundation bytes, Runtime ZIP, code key/version, model, trusted tenant/regions, caller principals and resource count are unchanged. Corrected legacy/empty-return proposals are synthesized under `artifacts/cdk.agentcore.endpoint-fix.<dataset-version>.out`. The original assemblies are preserved for audit.

The endpoint-ARN template/recovery is already approved. Further continuation now requires approval and administrator application of the separate exact-directory tagging addition above, preserving active V4 and M3 permissions. Then reverify the latest failed stack has no live resources, preserve its evidence, remove only that failed stack record, and retry using the unchanged corrected assembly and uploaded version:

```sh
# PROPOSED CONTINUATION: wait for the additional IAM statement to be approved/applied.
aws cloudformation describe-stack-resources --stack-name enterprise-analytics-dev-agent-runtime \
  --profile analytics-dev --region us-west-2
aws cloudformation delete-stack --stack-name enterprise-analytics-dev-agent-runtime \
  --profile analytics-dev --region us-west-2
aws cloudformation wait stack-delete-complete --stack-name enterprise-analytics-dev-agent-runtime \
  --profile analytics-dev --region us-west-2
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/cdk.agentcore.endpoint-fix.out enterprise-analytics-dev-agent-runtime \
  --parameters ArtifactVersionId=HSRXiFjg0w2W77InULH4.fn32Y.JH8b9 \
  --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices
```

Do not redeploy foundation, repeat the trust change, upload another archive, bootstrap, or publish datasets for this recovery. Once READY, resume the counted warm-up and authored suites using the existing operator ledger, then restore the **corrected** base assembly. Never restore the original assembly containing the wrong endpoint ARN. The original procedure below is retained for audit; substitute the approved corrected base/variant assemblies on recovery and do not replay completed steps. Detailed actual results and verification are in [progress](progress.md).

## Target and read-only evidence

| Setting | Reviewed value |
| --- | --- |
| Operator profile / account / region | `analytics-dev` / `453711491609` / `us-west-2` |
| Runtime / stacks | `enterprise_analytics_dev_agent`; `enterprise-analytics-dev-agent-foundation`, `enterprise-analytics-dev-agent-runtime` |
| Model inference profile | `us.amazon.nova-lite-v1:0` |
| Runtime implementation | Direct Python 3.12 Linux ARM64 ZIP, HTTP, platform `V1` explicitly pinned |
| Inbound authentication | AWS IAM/SigV4; one approved SSO role, on both runtime and DEFAULT endpoint |
| Server-owned authorization | Principal `analytics-development-runtime`, tenant `t1`, regions `North`, `South` |
| Acceptance dataset / reference date | `parity-v1` / `2025-02-01` |
| Other acceptance snapshots | `parity-legacy-v1`, `parity-no-returns-v1` through trusted deployment configuration only |
| Existing query role | `arn:aws:iam::453711491609:role/enterprise-analytics-dev-query-executor` |
| New runtime role | `arn:aws:iam::453711491609:role/enterprise-analytics-dev-agent-runtime` |
| New code bucket | `enterprise-analytics-dev-453711491609-us-west-2-agent-code` |

After the user renewed SSO, read-only STS verified the explicit profile/account/region. CloudFormation initially reported the data-layer stack CREATE_COMPLETE; it is now UPDATE_COMPLETE after the approved trust addition. Ready manifests, all 27 Glue table schemas, and object SHA-256/length metadata were verified for all four snapshots, including published `retail-v1`. Evidence is under ignored `artifacts/m4-snapshot-verification.json`. This verifies publication metadata, not a fresh Athena execution or a retail agent demonstration. Initial acceptance uses authored parity fixtures, not generated retail values.

Bedrock `GetInferenceProfile` reports ACTIVE and `GetFoundationModelAvailability` reports agreement/entitlement/region AVAILABLE and authorization AUTHORIZED for Nova Lite. Official documentation supports Converse client-side tools. **Inference access and tool behavior have not been proved by a model call.** The US inference profile can route from Oregon to **us-west-2, us-east-1, or us-east-2**; approval covers that US routing. SCPs and model quotas in those destinations can still prevent inference. No implicit default profile is allowed.

The user confirmed both scoped execution policies are attached and developer query-role trust was preserved. `iam:GetRole`/`iam:GetPolicy` inspection remains denied to the selected PowerUser SSO caller; the user has since supplied active Version 4 JSON matching `a5b690c`. The latest recovery identifies a separate exact-directory tagging denial; only that new proposal awaits administrator review/application. Do not repeat the completed attachment step below. Read-only Access Analyzer validation of the proposed policy returned `findings: []` after correcting two invalid S3 action names. This validates policy syntax/rules, not effective deployment privileges or service success.

## Exact resources and IAM changes proposed

The follow-up scope guard clarifies cross-dimension alternatives, unsupported coordinated groupings, unresolved date refinements, and unknown measures before accepting a partial tool plan. It preserves supported same-dimension alternatives, explicit conjunctions, governed metric comparisons and exclusive intervals. Metric definitions and IAM/resource scope are unchanged.

The reviewed source is [AgentCore configuration](../infrastructure/cdk/agentcore.config.development.json), [stacks](../infrastructure/cdk/agentcore_stack.py), [runtime configuration](../infrastructure/agentcore/runtime.development.json), and [CloudFormation execution policy](../infrastructure/cdk/agentcore-deployment-policy.development.json).

1. **Foundation stack: four CloudFormation resources.** One private, TLS-only, SSE-S3 encrypted, versioned code bucket; its policy; one runtime execution role; its inline policy. The bucket rejects object creation under `releases/` without `If-None-Match`. It is retained on stack deletion; unfinished multipart uploads expire after one day. No source data goes here.
2. **Existing data stack: one additive trust change.** Add the exact new runtime role to the existing query role's assume-role policy while retaining the original developer SSO principal. No data bucket, Glue table, workgroup, loader permission, or query permission changes. Comparison against the read-only deployed template found only `/Resources/SemanticQueryExecutorFBB71F8B/Properties/AssumeRolePolicyDocument/Statement` changed; evidence is `artifacts/m4-data-trust-diff.json`.
3. **Runtime stack: three CloudFormation resources.** One `AWS::BedrockAgentCore::Runtime` and two resource policies for its exact ARN and DEFAULT endpoint ARN. Python 3.12 ZIP code is pinned to a SHA-named S3 key **and the returned S3 VersionId**. PUBLIC network mode provides outbound service access; inbound requests still require SigV4. No OAuth authorizer, VPC, NAT, container build, ECR repository, additional endpoint, or other AgentCore service is created.
4. **Service-managed side effects.** Runtime creates its DEFAULT endpoint, workload identity, and stdout/stderr log group `/aws/bedrock-agentcore/runtimes/{agentRuntimeId}-DEFAULT`. Set retention to seven days with the explicit command below. If absent, AWS may create `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` and `AWSServiceRoleForBedrockAgentCoreNetwork`; the proposed deployment policy allows only those two service-linked-role creations with their matching service-name conditions. This automatic workload identity is platform support, not a separate AgentCore Identity integration.
5. **Administrator policy attachment (user-confirmed complete).** The reviewed preparation step was to create managed policy `enterprise-analytics-dev-agentcore-cdk-execution` from the reviewed JSON and attach it to the existing `cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`; this attachment was confirmed by the user and is not repeated here. Retain its existing milestone 3 policy. **Do not bootstrap again or attach AdministratorAccess.** The new policy manages only the named code bucket/runtime role and named runtime namespace, reads reviewed code, passes only the runtime role to AgentCore, and handles the automatic identities above. `CreateAgentRuntime` requires `Resource: "*"`; account, requested region, and project request-tag conditions narrow that statement. `logs:DescribeLogGroups` in the runtime role also requires `Resource: "*"`, restricted to Oregon. Policy management is privileged and assumes reviewed CDK input.

The runtime execution role trusts only `bedrock-agentcore.amazonaws.com` with source-account and runtime-name ARN conditions. It permits `bedrock:InvokeModel` on exactly:

- `arn:aws:bedrock:us-west-2:453711491609:inference-profile/us.amazon.nova-lite-v1:0`
- `arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0`
- `arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-lite-v1:0`
- `arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0`

It can assume only the existing query role, read only the SHA-named code object, and write/inspect its own runtime log namespace. It has no direct Athena/data/Glue grants. The SDK uses workload credentials; query-role assumptions last 900 seconds and refresh 120 seconds before expiry. No local profile or SSO files are packaged.

The only approved invocation principal is:

`arn:aws:iam::453711491609:role/aws-reserved/sso.amazonaws.com/us-west-2/AWSReservedSSO_PowerUserAccess_95483085e85e3a9b`

Both resource policies explicitly deny other principals, including same-account identities with broad identity policies, and deny alternate user/command/shell/WebSocket invocation APIs. Approved callers share the same development tenant/region scope. Payloads contain only `question`; session IDs and headers are not identity. This is application-enforced tenant filtering, **not Lake Formation row-level security**. Anyone directly authorized to assume the query role can read its approved full snapshots.

## Reviewed packaging and offline preparation

No AgentCore SDK or framework is required: a standard HTTP server implements `/ping` and `/invocations` on port 8080. Clients are created only during invocation. Packaging uses the Poetry lockfile, exact wheel hashes, Python 3.12 ARM64 tags, sorted fixed-timestamp ZIP entries, and an inventory manifest. Native DuckDB/Pydantic libraries were checked as AArch64 ELF objects. The archive is below the documented 250 MB compressed / 750 MB unpacked limits.

| Artifact | Reviewed value |
| --- | --- |
| Archive | `artifacts/agentcore/agent.zip` |
| SHA-256 | `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` |
| Compressed / unpacked bytes | `39,117,152 / 85,644,266` |
| Inventory | `artifacts/agentcore/agent.manifest.json` |
| Foundation template SHA-256 | `5f78288b02017a101e529e02ace36d3b0eba051c25f8b78fae18ad207e7f6fd9` |
| Runtime template SHA-256 | `a287c414f51bec59051bec51c44c006fcc0118326195b63a377e2718dbe07799` |
| Data-stack trust-update template SHA-256 | `716f59055d9cc4520c0e86bf087a77430d5e69fb525f9c0574cdaf25d02c2bd4` |
| Object key | `releases/<reviewed SHA-256>/agent.zip` |

Generated archives, wheels, templates, metadata, and live records remain ignored. Rebuilding after source/README changes requires a new reviewed checksum, configuration, and synthesis; never upload different bytes under the approved key. The development config pins the checksum; runtime synthesis fails if the archive differs.

Run from the repository root with the existing environment. These preparation commands are local:

```sh
export PATH=/opt/homebrew/anaconda3/envs/enterprise-analytics/bin:$PATH
export CONDA_PREFIX=/opt/homebrew/anaconda3/envs/enterprise-analytics
export JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache
poetry run python -m infrastructure.agentcore.package \
  --config infrastructure/agentcore/runtime.development.json \
  --output artifacts/agentcore/agent.zip --offline
infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
  --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.development.json --phase all' \
  --profile analytics-dev --region us-west-2 --no-lookups \
  --no-telemetry --no-notices --output artifacts/cdk.agentcore.reviewed.out --quiet
infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
  --app 'poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json' \
  --profile analytics-dev --region us-west-2 --no-lookups \
  --no-telemetry --no-notices --output artifacts/cdk.m4-data-trust.cli.out --quiet
```

A fresh machine first runs the packaging command without `--offline` to download only the locked Linux ARM64 wheels; no AWS credentials are involved. The reviewed ZIP can be rebuilt offline from the prepared wheel cache. Full required checks and current synthesis results are recorded in [progress](progress.md). Ordinary CI runs only offline tests and synthesis; no live acceptance is inferred.

## Original deployment commands — historical procedure; recovery gate above applies

These commands are a proposed procedure, **not operations already performed**. Before execution, verify STS still matches the account, inspect the reviewed assemblies/checksums and any fresh CloudFormation changeset, and stop if it includes changes outside this inventory. Existing bootstrap deployment privileges are a prerequisite. IAM-denied operations must be performed by an explicitly selected administrator; do not silently substitute profiles or broaden grants.

Run the deployment blocks sequentially in the same shell with `set -e` enabled; stop on any failure. Administrator, using an explicitly selected administrative profile after approval:

```sh
set -e
: "${ADMIN_PROFILE:?Set an explicitly approved administrator profile}"
test "$(aws sts get-caller-identity --profile "$ADMIN_PROFILE" --region us-west-2 --query Account --output text)" = 453711491609
aws iam get-role --role-name cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2 \
  --profile "$ADMIN_PROFILE" --region us-west-2
aws iam list-attached-role-policies --role-name cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2 \
  --profile "$ADMIN_PROFILE" --region us-west-2
aws iam get-role --role-name enterprise-analytics-dev-query-executor \
  --profile "$ADMIN_PROFILE" --region us-west-2
aws iam create-policy --policy-name enterprise-analytics-dev-agentcore-cdk-execution \
  --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json \
  --profile "$ADMIN_PROFILE" --region us-west-2
aws iam attach-role-policy --role-name cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2 \
  --policy-arn arn:aws:iam::453711491609:policy/enterprise-analytics-dev-agentcore-cdk-execution \
  --profile "$ADMIN_PROFILE" --region us-west-2
```

If that managed policy already exists, inspect it and use a reviewed policy version rather than blindly recreating/replacing it. Administrator confirmation must establish the original developer trust is preserved before the data-stack update.

Deploy the role/bucket, then apply the reviewed trust-only data-stack update:

```sh
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/cdk.agentcore.reviewed.out enterprise-analytics-dev-agent-foundation \
  --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/cdk.m4-data-trust.cli.out enterprise-analytics-dev-data-layer \
  --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices
```

Upload only the checksum-verified archive, with a conditional write, then capture its immutable VersionId. The approved operator upload proved `s3:PutObject` on the reviewed key; its exact retained version is recorded above, so do not repeat this completed upload. The CloudFormation execution policy deliberately has no code-upload permission.

```sh
poetry run python - <<'PY'
import base64
import hashlib
import json
from pathlib import Path
import subprocess
config = json.loads(Path('infrastructure/cdk/agentcore.config.development.json').read_text())
digest = hashlib.sha256(Path(config['artifact_path']).read_bytes()).digest()
assert digest.hex() == config['artifact_sha256']
result = subprocess.run([
    'aws', 's3api', 'put-object', '--profile', 'analytics-dev', '--region', 'us-west-2',
    '--bucket', 'enterprise-analytics-dev-453711491609-us-west-2-agent-code',
    '--key', f'releases/{digest.hex()}/agent.zip', '--body', config['artifact_path'],
    '--if-none-match', '*', '--expected-bucket-owner', config['account'],
    '--checksum-sha256', base64.b64encode(digest).decode(), '--output', 'json',
], check=True, text=True, capture_output=True)
record = json.loads(result.stdout)
assert record.get('VersionId') and record['VersionId'] != 'null'
Path('artifacts/agentcore/upload.json').write_text(json.dumps(record, indent=2) + '\n')
print('Uploaded reviewed archive; VersionId recorded in artifacts/agentcore/upload.json')
PY
ARTIFACT_VERSION_ID=$(poetry run python -c 'import json; print(json.load(open("artifacts/agentcore/upload.json"))["VersionId"])')
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/cdk.agentcore.reviewed.out enterprise-analytics-dev-agent-runtime \
  --parameters "ArtifactVersionId=$ARTIFACT_VERSION_ID" \
  --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices
aws cloudformation describe-stacks --stack-name enterprise-analytics-dev-agent-runtime \
  --profile analytics-dev --region us-west-2 --output json > artifacts/agentcore/deployed-runtime.json
```

Derive nonsecret live configuration from the actual outputs. Set log retention after the first counted invocation, because the service may create its log group lazily:

```sh
poetry run python - <<'PY'
import json
from pathlib import Path
record = json.loads(Path('artifacts/agentcore/deployed-runtime.json').read_text())
outputs = {x['OutputKey']: x['OutputValue'] for x in record['Stacks'][0]['Outputs']}
for version in ('parity-v1', 'parity-legacy-v1', 'parity-no-returns-v1'):
    config = dict(profile='analytics-dev', account='453711491609', region='us-west-2',
        runtime_arn=outputs['AgentRuntimeArn'], qualifier='DEFAULT',
        model_id='us.amazon.nova-lite-v1:0', dataset_version=version, reference_date='2025-02-01')
    Path(f'artifacts/agentcore/live.{version}.json').write_text(json.dumps(config, indent=2) + '\n')
Path('artifacts/agentcore/runtime-log-group.txt').write_text(outputs['RuntimeLogGroupName'])
print(outputs['AgentRuntimeId'])
PY
RUNTIME_LOG_GROUP=$(cat artifacts/agentcore/runtime-log-group.txt)
# Read-only readiness check, reused after each dataset update and base restoration.
verify_runtime_ready() {
  poetry run python - <<'PYREADY'
import json
from pathlib import Path
import boto3
from botocore.config import Config
record = json.loads(Path('artifacts/agentcore/deployed-runtime.json').read_text())
outputs = {x['OutputKey']: x['OutputValue'] for x in record['Stacks'][0]['Outputs']}
client = boto3.Session(profile_name='analytics-dev', region_name='us-west-2').client(
    'bedrock-agentcore-control', config=Config(connect_timeout=5, read_timeout=10,
        retries={'total_max_attempts': 1}))
runtime = client.get_agent_runtime(agentRuntimeId=outputs['AgentRuntimeId'])
endpoint = client.get_agent_runtime_endpoint(
    agentRuntimeId=outputs['AgentRuntimeId'], endpointName='DEFAULT')
assert runtime['status'] == endpoint['status'] == 'READY', (runtime['status'], endpoint['status'])
assert endpoint['liveVersion'] == endpoint['targetVersion'] == runtime['agentRuntimeVersion']
print('READY runtime version:', runtime['agentRuntimeVersion'])
PYREADY
}
verify_runtime_ready
```

Defer retention until after the counted warm-up below; waiting for a group before the first invocation can wait indefinitely. Do not enable account-wide log delivery or grant `logs:PutResourcePolicy`. Read `get-agent-runtime` / DEFAULT endpoint status and require READY before acceptance.

## Invocation and authored live acceptance — billable, approval required

One representative manual invocation, counted against the allowance below:

```sh
poetry run python - <<'PY'
import json
from pathlib import Path
from uuid import uuid4
import boto3
from botocore.config import Config
config = json.loads(Path('artifacts/agentcore/live.parity-v1.json').read_text())
session = boto3.Session(profile_name=config['profile'], region_name=config['region'])
client = session.client('bedrock-agentcore', config=Config(
    connect_timeout=5, read_timeout=150, retries={'total_max_attempts': 1}))
result = client.invoke_agent_runtime(agentRuntimeArn=config['runtime_arn'], qualifier='DEFAULT',
    runtimeSessionId=str(uuid4()), contentType='application/json', accept='application/json',
    payload=json.dumps({'question': 'Show net_revenue for January 2025 by region.'}).encode())
body = result['response']
try:
    Path('artifacts/agentcore/manual-response.json').write_bytes(body.read())
finally:
    body.close()
PY
aws logs put-retention-policy --log-group-name "$RUNTIME_LOG_GROUP" --retention-in-days 7 \
  --profile analytics-dev --region us-west-2
# If log creation is still propagating, retry only this retention command.
poetry run pytest tests --run-agent-live --agent-config=artifacts/agentcore/live.parity-v1.json -m agent_live -q
```

Acceptance uses literal independently authored values in [evaluation.py](../src/enterprise_analytics_agent/agent/evaluation.py), not model prose, generator outputs, or agreement between two implementations. Five grouped metrics must give:

| Metric | North | South |
| --- | ---: | ---: |
| gross_sales, USD | 38.00 | 15.00 |
| net_revenue, USD | 28.50 | 13.00 |
| order_count | 2 | 1 |
| average_order_value, USD | 14.25 | 13.00 |
| return_rate, fraction | 0.500000 | 1.000000 |

Other cases check ungrouped totals/filtering, February's exclusive boundary, reference-date-relative periods, empty/null ratios, all metadata operations, unsupported/ambiguous questions, attempted tenant/region overrides, and two independent requests within one runtime session. The fixtures already contain partial refunds, received versus pending/rejected returns, replayed events, multiple items, canceled/non-USD orders, hidden regions and another tenant. Tool IDs/arguments, successful selection, exact decimals/units, period/filter/grouping, versions, model configuration, token limits, and diagnostics are graded; exact prose is not.

Run missing-returns and empty-returns variants by updating **only the trusted dataset environment setting** on this same runtime, keeping the same archive/role/caller/model and S3 VersionId. The packaged default stays `parity-v1`:

```sh
poetry run python - <<'PY'
import json
from pathlib import Path
base = json.loads(Path('infrastructure/cdk/agentcore.config.development.json').read_text())
for version in ('parity-legacy-v1', 'parity-no-returns-v1'):
    config = dict(base, dataset_version_override=version)
    Path(f'artifacts/agentcore/deploy.{version}.json').write_text(json.dumps(config, indent=2) + '\n')
PY
VARIANT_STATUS=0
for DATASET_VERSION in parity-legacy-v1 parity-no-returns-v1; do
  infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
    --app "poetry run python -m infrastructure.cdk.agentcore_app --config artifacts/agentcore/deploy.$DATASET_VERSION.json --phase runtime" \
    --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices \
    --output "artifacts/cdk.agentcore.$DATASET_VERSION.out" --quiet || { VARIANT_STATUS=$?; break; }
  infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
    --app "artifacts/cdk.agentcore.$DATASET_VERSION.out" enterprise-analytics-dev-agent-runtime \
    --parameters "ArtifactVersionId=$ARTIFACT_VERSION_ID" \
    --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices || { VARIANT_STATUS=$?; break; }
  verify_runtime_ready || { VARIANT_STATUS=$?; break; }
  poetry run pytest tests --run-agent-live --agent-config="artifacts/agentcore/live.$DATASET_VERSION.json" -m agent_live -q || { VARIANT_STATUS=$?; break; }
done
# Restore parity-v1 even if a variant fails; do not start further evaluations on failure.
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/cdk.agentcore.reviewed.out enterprise-analytics-dev-agent-runtime \
  --parameters "ArtifactVersionId=$ARTIFACT_VERSION_ID" \
  --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices
```

After restoring the base, run `verify_runtime_ready` and `test "$VARIANT_STATUS" -eq 0` and retain the original failure output; a failed restore also fails this procedure. Require successful deployment/READY between variants; a deployment failure stops the loop before invoking tests. The shell loop above is a procedure for supervised execution, not an unattended recovery script. Legacy return rate must produce the specific missing-source error while net revenue still works; empty returns must yield zero, not missing-source failure. Default pytest and ordinary CI never invoke these tests. Requested live execution with missing/invalid configuration fails clearly rather than skipping.

**Original approved allowance, unchanged (0 used):** three live suite runs (18 + 3 + 3 tests, 27 invocation requests because each session test sends two), plus one manual invocation and limited failed-case reruns, **at most 40 total Runtime invocations** for this acceptance attempt. Record the count; stop and obtain approval before exceeding it or changing resources/IAM/model/scope. No production load, retail demo invocation, concurrency benchmark, or additional AgentCore service is included. The runtime does not implement an account-wide invocation counter; this total is an operator-enforced acceptance allowance.

Collect ignored `artifacts/agent-live-evaluations.jsonl`, actual runtime/endpoint versions, archive/S3 VersionId, test output, and CloudWatch logs. Diagnostics contain model configuration, reported input/output tokens, latency, matching tool calls, and Athena query IDs/scans/timings/versions. Redact before sharing outside the approved development context. Do not mark the milestone complete unless every agreed case passes on the deployed runtime, the base configuration is restored, and actual evidence is recorded. Record failures honestly and keep it open.

## Limits, costs, and cleanup

Each request permits at most 6 model iterations, 16 semantic calls, 1,024 output tokens per model call and 12,000 reported cumulative tokens. A conservative byte-based input reserve can reject large conversations sooner. Scheduling deadline is 90 seconds; Athena queries use 60 seconds, finite SDK connect/read timeouts, bounded retries and best-effort cancellation. In-flight calls/cleanup can outlast the scheduling deadline; it is not a hard wall-clock or billing cap. Runtime session idle timeout is 300 seconds, maximum lifetime 900 seconds. Athena retains its existing 10 MiB per-query scan limit, not an aggregate spend limit.

For planning only, reserve **$5 for this small acceptance attempt**, excluding existing data-layer baseline charges and retained resources afterward; this is not an AWS Budget or a hard cap. At an intentionally conservative illustrative model allowance of $1/million input and $5/million output tokens, 40 × 12,000 entirely output tokens would be $2.40. These are budgeting assumptions, **not a verified Nova tariff**; review the selected region/profile's current [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) before approved execution. No provisioned throughput or model subscription is requested.

The current [AgentCore price table](https://aws.amazon.com/bedrock/agentcore/pricing/) lists V1 CPU $0.0895/vCPU-hour and memory $0.00945/GB-hour. Illustratively 40 sessions using 2 active vCPUs for 90 seconds and retaining 4 GB for 390 seconds would be about $0.34 of runtime usage, before cold starts/overhead/retries; allocation and actual usage are not measured. Athena at an illustrative $5/TB and 10 MB minimum is about $0.032 for 640 single-attempt queries (40 × 16), with retries and S3/log requests extra. Code storage is roughly 40 MB plus retained versions. CloudWatch ingestion/retention, data/result storage, cross-region routing charges if applicable, and existing monitoring continue separately. Recheck [Athena](https://aws.amazon.com/athena/pricing/), [S3](https://aws.amazon.com/s3/pricing/), and [CloudWatch](https://aws.amazon.com/cloudwatch/pricing/) rates before execution.

Cleanup is **documented, not executed or preauthorized by preparation**. Delete the runtime stack first (including resource policies) to stop future invocation, then remove only the runtime principal from source-controlled query trust and deploy that reviewed trust-only reversal, preserving developer access. Finally delete the foundation stack. Code storage is retained; data/result buckets, Glue, Athena, bootstrap and shared service-linked roles remain intact.

```sh
infrastructure/cdk/tooling/node_modules/.bin/cdk destroy \
  --app artifacts/cdk.agentcore.reviewed.out enterprise-analytics-dev-agent-runtime \
  --profile analytics-dev --region us-west-2
# Prepare only the trust reversal; preserve developer and any other trusted principals.
poetry run python - <<'PYCODE'
import json
from pathlib import Path
config = json.loads(Path('infrastructure/cdk/config.development.json').read_text())
runtime = 'arn:aws:iam::453711491609:role/enterprise-analytics-dev-agent-runtime'
assert runtime in config['trusted_query_principal_arns']
config['trusted_query_principal_arns'] = [
    arn for arn in config['trusted_query_principal_arns'] if arn != runtime]
Path('artifacts/agentcore/data.cleanup.json').write_text(json.dumps(config, indent=2) + '\n')
PYCODE
infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
  --app 'poetry run python -m infrastructure.cdk.app --config artifacts/agentcore/data.cleanup.json' \
  --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices \
  --output artifacts/cdk.agentcore-trust-cleanup.out --quiet
# Inspect the synthesized diff: only removal of the M4 trust principal is allowed.
infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  --app artifacts/cdk.agentcore-trust-cleanup.out enterprise-analytics-dev-data-layer \
  --profile analytics-dev --region us-west-2 --no-telemetry --no-notices
infrastructure/cdk/tooling/node_modules/.bin/cdk destroy \
  --app artifacts/cdk.agentcore.reviewed.out enterprise-analytics-dev-agent-foundation \
  --profile analytics-dev --region us-west-2
aws s3api list-object-versions --bucket enterprise-analytics-dev-453711491609-us-west-2-agent-code \
  --profile analytics-dev --region us-west-2
```

For explicit storage removal, review each listed key/version, then use `aws s3api delete-object --bucket <code-bucket> --key <exact-key> --version-id <reviewed-version> --profile analytics-dev --region us-west-2`; remove delete markers too before deleting the bucket. Do not use blanket deletion on the data buckets. The seven-day log group can remain for evidence; deleting it and detaching/deleting the M4 CloudFormation policy require a separate administrator cleanup decision after confirming no dependents. Do not delete shared bootstrap or service-linked roles automatically.

## Official references checked during implementation

- [Boto3 Converse](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html), [client-side tool use](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html), [Nova tool schemas](https://docs.aws.amazon.com/nova/latest/userguide/tool-use-definition.html), [Nova Lite model/regions](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html), [inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html).
- [Direct Python code deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html), [supported runtimes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-code-deploy-supported-runtimes.html), [HTTP contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html), [platform versions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html), [IAM versus OAuth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html).
- [CDK Runtime](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/CfnRuntime.html), [CDK ResourcePolicy](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/CfnResourcePolicy.html), [AgentCore IAM actions/resources](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html), [service-linked roles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/service-linked-roles.html). Actual CloudFormation registry schemas were also inspected read-only for Runtime, ResourcePolicy, and S3 Bucket; optional VPC/KMS/capacity-provider permissions were excluded.
- [Boto3 credential providers](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html), [STS AssumeRole](https://docs.aws.amazon.com/boto3/latest/reference/services/sts/client/assume_role.html), [S3 IAM permissions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3.html), [Object Ownership permissions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html).
