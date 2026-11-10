# Q18 candidate upload, evaluation and original restoration proposal

**Current status (November 10, 2026): M5 passed the approved recovery and is complete
for the agreed development scope.** Q18 probe/warm-up and all **36/36** frozen
requests passed; the original artifact/parity configuration and counted smoke
passed on **Runtime/DEFAULT READY v12**, runtime stack UPDATE_COMPLETE. Recovery
is closed **38/38**, aggregate repair **40/40**; historical M5 **38/40**, M4 **28/40**
and both prior repair histories/claims are unchanged. PR #6 remains unmerged for
review. No live allowance remains. See [recovery results](milestone-5-q18-recovery-proposal.md)
and [progress](progress.md). The earlier preparation/failure records below are
historical; their commands cannot restart a closed campaign.

## Historical preparation and execution records

**Approved attempt ended with a local CDK timeout; original restoration/smoke passed (November 9, 2026). PR #6 stays unmerged; M5 stays open.**
The original live campaign remains 35/36 and closed at 38/40; M4 remains 28/40.
The user approved this exact proposal and supplied matching administrator evidence for
candidate-key reads. Fresh original parity-v1 READY v6 preflight passed. The reviewed
candidate was uploaded once and verified by its actual returned VersionId below.
The candidate update reached UPDATE_COMPLETE and Runtime/DEFAULT were verified READY v7.
The CDK command hit its 1800-second bound after that successful update, before any
candidate invocation. Warm-up, Q18 probe and full suite did not run. Mandatory original
restoration and independent smoke passed on Runtime/DEFAULT **READY v8**, stack
UPDATE_COMPLETE. Repair usage is **1/40**, solely restoration smoke; retail dispatch is
closed, 39 calls are unspent and no reserve was used. Actual evidence and verification
are in [progress](progress.md); do not replay this attempt or reset a ledger.

The [controller continuation execution record](milestone-5-q18-continuation-proposal.md)
is now retained separately. It deployed candidate v9, then stopped before candidate calls
with a connection timeout and restored original v10 successfully. Its ledger is 1/39 closed,
aggregate 2/40, 38 left. No current execution/replay approval remains for a fresh sequence;
keep every historical command and ledger intact.

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
| Candidate VersionId | `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` (returned by the single conditional upload; version-specific verification passed) |
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
network, lifecycle and limits stay unchanged. The reviewed template keeps an
`ArtifactVersionId` parameter; execution supplied the actual verified upload version
without editing it. Original restoration uses its original key/version and February1 scope.

Review identity is SHA-256 of the Pydantic review's sorted compact JSON, not of its
pretty-printed file. [Build manifest](../evaluations/retail-v1/q18-build-manifest.json)
records the unchanged Poetry lock and verified dependency hashes. Two independent wheel
builds and ZIP builds matched byte-for-byte with SOURCE_DATE_EPOCH=1735689600.
At the preparation baseline all 47 packaged project Python sources matched the checkout
and included the resolved-plan correction. The later controller correction intentionally
changes local operator modules; the 28 runtime-source files and frozen candidate bytes
remain unchanged. The Botocore public CA bundle is dependency data, not a private credential.
The original ZIP, assemblies, goldens and both ledgers are preserved byte-for-byte.

## Permission prerequisite: preserve existing grants

The retained foundation template's runtime execution-role policy grants code reads only
to the **original** SHA key (`agentcore_stack.py:80–85`). AWS documents that the execution
role needs S3 access for its deployment package in the [Python deployment requirements](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html).
The user supplied administrator evidence confirming policy
`enterprise-analytics-dev-q18-candidate-code` on role
`enterprise-analytics-dev-agent-runtime`; its active JSON matches this exact statement.
This is supplied administrator evidence, not live IAM inspection or a policy change by
the agent:

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

The administrator applied this additive grant outside this execution. Preserve
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

## Approved upload and actual version binding

The approval and administrator prerequisite were satisfied for this execution. These
commands document the reviewed operation; the upload and version binding have already
succeeded and must not be repeated. Use only analytics-dev and the
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
`artifacts/milestone-5/q18-repair-v1/runtime-invocations.jsonl`; final usage **1/40**,
solely the successful original restoration smoke. It is retail-closed, with 39 unspent
and no incomplete reservations/retries. Both historical ledgers are unchanged.
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

The approved normal successful execution would use 39 calls. This attempt did not reach
candidate dispatch; its mandatory smoke consumed one call. A future complete sequence
would need 39 more and use the reserved allowance, requiring explicit approval. No
automatic replay/reserve use is permitted. All failures and interruptions count; SDK
automatic invocation retries are disabled. The final call is protected for restoration.
A failed probe stops before the full suite and restores; it never replaces Q18 in the
suite or changes its denominator. No automatic reserve use or selective rerun is allowed.

The following is the historical command shape, not a resumable recipe: it requires an
unused ledger and original READY v6. Prepare reviewed continuation handling from v8
before any future execution; preserve the actual candidate version and closed ledger.

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
latency and unique Athena scans. Upload and READY status alone do not establish acceptance.
