# Milestone 5 Q18 repair and next campaign preparation

Status: The approved repair uploaded the reviewed candidate and verified READY v7, but local CDK hit its 1800-second bound before any candidate invocation. Mandatory original restoration/smoke passed: Runtime/DEFAULT READY v8, stack UPDATE_COMPLETE, original parity artifact/version/configuration, policies and seven-day retention. Repair usage is 1/40, retail-closed, 39 unspent and no reserve used. M5 remains open; PR #6 remains unmerged. See [progress](progress.md) for actual evidence and the offline next task.
The original live result remains **35/36**, its ledger **38/40 and closed**, and M4 **28/40**.
The original ZIP, uploaded version, goldens and reviewed assemblies are unchanged.

The approved continuation deployed candidate v9 successfully, but ConnectTimeoutError in the additional checkpoint stopped execution before any candidate call. Mandatory original restoration/smoke passed on Runtime/DEFAULT READY v10, stack UPDATE_COMPLETE. Continuation is 1/39 and closed, aggregate 2/40 with 38 remaining. The required 39-call sequence cannot fit that remainder; M5 remains open and PR #6 unmerged. No automatic retry or budget change is authorized.
The [continuation execution record](milestone-5-q18-continuation-proposal.md) retains
its separate reviewed v8 identity, actualv9/v10 results and failure evidence. Do not rewrite
the review or any closed counter to resume.

## Evidence and correction

The committed campaign evidence records Q18 (`Show net_revenue for yesterday.`) as one
model call, no tools and no results, followed by clarification. The configured reference
date was 2025-04-01. The question guard correctly resolves the request to net_revenue,
[2025-03-31,2025-04-01), no grouping and no filters. The agent's no-tool `end_turn`
branch nevertheless returned a generic clarification. This is an orchestration failure;
the evidence does not indicate a date arithmetic, Athena, IAM or SDK transport failure.

The detailed operation files are in the original checkout at
`artifacts/milestone-5/operations/20261109T171341Z/`, not in GitHub. The supplied source patch used the
committed summary. This checkout then inspected the retained original report and verified
its hash/diagnostics, reproducing the recorded response shape with authored Converse turns.
The preparation review claimed no raw model transcript or fresh AWS checkpoint. The
later approved execution separately retained fresh original/candidate/restored checkpoints.
The reported suite SHA is `7ccd5b43ec1ea38dfc0a17c562e1cd51a74f36e0bff247fac5a1759da5855021`.

For a fully resolved numeric request, a valid text-only model end-turn now causes the
server to execute the complete typed plan once through the same four-tool boundary.
The shared executor validates the request and response, passes the original trusted
authorization context, records real tool work and checks the existing time/tool limits.
The answer still comes only from validated adapter results. There is no extra model call,
model-generated arithmetic, hardcoded answer, prompt-only retry or fabricated model turn.
Actual server-planned tool records use `resolved-plan-` identifiers.

The fallback applies only with no metric results and no earlier tool error. It does not
repair partial results, retry failed queries, override model filtering, or bypass malformed
responses, token limits, unknown clauses or missing data. Ambiguous/unsupported questions
still clarify before model or tool execution. Metadata tool routing remains unchanged.

## Offline coverage

- Reproduce Q18 with a real DuckDB adapter and independent $120.25 minus $10.00 fixture:
  exact **110.25 USD**, excluding March 30, April 1, another tenant and hidden East data.
- Exercise all 36 frozen cases through the real question guard/agent/tool/render path:
  numeric cases receive a no-tool model turn, clarifications remain unexecuted, and
  metadata uses its existing tool route. Adapter responses use frozen expectations;
  this proves orchestration, not live model quality or canonical-data arithmetic.
- Independently exercise all five metrics against the authored parity fixture, leap-day,
  month/year boundaries, multi-metric/multi-period plans, and repeated-request isolation.
- Verify whole-plan tool budget rejection, failure evidence/no retry, missing returns,
  identity override rejection, content-filter/timeout stops and collision-free record IDs.
- Run the existing agent, semantic, operator, packaging and infrastructure checks.

The patch author reported seven targeted regressions failing before the correction. Final full verification and
environment details are recorded in [progress](progress.md).

