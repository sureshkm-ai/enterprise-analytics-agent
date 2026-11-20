# Workbench request failures: client repair

The owner reported **24/40 attempts** and only Qwen enabled after the earlier
20/40 acceptance checkpoint. This repair is offline-verified; it has not been
executed on the owner's Mac and makes no new live-acceptance claim. The four
new request records are local and are not present in GitHub.

## Findings and changes

- `InvokeAgentRuntime` incorrectly reused the 30-second configuration-read
  client. It now uses a separate **300-second read timeout**, covering the
  hosted 90-second agent plus 180-second response window. Configuration reads
  stay at 30 seconds. `total_max_attempts=1` remains enforced. A simulated
  45-second first response fails with the previous setting and passes with the
  repair. This is a confirmed configuration defect; **a timeout is not yet the
  confirmed cause of attempts 21–24**. The 35.5-second screenshot alone cannot
  establish that, particularly because the Runtime sends SSE heartbeats.
- Every failed question previously quarantined its model, even after successful
  acceptance. Under the exact client repair, accepted models can receive a new
  **manual** question after a recorded transport failure has settled for five
  minutes. The timeout may have occurred after AWS completed work; the failed
  attempt stays spent. There is no invocation retry, duplicate request-ID reuse,
  model substitution or increase in budget.
- A validated answer whose optional word stream falls back, and a completed
  question that hits its iteration/token/deadline limit, no longer prove that
  an accepted model is unavailable. They remain recorded failures. Unknown
  exceptions, incorrect/unvalidated results, failed acceptance, incomplete SDK
  accounting, expiry, cleanup and exhausted ordinary allowance stay paused.
- New private `error-<request-id>.json` files capture the failing stage, exception
  type, Runtime/session identifiers and redacted AWS error metadata when supplied.
  The browser shows an authored explanation and diagnostic path. It does not
  expose raw SDK messages, credentials, prompts or trace locals.
- The dropdown distinguishes **Account access unavailable**, **Acceptance
  failed**, **Waiting after connection failure**, and **Request failed — inspect
  details**. A recovered model is ready with a notice about its previous request.

The Botocore [configuration reference](https://docs.aws.amazon.com/botocore/latest/reference/config.html)
defines read timeouts separately from retries; `total_max_attempts=1` disables
automatic retries. A longer client timeout changes neither the deployed agent's
model/tool/token bounds nor its semantic results.

## Existing release and evidence

`evaluations/bedrock-streaming/workbench.operator-repair.json` binds the original
review and all **80 accepted source/assets** to exactly six operator/UI file
changes, including two new helper modules. Every agent, semantic, model adapter,
presentation and hosting source file remains identical to the deployed release.
The original ZIP/hash/S3 VersionId, templates, Runtime versions, approvals,
dataset and acceptance records remain authoritative. The repair needs no rebuild,
upload, deployment, new profile or IAM change.

The repair requires the **existing original-checkout ledger with at least 24
recorded attempts**. It cannot initialize a fresh allowance or use an older
20-attempt snapshot. Historical campaigns retain their original failure rules.
Failed counters/receipts are read without rewriting; all later questions append
to the same campaign, subject to its original expiry and ordinary cap.

## Inspect and restart in the original checkout

Update the existing PR branch with this repair. Keep all ignored local artifacts,
actual release records, canonical data, reservations and ledgers. A fresh clone
does not contain that operational evidence.

From the original repository root, inspect the last eight attempts without AWS:

```sh
conda activate enterprise-analytics
poetry run python -m enterprise_analytics_agent.ui.workbench_repair \
  --review evaluations/bedrock-streaming/review.workbench.proposed.json \
  --operator-repair evaluations/bedrock-streaming/workbench.operator-repair.json \
  --last 8
```

The report shows actual SDK exception types, retained outcomes, classified
failures, unchanged usage and remaining ordinary slots. It reports missing
local evidence as an error, never as zero usage. If attempts 21–24 show
`ReadTimeoutError`, that confirms the suspected client timeout. Different errors
must be diagnosed from their actual evidence. Unknown failures remain paused.

Stop the existing workbench in its owning terminal with Ctrl+C, then restart:

```sh
poetry run python -m enterprise_analytics_agent.ui --port 8501 --allow-live \
  --streaming-review evaluations/bedrock-streaming/review.workbench.proposed.json \
  --streaming-releases artifacts/bedrock-streaming/workbench-fix/operations-approved-01/releases.actual.json \
  --streaming-approval artifacts/bedrock-streaming/workbench-fix/approval.json \
  --streaming-operator-repair evaluations/bedrock-streaming/workbench.operator-repair.json \
  --canonical-dir artifacts/milestone-5/canonical/retail-v1
```

Refresh http://127.0.0.1:8501/?mode=live. Starting or refreshing does not submit
a question. Read the current ledger; do not assume that the old 20/40 or screenshot
24/40 snapshot is still current. The original expiry remains November 15, 2026,
5:59 p.m. CST. Cleanup and reserve stay unavailable for ordinary questions.

## Models that this client repair cannot enable

The retained [model diagnostics](../evaluations/bedrock-streaming/workbench.model-diagnostics.json)
show AWS account-model-unavailability responses for Sonnet, Opus, Astra and Sol.
Those responses include AWS RequestIds and an AWS Sales access-support link.
An administrator/account owner must resolve provider availability with AWS;
the evidence does not justify another IAM grant or another profile.

Gemma returned invalid `query_metric` arguments and Llama failed its complete-plan
case. They remain failed acceptance. The raw provider responses and later local
request evidence are not available in this review workspace, so no invented
argument correction or unverified model-enablement claim is made. Reassessing
these models requires an evidence-based agent change and separate live validation.
