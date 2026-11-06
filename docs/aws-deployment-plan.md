# Milestone 3 development deployment plan and validation record

The user reports successful development deployment and live validation:

| User-executed operation | Reported result |
| --- | --- |
| `CDKToolkit` bootstrap | `CREATE_COMPLETE` |
| `enterprise-analytics-dev-data-layer` deployment | `CREATE_COMPLETE` |
| Live parity command recorded below | **66 passed, 458 deselected in 111.94 seconds** |

These results were supplied by the user and were **not rerun or independently audited against AWS during this documentation update**. The reviewed plan below is retained as configuration and operator reference, not a checklist to repeat against existing resources. Current hosted-CI confirmation, final PR review, and merge remain separate handoff work; this is development validation, not production readiness. No AWS changes are authorized by this documentation task.

## Configured target and historical prerequisites

| Setting | Value |
| --- | --- |
| Selected profile | `analytics-dev`, explicitly selected by the user; no default-profile fallback |
| Account / region | `453711491609` / `us-west-2`, verified by read-only STS and profile metadata |
| App stack | `enterprise-analytics-dev-data-layer` |
| Database / SQL workgroup | `enterprise_analytics_dev` / `enterprise-analytics-dev` |
| Data bucket | `enterprise-analytics-dev-453711491609-us-west-2-data` |
| Results bucket | `enterprise-analytics-dev-453711491609-us-west-2-results` |
| Configuration | `infrastructure/cdk/config.development.json`; sanitized example alongside it |

Before deployment, read-only checks found `CDKToolkit` absent and only Athena's `primary` workgroup; `iam:GetRole` was denied for the selected SSO identity. Those were historical preparation findings. The user's later `CREATE_COMPLETE` reports supersede the missing-stack blocker. Exact administrator actions, deployed IAM policy attachments, and resource outputs were not supplied or reverified here; do not infer them from the stack statuses or silently switch profiles.

The reviewed configuration specifies this stable IAM role ARN for the two data-role trusts, derived from the verified STS role name and locally configured Identity Center region:

`arn:aws:iam::453711491609:role/aws-reserved/sso.amazonaws.com/us-west-2/AWSReservedSSO_PowerUserAccess_95483085e85e3a9b`

