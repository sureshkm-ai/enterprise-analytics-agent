# Administrator steps for the approved streaming release

The user approved the existing multi-model deployment plan on November 11, 2026.
These steps resolve its administrator prerequisites. Local operator commands
continue to use only `analytics-dev`; no additional local profile is needed.
Use an existing administrator AWS console session in account **453711491609**.
Do not use the developer SSO role to grant itself IAM permissions.

**November 12 follow-up:** both policy attachments and exact active documents
are verified from the supplied report. All three previously blocked model
agreements are now independently verified AVAILABLE. Do not repeat those steps.
The supplement now verifies its exact request and current M4 policy, identifying
the Project-condition gap. The user separately approved the exact correction at
f68e191. The remaining gate is administrator application/readback, followed by an
allowed simulation. Approval does not establish that the policy has been applied.

## Attach the reviewed permissions as two managed policies

The approved aggregate JSON has **8,147** characters excluding formatting;
IAM managed policies permit **6,144** each. Keep that original file as the audit
reference. Use the two files below, whose complete statement union is identical:
no action, resource or condition was added, removed or widened. The
[packaging manifest](../evaluations/bedrock-streaming/policy-packaging.json)
records both hashes, sizes and the unchanged aggregate hash.

| New policy name | JSON to paste | IAM characters |
| --- | --- | ---: |
| `enterprise-analytics-stream-cdk-roles` | [roles/code policy](../infrastructure/cdk/streaming-deployment-policy.roles.proposed.json) | 2,294 |
| `enterprise-analytics-stream-cdk-agentcore` | [AgentCore policy](../infrastructure/cdk/streaming-deployment-policy.agentcore.proposed.json) | 5,891 |

1. Open the first JSON file in VS Code and copy its complete contents.
2. In the administrator AWS console, open **IAM → Policies → Create policy → JSON**.
   Paste the JSON, choose **Next**, enter its exact policy name from the table,
   and create it. Repeat for the second file/name. If an exact name already
   exists, compare its active JSON first; do not overwrite a different policy or
   create duplicate grants to work around an unexplained mismatch.
3. Open **IAM → Roles** and select exactly
   **cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2**.
4. Choose **Permissions → Add permissions → Attach policies**. Select both new
   policies from the table and attach them.
5. Keep **enterprise-analytics-dev-cdk-execution** and
   **enterprise-analytics-dev-agentcore-cdk-execution** attached. Preserve their
   default versions, all existing permissions and the role's trust policy.

The two policies together grant exactly the reviewed new-role/runtime lifecycle
and exact new-code-key access. They contain no shared-directory tagging grant.
Both passed AWS Access Analyzer document validation with zero findings; actual
attachment and effective role authorization still require the reports below.
Do not paste the oversized aggregate as one managed policy or substitute a broad
AWS managed policy for these documents.

## Produce read-only evidence

Open **CloudShell from that administrator console session**. These commands read
IAM/STS only; they create local report files, not AWS resources, profiles, policies
or model requests. Verify the STS account is **453711491609** before continuing.

```sh
aws sts get-caller-identity --region us-west-2
```

After confirming that account, paste this block. Use a fresh CloudShell working
directory so earlier reports remain intact.

