"""Explicit shared-agent UI execution; SDKs and cloud verification stay in adapters."""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4

import boto3
from botocore.config import Config

from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
from enterprise_analytics_agent.adapters.bedrock_agent import ConverseClient
from enterprise_analytics_agent.adapters.operator_reads import ReadPool
from enterprise_analytics_agent.adapters.ui_live import runtime_lease
from enterprise_analytics_agent.adapters.ui_local_agent import LocalBedrockQuestions
from enterprise_analytics_agent.adapters.ui_release import (
    ReleaseKind,
    ReleaseRecord,
    make_record,
    validate_record,
    verify_local_release,
    verify_publication,
    verify_release,
)
from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.retail_evaluation.agent_cli import _check_restoration_smoke
from enterprise_analytics_agent.retail_evaluation.cases import load_goldens, load_suite
from enterprise_analytics_agent.retail_evaluation.client import validate_target_response
from enterprise_analytics_agent.retail_evaluation.judge import judge_response
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.retail_evaluation.reporting import _redact
from enterprise_analytics_agent.ui.models import (
    AskRequest,
    UiError,
    UiResult,
    unreported_diagnostics,
)
from enterprise_analytics_agent.ui.shared import (
    SdkAttemptRecorder,
    SharedLedger,
    SharedPurpose,
    SharedReview,
)


