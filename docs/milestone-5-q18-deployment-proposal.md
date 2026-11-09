# Q18 candidate upload, evaluation and original restoration proposal

**Offline preparation only; not deployment approval. PR #6 stays unmerged.**
The original live campaign remains 35/36 and closed at 38/40; M4 remains 28/40.
No AWS operation, upload, deployment, invocation or permission change ran in this preparation.
The last reported operational checkpoint is original parity-v1, Runtime/DEFAULT READY v6,
stack UPDATE_COMPLETE. A later approved window must verify that checkpoint afresh.

## Reviewed bundle

| Item | Pin |
| --- | --- |
| Profile / account / region | analytics-dev / 453711491609 / us-west-2 |
| Runtime | enterprise_analytics_dev_agent-HlWywlG60h, DEFAULT |
| Model | us.amazon.nova-lite-v1:0, existing US routing and limits |
| Candidate ZIP | `artifacts/milestone-5/q18-repair-v1/candidate/agent.zip` |
| Candidate SHA-256 | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` |
| Candidate size / runtime | 39171778 compressed / 85816131 unpacked bytes; Python 3.12 Linux ARM64 |
| Candidate key | `releases/398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1/agent.zip` |
| Code bucket | enterprise-analytics-dev-453711491609-us-west-2-agent-code |
| Candidate VersionId | **Unknown until approved upload; no version record exists yet.** |
| Candidate assembly | `artifacts/milestone-5/q18-repair-v1/cdk.candidate.out` |
| Candidate template SHA | `faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368` |
| Review identity SHA | `14a817f1ba1ad2b2fa5b5b6c1cfb4aa6250513f971153003b9ddc5ca8b193401` |
| Original ZIP SHA | `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` |
| Original S3 VersionId | `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9` |
| Original restoration assembly | `artifacts/milestone-5/cdk.restore.out` |
| Restoration template SHA | `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb` |

The [review model](../evaluations/retail-v1/q18-repair-review.json) and
[template comparison](../evaluations/retail-v1/q18-deployment-review.json) permit exactly
the candidate SHA-addressed code key and the three retail settings: dataset retail-v1,
tenant retail_demo, reference date2025-04-01. North/South, role, model, policies, resources,
network, lifecycle and limits stay unchanged. The version remains an unresolved
`ArtifactVersionId` parameter in the reviewed template, supplied from the verified real
upload record later. Original restoration uses its original key/version and February1 scope.

Review identity is SHA-256 of the Pydantic review's sorted compact JSON, not of its
pretty-printed file. [Build manifest](../evaluations/retail-v1/q18-build-manifest.json)
records the unchanged Poetry lock and verified dependency hashes. Two independent wheel
builds and ZIP builds matched byte-for-byte with SOURCE_DATE_EPOCH=1735689600.
All packaged project Python sources match this checkout and include the resolved-plan
correction. The Botocore public CA bundle is dependency data, not a private credential.
The original ZIP, assemblies, goldens and both ledgers are preserved byte-for-byte.

## Permission prerequisite: preserve existing grants

The retained foundation template's runtime execution-role policy grants code reads only
to the **original** SHA key (`agentcore_stack.py:80–85`). AWS documents that the execution
role needs S3 access for its deployment package in the [Python deployment requirements](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html).
No live IAM inspection is claimed. Before approving/executing upload or deployment, an
administrator must confirm candidate-key access. If absent, separately approve the
following additive inline statement on role `enterprise-analytics-dev-agent-runtime`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "ReadReviewedQ18CandidateCode",
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:GetObjectVersion"],
    "Resource": "arn:aws:s3:::enterprise-analytics-dev-453711491609-us-west-2-agent-code/releases/398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1/agent.zip"
  }]
}
```

This statement is a proposal only, not implemented IaC or an applied policy. Preserve
the original code grant, Bedrock/logging permissions, developer/query-role trust and all
M3 permissions. No wildcard, foundation redeployment or profile change is proposed.
Stop if additional access is required; do not broaden IAM automatically. Administrator
evidence and separate approval are prerequisites, not something analytics-dev may infer
from its own ability to HEAD an S3 object.

## Local reproduction and review

Use the existing Conda/Poetry environment. These preparation commands are local:

```sh
conda activate enterprise-analytics
export SOURCE_DATE_EPOCH=1735689600
poetry install --only-root --no-interaction
poetry build -f wheel --output artifacts/milestone-5/q18-repair-v1/candidate/project-dist
poetry run python -m infrastructure.agentcore.package --offline \
  --config infrastructure/agentcore/runtime.development.json \
  --output artifacts/milestone-5/q18-repair-v1/candidate/agent.zip \
  --wheel-dir artifacts/agentcore/wheels \
  --project-wheel artifacts/milestone-5/q18-repair-v1/candidate/project-dist/enterprise_analytics_agent-0.1.0-py3-none-any.whl
export JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache
infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
  --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.q18-repair.json --phase runtime' \
  --no-lookups --no-telemetry --no-notices \
  --output artifacts/milestone-5/q18-repair-v1/cdk.candidate.out --quiet
poetry run analytics-repair --campaign q18-repair-v1 verify-offline
```