```sh
STREAM_EVIDENCE_DIR=$(mktemp -d "$PWD/streaming-iam-evidence.XXXXXX")
cd "$STREAM_EVIDENCE_DIR"
STREAM_EXEC_ROLE=cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2

aws iam get-role --region us-west-2 \
  --role-name "$STREAM_EXEC_ROLE" > execution-role.json
aws iam list-attached-role-policies --region us-west-2 \
  --role-name "$STREAM_EXEC_ROLE" > attached-policies.json
for STREAM_POLICY_PART in roles agentcore; do
  STREAM_POLICY_ARN="arn:aws:iam::453711491609:policy/enterprise-analytics-stream-cdk-$STREAM_POLICY_PART"
  aws iam get-policy --region us-west-2 \
    --policy-arn "$STREAM_POLICY_ARN" > "policy-$STREAM_POLICY_PART-metadata.json"
  STREAM_POLICY_VERSION=$(aws iam get-policy --region us-west-2 \
    --policy-arn "$STREAM_POLICY_ARN" --query Policy.DefaultVersionId --output text)
  aws iam get-policy-version --region us-west-2 \
    --policy-arn "$STREAM_POLICY_ARN" --version-id "$STREAM_POLICY_VERSION" \
    > "policy-$STREAM_POLICY_PART-active.json"
done
aws iam get-role --region us-west-2 \
  --role-name enterprise-analytics-dev-query-executor > query-role-before.json

cat > directory-context.json <<'JSON'
[
  {"ContextKeyName":"aws:RequestedRegion","ContextKeyValues":["us-west-2"],"ContextKeyType":"string"},
  {"ContextKeyName":"aws:PrincipalAccount","ContextKeyValues":["453711491609"],"ContextKeyType":"string"},
  {"ContextKeyName":"aws:RequestTag/Project","ContextKeyValues":["enterprise-analytics-stream"],"ContextKeyType":"string"}
]
JSON
aws iam simulate-principal-policy --region us-west-2 \
  --policy-source-arn arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2 \
  --action-names bedrock-agentcore:TagResource \
  --resource-arns arn:aws:bedrock-agentcore:us-west-2:453711491609:workload-identity-directory/default \
  --context-entries file://directory-context.json > directory-simulation.json
```

Return both active policies/default versions, attachment list, permission-boundary
information from `execution-role.json`, current query-role trust and
`directory-simulation.json`. These are policy/evidence documents; never send access
keys, SSO tokens or signed request headers. A simulation is evidence of policy
evaluation, not a guarantee that a service deployment will succeed.

For one report to download or paste, run this in the same CloudShell directory:

```sh
python3 - <<'PY'
import json
from pathlib import Path

names = [
    "execution-role.json", "attached-policies.json",
    "policy-roles-metadata.json", "policy-roles-active.json",
    "policy-agentcore-metadata.json", "policy-agentcore-active.json",
    "query-role-before.json", "directory-simulation.json",
]
report = {name: json.loads(Path(name).read_text()) for name in names}
Path("streaming-admin-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
print("Created streaming-admin-evidence.json")
PY
```

The directory simulation must include the exact Project condition above.
Historical M4 permission allows tagging only for `enterprise-analytics-dev`;
new runtimes use `enterprise-analytics-stream`. Fresh directory tag reads returned
an empty tag map. Directory existence or an empty map does not prove permission.
If the result is `implicitDeny`, `explicitDeny`, or has missing context, return the
report before changing more permissions. No blanket AgentCore/IAM grant or manual
directory retagging is part of these instructions.

<a id="resolve-the-reported-directory-simulation"></a>

## Directory simulation evidence — received and diagnosed

The downloaded `streaming-admin-evidence.json` matches SHA-256
`67333dff4ea0e92f43103b297c51df7b81d366ae4539c2a0d2b32ebb414e751f`.
Its directory TagResource result is **implicitDeny**, with no matched statements.
The original combined report did not include its simulation request/context or
the active M4 policy document. The downloaded supplement now supplies both;
SHA-256 `f93373f83efe0e70c06ecf760776922b88c7d0c60ab44cfc60bb54ac8a14733e`.
Its exact request uses the reviewed execution role, directory, region/account and
`Project=enterprise-analytics-stream`; the result remains implicitDeny. Active M4
default **v5** exactly matches the committed policy, whose directory Allow
requires `Project=enterprise-analytics-dev`. Both streaming policies omit a
directory TagResource grant. This establishes the narrow gap. No further report
is needed to identify it; preserve the following collection procedure as history.

In the same existing **administrator CloudShell**, run the block below. It uses
read-only STS/IAM operations and a fresh local directory. It does not change IAM,
create profiles, tag resources, or invoke a model. An implicitDeny is collected
as evidence, not treated as permission to retry deployment.