class SharedQuestions:
    """One agent implementation, one question quota, and separately recorded SDK work.

    Construction and status are offline. Every new question freshly verifies the
    release/data before reservation; browser arguments supply no trusted scope.
    Rollback smoke is an operator-only purpose bound to the original release.
    """

    def __init__(
        self,
        root: Path,
        review: SharedReview,
        release: ReleaseRecord,
        canonical_dir: Path,
        *,
        purpose: SharedPurpose = "question",
    ) -> None:
        self.root, self.review, self.release = root.resolve(), review, release
        self.canonical_dir = canonical_dir.resolve()
        self.purpose = purpose
        self.kind: ReleaseKind = "original" if purpose == "rollback_smoke" else "candidate"
        validate_record(review, release, kind=self.kind)
        if self.kind == "candidate":
            verify_local_release(self.root, review, self.canonical_dir)
        self.ledger = SharedLedger(self.root, review)

    def public_state(self, mode: str) -> dict[str, object]:
        # Only normal candidate execution is exposed in the browser.
        if self.purpose != "question":
            raise UiError("Protected smoke execution is operator-only.")
        summary = self.ledger.summary()
        source_error = ""
        try:
            verify_local_release(self.root, self.review, self.canonical_dir)
        except (UiError, OSError, ValueError, ImportError):
            source_error = (
                "The local source or data no longer matches this approved release. "
                "Agent execution is unavailable."
            )
        verified = summary["purposes"]
        assert isinstance(verified, dict)
        ready = bool(
            verified["verification"] == 1
            and not summary["failed"]
            and not summary["incomplete"]
            and not summary["expired"]
            and not verified["rollback_smoke"]
            and not source_error
        )
        return {
            "enabled": ready,
            "error": source_error
            or (
                "Shared verification/allowance is not ready; inspect its evidence."
                if not ready
                else ""
            ),
            "dataset": self.review.target.dataset_version,
            "reference_date": self.review.target.reference_date.isoformat(),
            "tenant": self.review.tenant_id,
            "regions": list(self.review.allowed_regions),
            "runtime_version": self.release.runtime_version,
            "description": (
                "Local agent · canonical DuckDB + Amazon Bedrock"
                if mode == "local_agent"
                else f"AWS AgentCore · shared retail v{self.release.runtime_version}"
            ),
            "cost_notice": (
                "BILLABLE: Bedrock, up to six model calls per question; shared question budget."
                if mode == "local_agent"
                else "BILLABLE: AgentCore + Bedrock + Athena; one Runtime call per question."
            ),
            "source_sha256": self.release.source_sha256,
            "archive_sha256": self.release.archive_sha256,
        }

    def ask(self, request: AskRequest) -> UiResult:
        if request.mode not in {"local_agent", "live"}:
            raise UiError("Choose one of the explicitly enabled shared-agent modes.")
        if Path.cwd().resolve() != self.root:
            raise UiError("Shared agent execution must run from the original checkout root.")
        if self.purpose == "question":
            purposes = self.ledger.summary()["purposes"]
            assert isinstance(purposes, dict)
            if purposes["verification"] != 1:
                raise UiError("Counted Q18 verification is required before shared UI questions.")
        elif self.purpose == "verification":
            if request.question != "Show net_revenue for yesterday.":
                raise UiError("The protected verification slot is only for the frozen Q18 probe.")
        elif request.question != "Show net_revenue for January 2025 by region.":
            raise UiError("The rollback slot is only for the original parity smoke question.")
        with runtime_lease(self.root):
            return self.ledger.execute(
                request, lambda: self._prepare(request), purpose=self.purpose
            )

    def _publication_heads(self, pool: ReadPool) -> dict[str, object]:
        return verify_publication(
            self.review,
            pool.view(time.monotonic() + 180, "ui-shared-canonical-publication"),
            root=self.root,
        )

    def _local_client(self, pool: ReadPool) -> ConverseClient:
        started = time.monotonic()
        context = {
            "phase": "ui-local-model-setup",
            "service": "bedrock-runtime",
            "operation": "create_client",
            "attempt": 1,
        }
        pool.record({**context, "event": "started"})
        try:
            client = pool.session.client(
                "bedrock-runtime",
                config=Config(
                    connect_timeout=5,
                    read_timeout=30,
                    retries={"total_max_attempts": 1, "mode": "standard"},
                ),
            )
            if time.monotonic() - started >= 30:
                raise UiError("Local model client setup exceeded its budget; no call was sent.")
        except BaseException as exc:
            pool.record({**context, "event": "failed", **error_record(exc, "ui-local-model-setup")})
            raise
        endpoint = getattr(getattr(client, "meta", None), "endpoint_url", "")
        pool.record({**context, "event": "succeeded", "endpoint_host": urlsplit(endpoint).hostname})
        return cast(ConverseClient, client)

    def _guard_dispatch(
        self, pool: ReadPool, dispatch: Callable[[SdkAttemptRecorder], UiResult]
    ) -> Callable[[SdkAttemptRecorder], UiResult]:
        def run(recorder: SdkAttemptRecorder) -> UiResult:
            try:
                return dispatch(recorder)
            except BaseException as exc:
                try:
                    pool.record(
                        {
                            "event": "ui-shared-dispatch-failed",
                            **error_record(exc, "ui-shared-dispatch"),
                        }
                    )
                except Exception:
                    # The durable reservation remains spent if diagnostics storage fails.
                    pass
                raise

        return run

    def _prepare(self, request: AskRequest) -> Callable[[SdkAttemptRecorder], UiResult]:
        pool = ReadPool(None, self.ledger.directory / "operator-reads.jsonl")
        try:
            if self.kind == "candidate":
                local_evidence = verify_local_release(self.root, self.review, self.canonical_dir)
            else:
                local_evidence = {"scope": "original rollback; no shared-source equivalence claim"}
            pool.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
            checkpoint = verify_release(
                self.review,
                kind=self.kind,
                session=pool.view(time.monotonic() + 180, "ui-shared-release"),
            )
            observed = make_record(self.review, checkpoint, kind=self.kind)
            if observed.runtime_version != self.release.runtime_version:
                raise UiError("The observed Runtime version differs from its bound release record.")
            publication = self._publication_heads(pool) if self.kind == "candidate" else None
            evidence = (
                json.dumps(
                    _redact(
                        {
                            "checkpoint": checkpoint,
                            "release": observed.model_dump(mode="json"),
                            "local": local_evidence,
                            "publication": publication,
                            "purpose": self.purpose,
                        }
                    ),
                    indent=2,
                )
                + "\n"
            )
            self.ledger.directory.mkdir(parents=True, exist_ok=True)
            with (self.ledger.directory / f"preflight-{request.request_id}.json").open("x") as out:
                out.write(evidence)
            if request.mode == "local_agent":
                client = self._local_client(pool)

                def local_dispatch(recorder: SdkAttemptRecorder) -> UiResult:
                    result = LocalBedrockQuestions(
                        self.canonical_dir,
                        self.review.agent_config,
                        client=recorder.converse(client),
                    ).ask(request.question)
                    validate_target_response(result.response, self.review.target)
                    return result

                return self._guard_dispatch(pool, local_dispatch)
            target = (
                RetailTarget(
                    runtime_arn=self.review.target.runtime_arn,
                    dataset_version="parity-v1",
                    reference_date="2025-02-01",
                )
                if self.kind == "original"
                else self.review.target
            )
            setup = pool.view(time.monotonic() + 30, "ui-shared-invocation-setup")
            invoke = create_runtime_invoker(
                target,
                session=pool.session,
                identity_session=setup,
                client_factory=lambda config: setup.invocation_client(
                    runtime_arn=target.runtime_arn, config=config
                ),
            )

            def aws_dispatch(recorder: SdkAttemptRecorder) -> UiResult:
                started = time.monotonic()
                reply = recorder.invoke_runtime(
                    invoke,
                    payload=AgentRequest(question=request.question).model_dump_json().encode(),
                    session_id=str(uuid4()),
                )
                try:
                    response = AgentResponse.model_validate_json(reply.body.read())
                finally:
                    reply.body.close()
                validate_target_response(response, target)
                expected = self.review.agent_config.model_dump(mode="json")
                if self.kind == "original":
                    expected["reference_date"] = "2025-02-01"
                if response.diagnostics.configuration != expected:
                    raise UiError("The agent reported a different model configuration.")
                if self.purpose == "verification":
                    suite = load_suite(self.root / "evaluations/retail-v1/questions.json")
                    goldens = load_goldens(
                        self.root / "evaluations/retail-v1/expected-results.json", suite
                    )
                    case = next(case for case in suite.cases if case.id == "Q18")
                    golden = next(item for item in goldens.cases if item.case_id == "Q18")
                    judged = judge_response(
                        case,
                        golden,
                        response,
                        target,
                        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                        raw_response=response.model_dump(mode="json"),
                    )
                    path = self.ledger.directory / f"verification-{request.request_id}.json"
                    encoded = json.dumps(_redact(judged.model_dump(mode="json")), indent=2)
                    with path.open("x") as out:
                        out.write(encoded + "\n")
                    if judged.status != "passed":
                        raise UiError(
                            "Q18 verification failed its full independent plan/result gate."
                        )
                if self.purpose == "rollback_smoke":
                    _check_restoration_smoke(response)
                return UiResult(
                    mode="live",
                    response=response,
                    elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                    unreported_diagnostics=unreported_diagnostics(response),
                )

            return self._guard_dispatch(pool, aws_dispatch)
        except Exception as exc:
            pool.record(
                {"event": "ui-shared-preflight-failed", **error_record(exc, "ui-shared-preflight")}
            )
            raise UiError(
                "Shared preflight failed; no question sent. Inspect operator diagnostics."
            ) from exc