Use a separate reproduction output/project-wheel directory to check both wheel/ZIP
digests, as done in this preparation; never overwrite the original artifact. Stop on
any mismatch. The original restore assembly was copied into the repair bundle for
audit and compared byte-for-byte, but restoration uses the original pinned path above.

## Later approved upload and actual version binding

**Do not execute the remaining sections until the complete proposal is approved and
the administrator access prerequisite is satisfied.** Use only analytics-dev and the
named account/region. First verify STS identity and the fresh original checkpoint;
stop on unexplained drift. Verify all source manifest/object/schema pins as in the
original runbook; do not republish or regenerate data.

```sh
aws sts get-caller-identity --profile analytics-dev --region us-west-2
Q18_ROOT=artifacts/milestone-5/q18-repair-v1
Q18_SHA=398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1
Q18_B64=$(poetry run python -c 'import base64; print(base64.b64encode(bytes.fromhex("398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1")).decode())')
aws s3api put-object \
  --bucket enterprise-analytics-dev-453711491609-us-west-2-agent-code \
  --key "releases/$Q18_SHA/agent.zip" --body "$Q18_ROOT/candidate/agent.zip" \
  --expected-bucket-owner 453711491609 --if-none-match '*' \
  --checksum-algorithm SHA256 --checksum-sha256 "$Q18_B64" \
  --profile analytics-dev --region us-west-2 > "$Q18_ROOT/upload-response.json"
poetry run analytics-repair --campaign q18-repair-v1 bind-upload --verify-upload \
  --upload-response "$Q18_ROOT/upload-response.json" \
  --output "$Q18_ROOT/candidate-version.json"
```

Upload once conditionally; on denial/412 preserve the response and stop. Do not retry
uploads or substitute a version. Binding takes the **returned** VersionId and performs
version-specific HEAD with owner/checksum/size checks; its write-once record binds the
review, candidate, template and object identity. Live execution repeats HEAD before any
CloudFormation mutation. The real VersionId is passed directly to the reviewed template;
no rebuild or template edit is needed. No version record was manufactured offline.

## New campaign and mandatory original restoration

New campaign ID: `milestone-5-q18-repair-v1`; ledger
`artifacts/milestone-5/q18-repair-v1/runtime-invocations.jsonl`, currently absent/unused.
Explicit CLI selection binds every ledger event to the review/candidate/template/upload
record hashes. Unknown/unpinned selections and reuse/redirection of either historical
ledger fail before dispatch. Existing legacy CLI commands keep their original closed
campaign; use the repair command for this new proposal.

| Purpose | Proposed maximum |
| --- | ---: |
| Warm-up | 1 |
| Q18 probe | 1 |
| Full unchanged suite (including Q18 again and S01A/B) | 36 |
| Original parity restoration smoke | 1 |
| Controlled reserve | 1 |
| Total new allowance | 40 |

Normal successful execution uses 39 calls. All failures and interruptions count; SDK
automatic invocation retries are disabled. The final call is protected for restoration.
A failed probe stops before the full suite and restores; it never replaces Q18 in the
suite or changes its denominator. No automatic reserve use or selective rerun is allowed.

```sh
poetry run analytics-repair --campaign q18-repair-v1 run --invoke-live \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json \
  --report-dir artifacts/milestone-5/q18-repair-v1/runs/approved-unique
```

The command checks the original READY version 6 baseline, deploys only the reviewed
Runtime stack with the candidate's exact bound version, verifies candidate/DEFAULT,
executes counted warm-up/probe/full suite, and restores in `finally`. Original restoration
deploys `artifacts/milestone-5/cdk.restore.out` with VersionId
`HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`. Readiness/policies/retention/old artifact are checked;
the smoke uses the new ledger's allowance and independent North 28.50 / South 13.00 USD.
Restored operational version must be recorded, not asserted to equal historical v6.

SIGTERM/Ctrl-C enter restoration. SIGKILL, host loss or restoration failure require
operator recovery; preserve evidence and run restoration-only, without retail inputs or
candidate-object access, using the same binding/ledger:

```sh
poetry run analytics-repair --campaign q18-repair-v1 restore --invoke-live \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json \
  --report-dir artifacts/milestone-5/q18-repair-v1/runs/restoration-unique
```

Do not reset/repoint a ledger or restart the full run after partial usage. Deployment
commands have a 1800-second subprocess bound, stack-settle 900s and READY polling 300s;
SDK reads and invocation bodies retain finite timeouts. Preserve parent/nested CloudTrail
denials on any AWS authorization failure, stop repeated attempts, and request no extra
permissions automatically. No destructive cleanup is proposed; retain original/candidate
objects, reports and ledgers.

Require probe pass, all 36 unchanged cases, diagnostics and existing p95 ≤ 90s gate, then
original restoration/proof/smoke/report review before M5 completion. Reports include
realized versions, candidate and ledger bindings, exact structured evidence, tokens,
latency and unique Athena scans. This offline bundle does not establish live acceptance.