```sh
(
  set -euo pipefail
  STREAM_SUPPLEMENT_DIR=$(mktemp -d "$PWD/streaming-iam-supplement.XXXXXX")
  cd "$STREAM_SUPPLEMENT_DIR"
  aws sts get-caller-identity --region us-west-2 --no-cli-pager > administrator-identity.json
  python3 -c 'import json; account=json.load(open("administrator-identity.json"))["Account"]; account == "453711491609" or exit("Wrong AWS account")'

  STREAM_M4_POLICY_ARN=arn:aws:iam::453711491609:policy/enterprise-analytics-dev-agentcore-cdk-execution
  aws iam get-policy --policy-arn "$STREAM_M4_POLICY_ARN" \
    --region us-west-2 --no-cli-pager > m4-policy-metadata.json
  STREAM_M4_VERSION=$(python3 -c 'import json; print(json.load(open("m4-policy-metadata.json"))["Policy"]["DefaultVersionId"])')
  aws iam get-policy-version --policy-arn "$STREAM_M4_POLICY_ARN" \
    --version-id "$STREAM_M4_VERSION" --region us-west-2 --no-cli-pager \
    > m4-policy-active.json

  cat > directory-simulation-request.json <<'JSON'
{
  "PolicySourceArn": "arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2",
  "ActionNames": ["bedrock-agentcore:TagResource"],
  "ResourceArns": ["arn:aws:bedrock-agentcore:us-west-2:453711491609:workload-identity-directory/default"],
  "ContextEntries": [
    {"ContextKeyName":"aws:RequestedRegion","ContextKeyValues":["us-west-2"],"ContextKeyType":"string"},
    {"ContextKeyName":"aws:PrincipalAccount","ContextKeyValues":["453711491609"],"ContextKeyType":"string"},
    {"ContextKeyName":"aws:RequestTag/Project","ContextKeyValues":["enterprise-analytics-stream"],"ContextKeyType":"string"}
  ]
}
JSON
  aws iam simulate-principal-policy \
    --cli-input-json file://directory-simulation-request.json \
    --region us-west-2 --no-cli-pager > directory-simulation-response.json

  python3 - <<'PY'
import json
from pathlib import Path

names = [
    "administrator-identity.json", "m4-policy-metadata.json", "m4-policy-active.json",
    "directory-simulation-request.json", "directory-simulation-response.json",
]
content = json.dumps({name: json.loads(Path(name).read_text()) for name in names}, indent=2) + "\n"
report = Path("streaming-admin-supplement.json")
with report.open("x") as stream:
    stream.write(content)
print(report.resolve())
PY
)
```

Use **CloudShell → Actions → Download file** with the printed absolute path and
return `streaming-admin-supplement.json`. If Download file is absent in the
toolbar panel, open full-page CloudShell. Preserve any denial or missing-context
fields. In particular, do not invent `iam:AWSServiceName` or `iam:PassedToService`
values for TagResource merely to remove the simulator's missing-context output.
No additional permission is approved by collecting this report. A specific
correction, if established, requires review before application.

<a id="proposed-directory-correction--separate-approval-required"></a>

## Approved directory correction — administrator application pending

The smallest proposed delta is [this separate policy](../infrastructure/cdk/streaming-directory-tag-policy.proposed.json),
SHA-256 **ba04feb1ce5c92ab55b94e09bfa522e641a0b2a2eedb10d97d313e42d996d39b**.
It grants only `bedrock-agentcore:TagResource` on the exact account/region default
workload-identity directory, conditioned on the reviewed requested Project,
account and region. The directory is shared; this is not a new Runtime-only
resource. The [review record](../evaluations/bedrock-streaming/directory-tag-review.proposed.json)
binds the reports, exact target role, policy checksum and verification gates.

The original deployment plan deliberately excluded this grant. The user has now
**separately approved this exact correction**, recorded in the
[approval record](../evaluations/bedrock-streaming/directory-tag-approval.json).
The proposed review JSON and policy bytes remain unchanged as historical review
evidence. Administrator application and an allowed post-change simulation are
still unverified. Keep the original aggregate, both split managed policies,
M3/M4 policies, trust, package/templates, data and all budgets unchanged.

The administrator can now apply the exact additive inline policy using the console:

1. Open **IAM → Roles → cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2**.
2. Choose **Permissions → Add permissions → Create inline policy → JSON**.
3. Paste the complete proposed JSON, review it, and use the name
   **enterprise-analytics-stream-directory-tag**. If that name already exists,
   compare its contents first; do not overwrite an unexplained policy.