## Prepare the next live attempt as one reviewed bundle

The correction changes **deployed agent code**. The original frozen ZIP cannot execute it.
The old environment-only runbook is therefore not a deployment recipe for this correction.
Keep the original ZIP, version, assemblies, goldens, operation evidence and ledgers intact.

All seven preparation items below were completed before approval. The proposal now
records actual upload/version, candidate READY and successful restoration, separately
from unrun candidate acceptance. The administrator supplied the exact candidate-key grant;
the agent made no IAM change. The profile remains analytics-dev, account 453711491609,
region us-west-2. Neither Q18's source failure nor the local CDK timeout establishes an
additional IAM requirement. The following list preserves the preparation checklist.

1. Apply the source patch to the same milestone branch, inspect the retained Q18 report
   and verify its recorded hash/diagnostics. Do not rewrite failed acceptance evidence or
   weaken the frozen Q18 expectation. Run the required offline checks in Conda/Poetry.
2. Build a new project wheel and candidate Python 3.12 Linux ARM64 ZIP in a **new** candidate
   directory using the committed lockfile and verified wheel cache. Use the existing
   packaging module with explicit output/project-wheel paths; do not overwrite
   `artifacts/agentcore/agent.zip`. Inspect the ZIP's agent source to prove it includes this
   correction, record its SHA-256/manifest, and reproduce its build before upload approval.
3. Prepare a candidate runtime assembly with the new code object's SHA-addressed key plus
   the already reviewed retail settings. Preserve the original restore assembly byte-for-byte.
   The reviewed diff must allow the candidate code reference and exactly the three retail
   settings; every other resource, permission, model, network and lifecycle property stays fixed.
4. Prepare explicit **candidate versus restoration artifact pins** in operator verification.
   The current `retail_checkpoint.py` and `deployment.py` intentionally require the original
   artifact/template. They must validate the candidate ZIP/key/version for retail and the
   original ZIP/key/version for restoration. Do not globally replace the original constants,
   relax checksum/version checks, or edit the original restoration proof to accept the candidate.
   The upload's actual S3 VersionId must be bound and verified after the approved upload,
   before deployment; it cannot be known or invented during offline preparation.
5. Prepare a **new, separately identified campaign** with a new immutable ledger path and
   explicit reviewed limit. The current runner/CLI use the first campaign's closed ledger;
   implement and test explicit new-campaign selection without resetting or redirecting it.
   Bind the new campaign to candidate/template hashes and preserve the original campaign ID,
   final ledger SHA `fad2f259d79c98d694b6452aec675df474726c225ff5bf72244b5abbef7713c9`,
   and M4 ledger SHA `f04f9cc568d4842b6c9e0118f01cf5b92e496c40658f25a9fdc364075eb17f14`.
   Unknown/unpinned configurations must fail before dispatch; restoration must use the new
   campaign's protected allowance while checking the original restored artifact.
6. Offline-test the complete candidate/restore/campaign path with realistic SDK responses,
   including timestamp serialization, mismatched hashes/versions, attempted old-ledger reuse,
   failure/interruption accounting, and successful restoration. Keep new live flags gated.
7. Present one concrete upload/deployment/evaluation/restoration proposal. Suggested new
   maximum: **40 additional calls** = 1 usual warm-up + 1 Q18 probe + all 36 suite requests
   + 1 restored parity smoke + 1 controlled reserve. The probe does not replace Q18 in the
   full suite or alter its denominator. Stop after a failing probe, preserve its evidence,
   and restore; do not use a selective rerun to relabel the first campaign as passed.

The approved procedure was: upload the verified candidate once, pin the returned version,
perform fresh preflight, deploy/verify READY, run the counted probe/full campaign, then
restore the original parity artifact/configuration in `finally` and verify its counted smoke.
Record actual Runtime versions; restoring a configuration does not restore a historical
version number. Mark M5 complete only after all 36 cases and all restoration/report gates pass.

The correction removes the reproduced offline failure class. The candidate reached READY
but was not invoked before the local CDK timeout. No new live answer-quality acceptance
is claimed; historical first-campaign failure evidence remains intact.
