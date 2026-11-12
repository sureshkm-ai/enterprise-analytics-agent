"""Explicit operator commands for the separately reviewed streaming release.

Default offline verification creates no AWS session or campaign. Live commands
require an invocation gate, exact approval and actual post-deployment bindings.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from enterprise_analytics_agent.adapters.model_stream_ui import (
    StreamingQuestions,
    verify_developer_identity,
    verify_local_inputs,
    verify_target,
)
from enterprise_analytics_agent.agent.questions import question_scope
from enterprise_analytics_agent.retail_evaluation.cases import (
    load_goldens,
    load_suite,
    verify_frozen_inputs,
)
from enterprise_analytics_agent.retail_evaluation.judge import judge_response
from enterprise_analytics_agent.retail_evaluation.models import GoldenCase, RetailCase
from enterprise_analytics_agent.ui.model_streams import (
    StreamingLedger,
    StreamingReleases,
    StreamingReview,
    StreamRelease,
)
from enterprise_analytics_agent.ui.models import AskRequest, UiError

ROOT = Path(__file__).resolve().parents[3]
ALL_METRICS = (
    "Show gross_sales, net_revenue, order_count, average_order_value and return_rate "
    "for January 2025 by region."
)


def _write_json_new(path: Path, value: object) -> None:
    # Serialize before creating a final evidence file.
    content = json.dumps(value, indent=2) + "\n"
    with path.open("x") as out:
        out.write(content)


@contextmanager
def _failure_report(path: Path, context: dict[str, object]) -> Iterator[None]:
    try:
        yield
    except BaseException as exc:
        try:
            _write_json_new(
                path,
                {
                    **context,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
        except Exception:
            # Secondary evidence I/O must not replace the operation's failure.
            pass
        raise


def _cleanup(review: StreamingReview, approval: object, output: Path) -> int:
    """Verify the retained Nova v15 under the NEW cleanup slot, not an old ledger.

    This path deliberately does not depend on the new archive, new releases,
    source fingerprint, model access or canonical downloads being available.
    """
    from datetime import UTC, datetime

    import boto3

    from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
    from enterprise_analytics_agent.adapters.operator_reads import ReadPool
    from enterprise_analytics_agent.adapters.ui_live import runtime_lease
    from enterprise_analytics_agent.adapters.ui_release import (
        ReleaseRecord,
        make_record,
        verify_release,
    )
    from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
    from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
    from enterprise_analytics_agent.ui.model_streams import verify_approval
    from enterprise_analytics_agent.ui.shared import SharedReview

    verify_approval(review, approval, now=datetime.now(UTC))
    if output.exists():
        raise UiError("Use a new cleanup report path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    old = SharedReview.model_validate_json(
        (ROOT / "evaluations/ui-shared/interactive-02.proposed.json").read_bytes()
    )
    expected = ReleaseRecord.model_validate_json(
        (ROOT / "artifacts/ui-shared/interactive-02-preparation/release-record.json").read_bytes()
    )
    ledger = StreamingLedger(ROOT, review)
    identifier = str(uuid4())
    with (
        _failure_report(
            output,
            {
                "operation": "legacy_cleanup",
                "request_id": identifier,
                "campaign_id": review.campaign_id,
                "review_sha256": review.sha256,
                "expected_runtime_version": "15",
            },
        ),
        runtime_lease(ROOT),
    ):
        pool = ReadPool(None, ledger.directory / "cleanup-reads.jsonl")
        pool.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
        import time

        reads = pool.view(time.monotonic() + 180, "streaming-legacy-cleanup")
        checkpoint = verify_release(old, session=reads, kind="candidate")
        verify_developer_identity(checkpoint["identity"])
        observed = make_record(old, checkpoint, kind="candidate")
        if observed.runtime_version != expected.runtime_version or observed.runtime_version != "15":
            raise UiError("The retained legacy Nova checkpoint drifted; no cleanup call was sent.")
        target = RetailTarget(
            runtime_arn=expected.runtime_arn,
            dataset_version="retail-v1",
            reference_date="2025-04-01",
        )
        invoke = create_runtime_invoker(target, session=pool.session, identity_session=reads)
        with ledger.attempt(identifier, "nova-lite", mode="live", cleanup=True) as record:
            record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
            try:
                reply = invoke(
                    payload=AgentRequest(question="Show net_revenue for yesterday.")
                    .model_dump_json()
                    .encode(),
                    session_id=str(uuid4()),
                )
                primary: BaseException | None = None
                try:
                    response = AgentResponse.model_validate_json(reply.body.read())
                except BaseException as exc:
                    primary = exc
                    raise
                finally:
                    try:
                        reply.body.close()
                    except BaseException:
                        if primary is None:
                            raise
                q18, golden = acceptance_cases(ROOT)[0]
                judgment = judge_response(q18, golden, response, target)
                if judgment.status != "passed":
                    raise UiError(
                        "The legacy restoration smoke did not match its independent values."
                    )
            except BaseException as exc:
                record(
                    {
                        "event": "failed",
                        "operation": "InvokeAgentRuntime",
                        "number": 1,
                        "error_type": type(exc).__name__,
                    }
                )
                raise
            record({"event": "returned", "operation": "InvokeAgentRuntime", "number": 1})
        content = (
            json.dumps(
                {
                    "restored_runtime_version": "15",
                    "new_campaign": review.campaign_id,
                    "judgment": judgment.model_dump(mode="json"),
                    "budget": ledger.summary(),
                },
                indent=2,
            )
            + "\n"
        )
        with output.open("x") as out:
            out.write(content)
    print(
        "Legacy Nova v15 cleanup smoke passed; new campaign is closed. Old ledgers are unchanged."
    )
    return 0


def acceptance_cases(root: Path) -> tuple[tuple[RetailCase, GoldenCase], ...]:
    """Compose a new question from frozen independent literals; never calculate with an adapter."""
    questions = root / "evaluations/retail-v1/questions.json"
    expected = root / "evaluations/retail-v1/expected-results.json"
    suite = load_suite(questions)
    goldens = load_goldens(expected, suite)
    verify_frozen_inputs(questions, expected, expected.with_name("oracle-provenance.json"), goldens)
    cases = {case.id: case for case in suite.cases}
    values = {case.case_id: case for case in goldens.cases}
    identifiers = ("Q01", "Q02", "Q03", "Q04", "Q05")
    combined = RetailCase(
        id="Q01",
        question=ALL_METRICS,
        kind="metric",
        expected_queries=tuple(
            query for key in identifiers for query in cases[key].expected_queries
        ),
        tags=("streaming-all-five", "composed-from-frozen-Q01-Q05"),
    )
    literal = GoldenCase(
        case_id="Q01",
        results=tuple(result for key in identifiers for result in values[key].results),
    )
    scope = question_scope(ALL_METRICS, suite.reference_date)
    if scope.clarification:
        raise UiError("The authored all-metric question exceeds the supported vocabulary.")
    for query in combined.expected_queries:
        scope.validate_query(query)
    return ((cases["Q18"], values["Q18"]), (combined, literal))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--releases", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument(
        "--canonical-dir", type=Path, default=Path("artifacts/milestone-5/canonical/retail-v1")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-offline")
    bind = commands.add_parser("bind-releases")
    bind.add_argument("--read-only-aws", action="store_true")
    bind.add_argument("--upload-response", type=Path, required=True)
    bind.add_argument("--output", type=Path, required=True)
    ask = commands.add_parser("ask")
    ask.add_argument("--invoke-live", action="store_true")
    ask.add_argument("--model", required=True)
    ask.add_argument("--mode", choices=("local_agent", "live"), default="live")
    ask.add_argument("--question", required=True)
    ask.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--invoke-live", action="store_true")
    evaluate.add_argument("--output", type=Path, required=True)
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--invoke-live", action="store_true")
    cleanup.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if Path.cwd().resolve() != ROOT:
            raise UiError("Run the streaming operator from the original checkout root.")
        review = StreamingReview.model_validate_json(args.review.read_bytes())
        if args.command == "cleanup":
            if not args.invoke_live or args.approval is None:
                raise UiError("Cleanup needs its explicit new-scope approval and --invoke-live.")
            return _cleanup(review, json.loads(args.approval.read_bytes()), args.output)
        verify_local_inputs(ROOT, review, args.canonical_dir)
        ledger = StreamingLedger(ROOT, review)
        if args.command == "verify-offline":
            checks = acceptance_cases(ROOT)
            print(
                json.dumps(
                    {
                        "passed": True,
                        "review_sha256": review.sha256,
                        "models": [t.model_key for t in review.targets],
                        "acceptance_questions_per_model": len(checks),
                        "budget": ledger.summary(),
                        "aws_calls": 0,
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "bind-releases":
            if not args.read_only_aws:
                raise UiError("Release binding requires explicit --read-only-aws.")
            # No uploads or mutations: bind the actual returned VersionId, then
            # independently read every exact deployment before saving any record.
            import boto3

            from enterprise_analytics_agent.adapters.model_stream_ui import READ_CONFIG
            from enterprise_analytics_agent.adapters.operator_reads import ReadPool

            upload = json.loads(args.upload_response.read_bytes())
            version = upload.get("VersionId")
            if (
                not isinstance(version, str)
                or not version
                or version.lower() in {"null", "pending", "unknown"}
            ):
                raise UiError("A real versioned S3 upload response is required.")
            pool = ReadPool(None, ledger.directory / "binding-reads.jsonl")
            pool.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
            import time

            reads = pool.view(time.monotonic() + 300, "streaming-release-binding")
            identity = reads.client("sts", config=READ_CONFIG).get_caller_identity()
            if identity.get("Account") != review.account:
                raise UiError("The development profile resolved to the wrong account.")
            verify_developer_identity(identity)
            bindings = []
            for target in review.targets:
                stack = reads.client("cloudformation", config=READ_CONFIG).describe_stacks(
                    StackName="enterprise-analytics-stream-" + target.model_key
                )["Stacks"][0]
                outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
                arn = outputs["RuntimeArn"]
                runtime = reads.client(
                    "bedrock-agentcore-control", config=READ_CONFIG
                ).get_agent_runtime(agentRuntimeId=arn.rsplit("/", 1)[1])
                bindings.append(
                    StreamRelease(
                        model_key=target.model_key,
                        runtime_arn=arn,
                        runtime_version=runtime["agentRuntimeVersion"],
                        configuration_sha256=hashlib.sha256(
                            json.dumps(
                                target.settings.model_dump(mode="json"), sort_keys=True
                            ).encode()
                        ).hexdigest(),
                        template_sha256=target.template_sha256,
                    )
                )
            releases = StreamingReleases(
                review_sha256=review.sha256, artifact_version_id=version, models=tuple(bindings)
            )
            for target in review.targets:
                record = next(
                    item for item in releases.models if item.model_key == target.model_key
                )
                verify_target(reads, review, releases, target, record)
            with args.output.open("x") as out:
                out.write(releases.model_dump_json(indent=2) + "\n")
            print("All actual streaming releases independently verified and bound.")
            return 0
        if not args.invoke_live or args.releases is None or args.approval is None:
            raise UiError(
                "Live execution needs --invoke-live plus actual releases and explicit approval."
            )
        releases = StreamingReleases.model_validate_json(args.releases.read_bytes())
        approval = json.loads(args.approval.read_bytes())

        def backend(key: str) -> StreamingQuestions:
            return StreamingQuestions(
                ROOT, review, releases, approval, key, args.canonical_dir, operator=True
            )

        if args.command == "ask":
            if args.output.exists():
                raise UiError("Use a new output path; retained evidence must not be replaced.")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            result = backend(args.model).ask_with_events(
                AskRequest(question=args.question, mode=args.mode, request_id=uuid4()),
                lambda event: print(json.dumps(event), flush=True),
            )
            with args.output.open("x") as out:
                out.write(result.model_dump_json(indent=2) + "\n")
            return 0 if result.response.status != "error" else 1
        args.output.mkdir(parents=True, exist_ok=False)
        cases = acceptance_cases(ROOT)
        # A partial or completed acceptance run cannot be silently repeated to
        # consume user-owned slots. Cleanup remains available separately.
        from datetime import UTC, datetime

        from enterprise_analytics_agent.ui.model_streams import verify_approval

        verify_approval(review, approval, now=datetime.now(UTC))
        releases.validate_review(review)
        ledger.directory.mkdir(parents=True, exist_ok=True)
        _write_json_new(
            ledger.directory / "acceptance-claim.json",
            {
                "review_sha256": review.sha256,
                "output": str(args.output.resolve()),
                "at": datetime.now(UTC).isoformat(),
            },
        )
        reports = []
        for target in review.targets:
            runner = backend(target.model_key)
            for index, (case, golden) in enumerate(cases):
                request = AskRequest(question=case.question, mode="live", request_id=uuid4())
                report: dict[str, object] = {
                    "model_key": target.model_key,
                    "case": "Q18" if index == 0 else "all-five-regionals",
                    "source_case_ids": ["Q18"]
                    if index == 0
                    else ["Q01", "Q02", "Q03", "Q04", "Q05"],
                    "request_id": str(request.request_id),
                }
                report_path = args.output / f"{target.model_key}-{index}.json"
                try:
                    result = runner.ask(request)
                    judged = judge_response(
                        case,
                        golden,
                        result.response,
                        target.settings,
                        elapsed_ms=result.elapsed_ms,
                        raw_response=result.response.model_dump(mode="json"),
                    )
                except BaseException as exc:
                    _write_json_new(
                        report_path,
                        {
                            **report,
                            "status": "failed",
                            "operation": "model_acceptance",
                            "error_type": type(exc).__name__,
                        },
                    )
                    raise
                report.update(
                    judgment=judged.model_dump(mode="json"), result=result.model_dump(mode="json")
                )
                reports.append(report)
                _write_json_new(report_path, report)
                if judged.status != "passed" or result.presentation_status != "streamed":
                    raise UiError(
                        "A model acceptance gate failed; "
                        "stop ordinary execution and retain evidence."
                    )
        accepted = {
            "review_sha256": review.sha256,
            "passed": True,
            "models": [target.model_key for target in review.targets],
            "reports": str(args.output),
            "questions": len(reports),
            "budget": ledger.summary(),
        }
        _write_json_new(ledger.directory / "accepted.json", accepted)
        print(json.dumps(accepted, indent=2))
        return 0
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "status": "interrupted",
                    "message": (
                        "Keep all evidence and follow the restoration procedure; do not resubmit."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": (
                        "Streaming operation failed; retain diagnostics "
                        "and do not retry billable work automatically."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