The initial plan required administrator confirmation before creation because `GetRole` was denied; deployed trust was not independently rechecked in this update. AWS documents this [Identity Center role path](https://docs.aws.amazon.com/singlesignon/latest/userguide/referencingpermissionsets.html). The configured trust is restricted to that role, not the whole account. If its Identity Center assignment is deleted/recreated, its suffix can change and a reviewed trust update is necessary.

## Reviewed resources and IAM configuration

The synthesized application template contains 41 resources:

- Two private, versioned, SSE-S3-encrypted buckets with public access blocked, TLS required, and retained on stack removal. Source versions have no expiration. Results expire after 7 days (noncurrent versions also 7 days); incomplete multipart uploads are aborted after 1 day.
- Two bucket policies, including conditional source writes. Loader permissions cover exactly 27 canonical Parquet keys plus four manifests; it cannot append extra source files after readiness. Source objects cannot be overwritten through the approved loader protocol/permissions.
- One Glue database and 27 explicit external Parquet tables: `retail-v1` (7), `parity-v1` (7), `parity-legacy-v1` (6), and `parity-no-returns-v1` (7 with empty returns). Every table points to its own snapshot/table prefix. The database uses IAM-compatible default table permissions; existing account-level Lake Formation settings are untouched.
- One retained Athena engine 3 SQL workgroup with enforced results location, SSE-S3, expected bucket owner, query metrics, and a **10 MiB (10,485,760 byte)** per-query cutoff.
- Two roles: `enterprise-analytics-dev-dataset-loader` and `enterprise-analytics-dev-query-executor`, with two inline policies and three generated managed overflow policies. The loader can conditionally upload/read the exact source keys and inspect deployed schemas; it cannot change Glue or execute Athena. The query role can read those sources/catalog schemas, run/cancel/page queries only in the dedicated workgroup, and read/write results under `queries/`; it cannot alter source data.
- One CloudWatch alarm on aggregate Athena `ProcessedBytes` across succeeded/failed/canceled DML queries. The alarm threshold is 100 MiB; it monitors rather than automatically limiting total spend.

The reviewed local template is `artifacts/cdk.reviewed.out/enterprise-analytics-dev-data-layer.template.json`, SHA-256 `ec1f978b9741d2cae4f24b09837e5d082525d9c2da29dafe41001d2862ed6940`. Its assembly has no missing lookup context. Artifacts are ignored by Git and can be regenerated from the committed configuration. A bootstrap template was displayed locally with `cdk bootstrap --show-template` and saved to `artifacts/cdk.bootstrap-template.yaml`; displaying it did not create a bootstrap stack.

The application enforces tenant/region predicates from trusted context. Anyone with direct query-role/S3 access can read all rows in its approved snapshots; this is **not Lake Formation row-level security**. Do not use this development role as a production tenant boundary.

## Bootstrap scope

The user reports the bootstrap completed. The original approval scope included the standard `CDKToolkit` asset bucket, ECR repository, SSM version parameter, and five roles (deployment, CloudFormation execution, file/image publication, lookup), plus supporting policies. These are additional to the 41 synthesized application resources. Future bootstrap changes require their own authorization.

The reviewed bootstrap plan specifies [deployment-policy.development.json](../infrastructure/cdk/deployment-policy.development.json) instead of default AdministratorAccess, with an administrator-created `enterprise-analytics-dev-cdk-execution` policy. Its permissions are constrained to the two development buckets, new Glue database/table namespace, named workgroup, two data roles, stack-generated policies (including attachment inspection), and development alarms. It also grants read-only `ssm:GetParameters` on the exact `/cdk-bootstrap/hnb659fds/version` parameter referenced by the synthesized assembly. Earlier read-only IAM Access Analyzer validation returned no findings. The user-reported stack success does not independently confirm which execution policy was attached; that attachment was not rechecked here. Bootstrap requires IAM/control-plane privileges; this policy is for subsequent CloudFormation execution. Managing role policies is privileged, so this is for reviewed development code, not a security boundary against arbitrary CDK applications. Do not broaden permissions automatically if a future deployment encounters an error.

## Operator reference commands — not rerun in this update

Run from the repository root in `enterprise-analytics`. The repository pins a compatible CDK CLI in `infrastructure/cdk/tooling`; the pre-existing global CLI 2.1138.0 cannot read CDK library 2.275.0's assembly schema and is left unchanged.

Offline preparation commands:

```sh
poetry install --with dev
npm ci --prefix infrastructure/cdk/tooling --ignore-scripts
JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache \
  poetry run python -m infrastructure.cdk.app \
  --config infrastructure/cdk/config.development.json --outdir artifacts/cdk.development.out
JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache \
  infrastructure/cdk/tooling/node_modules/.bin/cdk synth \
  --app 'poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json' \
  --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices \
  --output artifacts/cdk.reviewed.out --quiet
poetry run python tests/aws_fixture_data.py --output-dir artifacts/aws-datasets
```

The following block retains the initial reviewed deployment/publication sequence and the user-executed live-test command. The individual IAM/publication commands and exact deployment invocations were not reported, so they are not asserted as executed. Do not repeat resource creation or overwrite immutable snapshots as part of this documentation update. Future AWS mutations need explicit authorization and the correct privileges; all AWS CLI commands below explicitly select the development profile/region.

```sh
aws iam create-policy --profile analytics-dev --region us-west-2 \
  --policy-name enterprise-analytics-dev-cdk-execution \
  --policy-document file://infrastructure/cdk/deployment-policy.development.json

infrastructure/cdk/tooling/node_modules/.bin/cdk bootstrap \
  aws://453711491609/us-west-2 --profile analytics-dev --region us-west-2 \
  --cloudformation-execution-policies \
  arn:aws:iam::453711491609:policy/enterprise-analytics-dev-cdk-execution \
  --no-telemetry --no-notices

infrastructure/cdk/tooling/node_modules/.bin/cdk deploy \
  enterprise-analytics-dev-data-layer --app artifacts/cdk.reviewed.out \
  --profile analytics-dev --region us-west-2 --require-approval broadening \
  --no-telemetry --no-notices

poetry run analytics-publish --config infrastructure/cdk/config.development.json \
  --source-dir artifacts/aws-datasets/retail-v1 --dataset-version retail-v1 --seed 20260101
poetry run analytics-publish --config infrastructure/cdk/config.development.json \
  --source-dir artifacts/aws-datasets/parity-v1 --dataset-version parity-v1
poetry run analytics-publish --config infrastructure/cdk/config.development.json \
  --source-dir artifacts/aws-datasets/parity-legacy-v1 --dataset-version parity-legacy-v1
poetry run analytics-publish --config infrastructure/cdk/config.development.json \
  --source-dir artifacts/aws-datasets/parity-no-returns-v1 --dataset-version parity-no-returns-v1

poetry run pytest tests --run-aws --aws-config=infrastructure/cdk/config.development.json -m aws_integration -q
```

The publisher verifies the selected account, assumes only the loader role, checks schemas/checksums, and makes the ready manifest visible last. Existing/partial versions are rejected rather than overwritten; a partial failure requires an explicitly reviewed cleanup or a new configured version. Live tests assume the query role and independently compare both adapters with literal fixture answers. Internal query IDs, bytes, timings, dataset/metric versions are written to ignored `artifacts/aws-parity-diagnostics.jsonl`. Missing configuration errors instead of skipping a requested AWS run. Default tests and ordinary CI create no AWS sessions/queries.

The user's live result was **66 passed, 458 deselected in 111.94 seconds**. It covers the three parity snapshot variants; it does not by itself establish publication of synthetic `retail-v1`, which is not queried by this suite. Exact publication inventory, deployed outputs/IAM details, and measured costs were not independently verified here. The cancellation fix and offline regressions are present at `ae68d2c`, covered by the recorded current-code offline checks. See [progress](progress.md) for verification provenance and remaining review/merge work.

## Cost assumptions and controls

The fixture set is small and uses serverless Athena SQL, S3, Glue metadata, and one CloudWatch alarm; the reviewed template has no EC2, NAT gateway, Spark, or capacity reservation. The original **illustrative estimate** was 100 queries at a 10 MB billable minimum and $5/TB, about $0.005 of Athena scan charges before retries. This remains a planning assumption, not a measured bill, current quote, or hard budget; rates and actual spend were not rechecked in this update. S3 requests/storage/transfer, Glue metadata, CloudWatch alarm/metric usage, and retained bootstrap artifacts are additional. Source object versions persist until explicitly removed.

The per-query cutoff is not an aggregate cost cap, can overshoot at cancellation boundaries, and does not eliminate charges for canceled queries. Up to three explicitly retryable executions can consume scan charges. Repeated test runs and leaving monitoring/storage enabled continue to incur costs. Current references: [Athena pricing](https://aws.amazon.com/athena/pricing/), [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/), and [Athena query limits](https://docs.aws.amazon.com/athena/latest/ug/workgroups-setting-control-limits-cloudwatch.html).

## Cleanup — document only, not executed

After a separate cleanup decision, remove the application stack with the pinned CLI and same explicit profile. Buckets, Glue database/tables, and workgroup are retained; destroying the stack removes its roles/policies/alarm, so retained data will not automatically be queryable through those roles.

```sh
infrastructure/cdk/tooling/node_modules/.bin/cdk destroy enterprise-analytics-dev-data-layer \
  --app artifacts/cdk.reviewed.out --profile analytics-dev --region us-west-2
aws athena delete-work-group --work-group enterprise-analytics-dev --recursive-delete-option \
  --profile analytics-dev --region us-west-2
aws glue delete-table --database-name enterprise_analytics_dev --name REVIEWED_TABLE_NAME \
  --profile analytics-dev --region us-west-2
aws glue delete-database --name enterprise_analytics_dev --profile analytics-dev --region us-west-2
aws s3api list-object-versions --bucket REVIEWED_BUCKET --profile analytics-dev --region us-west-2
aws s3api delete-objects --bucket REVIEWED_BUCKET --delete file://reviewed-version-deletions.json \
  --profile analytics-dev --region us-west-2
aws s3api delete-bucket --bucket REVIEWED_BUCKET --profile analytics-dev --region us-west-2
```

Review each exact version ID/delete marker before deletion; `s3 rb --force` is insufficient for versioned buckets. Retained named resources require import/reconciliation or explicit cleanup before redeploying a removed stack. Do not delete a shared `CDKToolkit`; bootstrap cleanup and execution-policy removal require their own administrator review after confirming no dependent stacks remain.

## Official implementation references

Consulted during implementation on 2026-11-05; locked SDK versions are in `poetry.lock`:

- [Athena execution parameters and restrictions](https://docs.aws.amazon.com/athena/latest/ug/querying-with-prepared-statements.html), [Boto3 StartQueryExecution](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/start_query_execution.html), [GetQueryExecution](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/get_query_execution.html), [GetQueryResults](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/get_query_results.html), [StopQueryExecution](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/stop_query_execution.html), [Athena data types](https://docs.aws.amazon.com/athena/latest/ug/data-types.html).
- [S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html), [Boto3 PutObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html), [HeadObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/head_object.html), [GetObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html), [Glue GetTable](https://docs.aws.amazon.com/boto3/latest/reference/services/glue/client/get_table.html).
- [CDK S3 Bucket](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_s3/Bucket.html), [CDK CfnTable](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_glue/CfnTable.html), [CDK CfnWorkGroup](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_athena/CfnWorkGroup.html), [Glue ancestor permissions](https://docs.aws.amazon.com/glue/latest/dg/glue-specifying-resource-arns.html), [Athena monitoring metrics](https://docs.aws.amazon.com/athena/latest/ug/query-metrics-viewing.html), [CDK bootstrapping](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping-env.html).
- [CloudFormation service roles](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-iam-servicerole.html) and [Systems Manager parameter types](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cloudformation-supplied-parameter-types.html).
- [IAM managed-policy attachment inspection](https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListEntitiesForPolicy.html).