def main(argv: list[str] | None = None) -> int:
    """Counted, operator-only verification/rollback smoke; never a browser route."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purpose", choices=("verification", "rollback_smoke"), required=True)
    parser.add_argument("--invoke-live", action="store_true", required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--release-record", type=Path, required=True)
    parser.add_argument(
        "--canonical-dir", type=Path, default=Path("artifacts/milestone-5/canonical/retail-v1")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise UiError("Output exists; preserve it and inspect the allowance before resuming.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        review = SharedReview.model_validate_json(args.review.read_text())
        record = ReleaseRecord.model_validate_json(args.release_record.read_text())
        purpose: SharedPurpose = args.purpose
        root = Path(__file__).resolve().parents[3]
        backend = SharedQuestions(root, review, record, args.canonical_dir, purpose=purpose)
        question = (
            "Show net_revenue for yesterday."
            if purpose == "verification"
            else "Show net_revenue for January 2025 by region."
        )
        result = backend.ask(AskRequest(mode="live", question=question, request_id=uuid4()))
        encoded = (
            json.dumps(
                _redact(
                    {
                        "purpose": purpose,
                        "result": result.model_dump(mode="json"),
                        "campaign": backend.ledger.summary(),
                    }
                ),
                indent=2,
            )
            + "\n"
        )
        with args.output.open("x") as out:
            out.write(encoded)
        print(f"Counted {purpose} passed; evidence: {args.output}")
        return 0
    except Exception as exc:
        print(json.dumps(error_record(exc, "ui-shared-smoke"), indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