4. Preserve all existing policies and trust. Record the actual inline policy
   using administrator `get-role-policy` evidence and rerun the exact reviewed
   directory simulation request. Require **allowed** and review the complete
   result; a simulation is not proof of deployment success.
5. Return the exact inline-policy JSON and simulation evidence. The operator
   repeats full fresh preflight before the already approved upload/deployment.

After saving the inline policy, collect its readback and attachment list in a
fresh CloudShell evidence directory:

```sh
STREAM_POST_CHANGE_DIR=$(mktemp -d "$PWD/streaming-directory-post-change.XXXXXX")
aws iam get-role-policy --region us-west-2 --no-cli-pager \
  --role-name cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2 \
  --policy-name enterprise-analytics-stream-directory-tag \
  > "$STREAM_POST_CHANGE_DIR/directory-inline-policy.json"
aws iam list-attached-role-policies --region us-west-2 --no-cli-pager \
  --role-name cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2 \
  > "$STREAM_POST_CHANGE_DIR/attached-policies.json"
echo "$STREAM_POST_CHANGE_DIR"
```

Then rerun the unchanged read-only supplement collection block above; it records
the exact directory simulation request/response in `streaming-admin-supplement.json`.
Download that new supplement plus the two files in the printed post-change
directory. Return the full files, including any denial or missing context; do
not add unrelated IAM context values or retry deployment to test permissions.
The existing administrator account/region checks still apply. These verification
commands do not modify AWS and create no local profile.

Do not append this grant to the 5,891-character managed policy or replace the old
M4 Project condition. A separate inline policy preserves those approved documents
and avoids their managed-policy size constraints; IAM's total inline-policy quota
still applies. Cleanup, if subsequently approved, removes only this named inline
policy after confirming it is no longer needed; it does not untag/delete the
shared directory or alter M3/M4 permissions.

Official references: [AgentCore resource/action/condition support](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html),
[IAM simulation and additional-policy behavior](https://docs.aws.amazon.com/cli/latest/reference/iam/simulate-principal-policy.html),
and [IAM policy editing](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_manage-edit.html).

## Query-role trust is a later administrator step

The [ten exact additions](../infrastructure/cdk/streaming-query-trust-additions.proposed.json)
were extracted from the reviewed templates and consolidated into one statement
with ten exact principals. This preserves permissions and leaves room under the
trust-document size quota; check the complete merged document against the current
role quota. Preserve the current query-role trust
now. Apply these additions **after the ten new roles exist**, before evaluation;
IAM cannot trust nonexistent role principals. Merge only those statements and
preserve the developer SSO and existing runtime principals. The operator will
record before/after proof when that step is reached.

## Model agreement history — resolved November 12

The read-only check at `2026-11-12T04:04Z` found authorization, entitlement and region
availability for all nine native model targets, matching US profile routing, and
an active Mantle default project. Three targets additionally returned
`agreementAvailability.status = NOT_AVAILABLE`:

- `anthropic.claude-opus-5-5`
- `openai.gpt-6-astra`
- `openai.gpt-6.1-sol`

At that initial checkpoint they were not access-ready; public offer metadata was
read without subscribing. After the user completed the agreements, read-only
checks at **2026-11-12T18:04Z** verified **AVAILABLE** for all three, with
authorization, entitlement and region gates passing. No further agreement action
is needed from this handoff. Do not submit playground prompts to test access:
those would be extra billable attempts outside the prescribed twenty-question
sequence. The operator performed no agreement creation, provider form submission
or model invocation; agreement completion was user-executed.

AWS documents the agreement status separately from authorization/entitlement:
[model-access prerequisites and status meanings](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html),
[GetFoundationModelAvailability](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetFoundationModelAvailability.html),
[creating a policy in the JSON editor](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_create-console.html),
[attaching managed policies](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_manage-attach-detach.html),
[IAM policy simulation](https://docs.aws.amazon.com/cli/latest/reference/iam/simulate-principal-policy.html),
[IAM policy character limits](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html).

The existing Nova release remains intact. Once the evidence and model prerequisites
are satisfied, continue the already approved [deployment plan](bedrock-multimodel-streaming-plan.md)
with fresh preflight; no repeated execution approval is needed for its unchanged scope.
