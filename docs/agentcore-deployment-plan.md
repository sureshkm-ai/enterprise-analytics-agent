# Milestone 4 AgentCore deployment and live-test plan

Prepared 2026-11-06; archive and synthesized templates refreshed for the question-scope follow-up. **Local readiness only; deployment, IAM changes, uploads, and billable invocations await approval. Milestone 4 remains open.** This plan reuses the deployed milestone 3 data layer. It does not repeat bootstrap, dataset publication, or the earlier Athena parity run.

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

After the user renewed SSO, read-only STS verified the explicit profile/account/region. CloudFormation reports the existing data-layer stack `CREATE_COMPLETE`. Ready manifests, all 27 Glue table schemas, and object SHA-256/length metadata were verified for all four snapshots, including published `retail-v1`. Evidence is under ignored `artifacts/m4-snapshot-verification.json`. This verifies publication metadata, not a fresh Athena execution or a retail agent demonstration. Initial acceptance uses authored parity fixtures, not generated retail values.

Bedrock `GetInferenceProfile` reports ACTIVE and `GetFoundationModelAvailability` reports agreement/entitlement/region AVAILABLE and authorization AUTHORIZED for Nova Lite. Official documentation supports Converse client-side tools. **Inference access and tool behavior have not been proved by a model call.** The US inference profile can route from Oregon to **us-west-2, us-east-1, or us-east-2**; approval covers that US routing. SCPs and model quotas in those destinations can still prevent inference. No implicit default profile is allowed.

`iam:GetRole` is denied to the selected PowerUser SSO caller. An administrator must verify existing bootstrap role attachments and query-role trust, and perform the scoped deployment-policy attachment below. Read-only Access Analyzer validation of the proposed policy returned `findings: []` after correcting two invalid S3 action names. This validates policy syntax/rules, not effective deployment privileges or service success.

## Exact resources and IAM changes proposed

The follow-up scope guard clarifies cross-dimension alternatives, unsupported coordinated groupings, unresolved date refinements, and unknown measures before accepting a partial tool plan. It preserves supported same-dimension alternatives, explicit conjunctions, governed metric comparisons and exclusive intervals. Metric definitions and IAM/resource scope are unchanged.

The reviewed source is [AgentCore configuration](../infrastructure/cdk/agentcore.config.development.json), [stacks](../infrastructure/cdk/agentcore_stack.py), [runtime configuration](../infrastructure/agentcore/runtime.development.json), and [CloudFormation execution policy](../infrastructure/cdk/agentcore-deployment-policy.development.json).

1. **Foundation stack: four CloudFormation resources.** One private, TLS-only, SSE-S3 encrypted, versioned code bucket; its policy; one runtime execution role; its inline policy. The bucket rejects object creation under `releases/` without `If-None-Match`. It is retained on stack deletion; unfinished multipart uploads expire after one day. No source data goes here.
2. **Existing data stack: one additive trust change.** Add the exact new runtime role to the existing query role's assume-role policy while retaining the original developer SSO principal. No data bucket, Glue table, workgroup, loader permission, or query permission changes. Comparison against the read-only deployed template found only `/Resources/SemanticQueryExecutorFBB71F8B/Properties/AssumeRolePolicyDocument/Statement` changed; evidence is `artifacts/m4-data-trust-diff.json`.
3. **Runtime stack: three CloudFormation resources.** One `AWS::BedrockAgentCore::Runtime` and two resource policies for its exact ARN and DEFAULT endpoint ARN. Python 3.12 ZIP code is pinned to a SHA-named S3 key **and the returned S3 VersionId**. PUBLIC network mode provides outbound service access; inbound requests still require SigV4. No OAuth authorizer, VPC, NAT, container build, ECR repository, additional endpoint, or other AgentCore service is created.
4. **Service-managed side effects.** Runtime creates its DEFAULT endpoint, workload identity, and stdout/stderr log group `/aws/bedrock-agentcore/runtimes/{agentRuntimeId}-DEFAULT`. Set retention to seven days with the explicit command below. If absent, AWS may create `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` and `AWSServiceRoleForBedrockAgentCoreNetwork`; the proposed deployment policy allows only those two service-linked-role creations with their matching service-name conditions. This automatic workload identity is platform support, not a separate AgentCore Identity integration.
5. **Administrator policy attachment.** Create managed policy `enterprise-analytics-dev-agentcore-cdk-execution` from the reviewed JSON and attach it to the existing `cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`. Retain its existing milestone 3 policy. **Do not bootstrap again or attach AdministratorAccess.** The new policy manages only the named code bucket/runtime role and named runtime namespace, reads reviewed code, passes only the runtime role to AgentCore, and handles the automatic identities above. `CreateAgentRuntime` requires `Resource: "*"`; account, requested region, and project request-tag conditions narrow that statement. `logs:DescribeLogGroups` in the runtime role also requires `Resource: "*"`, restricted to Oregon. Policy management is privileged and assumes reviewed CDK input.

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

## Deployment commands — execute only after approval

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

Upload only the checksum-verified archive, with a conditional write, then capture its immutable VersionId. The explicitly approved operator needs `s3:PutObject` on this one new code key; the existing PowerUser profile normally supplies it, but effective access is not yet verified. The CloudFormation execution policy deliberately has no code-upload permission.

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

**Proposed allowance:** three live suite runs (18 + 3 + 3 tests, 27 invocation requests because each session test sends two), plus one manual invocation and limited failed-case reruns, **at most 40 total Runtime invocations** for this acceptance attempt. Record the count; stop and obtain approval before exceeding it or changing resources/IAM/model/scope. No production load, retail demo invocation, concurrency benchmark, or additional AgentCore service is included. The runtime does not implement an account-wide invocation counter; this total is an operator-enforced acceptance allowance.

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
