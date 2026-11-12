# Administrator steps for the approved streaming release

The user approved the existing multi-model deployment plan on November 11, 2026.
These steps resolve its administrator prerequisites. Local operator commands
continue to use only `analytics-dev`; no additional local profile is needed.
Use an existing administrator AWS console session in account **453711491609**.
Do not use the developer SSO role to grant itself IAM permissions.

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

## Model agreements also need resolution before acceptance

The read-only check at `2026-11-12T04:04Z` found authorization, entitlement and region
availability for all nine native model targets, matching US profile routing, and
an active Mantle default project. Three targets additionally returned
`agreementAvailability.status = NOT_AVAILABLE`:

- `anthropic.claude-opus-5-5`
- `openai.gpt-6-astra`
- `openai.gpt-6.1-sol`

Those three are not access-ready yet. Public offer metadata was read without
subscribing. Resolve the exact model agreement/provider prerequisites and confirm
`AVAILABLE` before acceptance. Do not submit playground prompts to test access:
those would be extra billable attempts outside the prescribed twenty-question
sequence. No agreement creation, provider form submission or model invocation has
been performed by the operator.

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
