"""One explicitly reviewed allowance for local Bedrock and AgentCore questions.

No AWS client is created here. The ledger is deliberately separate from all
historical campaigns, and question modes never supply authorization context.
"""

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self, TextIO

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.adapters.bedrock_agent import BedrockAgentConfig, ConverseClient
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.ui.live import UiLedgerFiles
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult

CANDIDATE_SHA256: Final = "398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1"
CANDIDATE_VERSION: Final = "V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu"
CANDIDATE_TEMPLATE: Final = "faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368"
CANONICAL_MANIFEST: Final = "99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797"
RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:"
    "runtime/enterprise_analytics_dev_agent-HlWywlG60h"
)
type SharedPurpose = Literal["question", "verification", "rollback_smoke"]


class SharedReview(BaseModel):
    """Immutable proposed release and budget, never accepted from browser payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ui-shared-live-v1"] = "ui-shared-live-v1"
    campaign_id: Annotated[str, Field(pattern=r"^ui-shared-[a-z0-9-]{1,48}$")]
    maximum_calls: Annotated[int, Field(strict=True, ge=2, le=20)] = 20
    expires_at: datetime
    target: RetailTarget
    tenant_id: Literal["retail_demo"] = "retail_demo"
    allowed_regions: tuple[Literal["North"], Literal["South"]] = ("North", "South")
    agent_config: BedrockAgentConfig = Field(
        default_factory=lambda: BedrockAgentConfig(
            model_id="us.amazon.nova-lite-v1:0", reference_date=date(2025, 4, 1)
        )
    )
    archive_sha256: Literal["398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1"] = (
        CANDIDATE_SHA256
    )
    artifact_version_id: Literal["V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu"] = CANDIDATE_VERSION
    runtime_template_sha256: Literal[
        "faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368"
    ] = CANDIDATE_TEMPLATE
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    canonical_manifest_sha256: Literal[
        "99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797"
    ] = CANONICAL_MANIFEST

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("shared review expiry must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def reviewed_scope(self) -> Self:
        if (
            self.target.runtime_arn != RUNTIME_ARN
            or self.target.dataset_version != "retail-v1"
            or self.target.reference_date.isoformat() != "2025-04-01"
        ):
            raise ValueError("shared review requires the exact reviewed retail Runtime target")
        if self.agent_config.model_dump(mode="json") != {
            "model_id": "us.amazon.nova-lite-v1:0",
            "reference_date": "2025-04-01",
            "max_iterations": 6,
            "max_tool_calls": 16,
            "max_output_tokens": 1024,
            "max_total_tokens": 12000,
            "timeout_seconds": 90.0,
        }:
            raise ValueError("shared review must preserve the accepted agent configuration")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()


class SdkAttemptRecorder:
    """Durably count actual SDK attempts before dispatch, without wrapping retries."""

    def __init__(
        self,
        ledger: "SharedLedger",
        reservation: dict[str, Any],
    ) -> None:
        self.ledger, self.reservation = ledger, reservation
        self.converse_calls = self.runtime_calls = 0
        self.failed = False
        self.closed = False

    def _event(self, event: str, service: str, operation: str, number: int, **extra: Any) -> None:
        if self.closed:
            raise UiError("This question's SDK recorder is closed; no call was sent.")
        record = {
            "at": self.ledger.now().isoformat(),
            "review_sha256": self.ledger.review.sha256,
            "request_id": self.reservation["request_id"],
            "question_number": self.reservation["number"],
            "mode": self.reservation["mode"],
            "purpose": self.reservation["purpose"],
            "event": event,
            "service": service,
            "operation": operation,
            "sdk_number": number,
            **extra,
        }
        self.ledger._check_paths()
        # The question lock is already held by execute(). Re-read without taking
        # a second lock so integrity loss cannot silently restart SDK accounting.
        with self.ledger.path.open() as question_stream:
            self.ledger._read(question_stream)
        encoded = json.dumps(record, sort_keys=True) + "\n"
        if event == "reserved":
            self.ledger.sdk_claims.mkdir(exist_ok=True)
            receipt = self.ledger.sdk_claims / f"{self.reservation['number']}-{number}.json"
            descriptor = os.open(
                receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            for directory in (self.ledger.sdk_claims, self.ledger.directory):
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        descriptor = os.open(
            self.ledger.sdk_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(descriptor, "a") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(self.ledger.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def converse(self, client: ConverseClient) -> ConverseClient:
        recorder = self

        class CountedConverse:
            def converse(self, **kwargs: object) -> dict[str, object]:
                if recorder.reservation["mode"] != "local_agent":
                    raise UiError("Direct Converse is not permitted in this question mode.")
                if recorder.failed:
                    raise UiError("A failed SDK attempt cannot be retried in this question.")
                if recorder.converse_calls >= 6:
                    raise UiError("The six-model-call ceiling was reached; no call was sent.")
                if recorder.ledger.now() >= recorder.ledger.review.expires_at:
                    raise UiError("The reviewed expiry was reached; no model call was sent.")
                recorder.converse_calls += 1
                count = recorder.converse_calls
                recorder._event("reserved", "bedrock-runtime", "Converse", count)
                try:
                    response = client.converse(**kwargs)
                except BaseException as exc:
                    recorder.failed = True
                    recorder._event(
                        "failed",
                        "bedrock-runtime",
                        "Converse",
                        count,
                        error_type=type(exc).__name__,
                    )
                    raise
                recorder._event("returned", "bedrock-runtime", "Converse", count)
                return response

        return CountedConverse()

    def invoke_runtime(self, invoke: Callable[..., Any], **kwargs: Any) -> Any:
        if self.reservation["mode"] != "live" or self.runtime_calls or self.failed:
            raise UiError("Only one AgentCore invocation is allowed for this question attempt.")
        if self.ledger.now() >= self.ledger.review.expires_at:
            raise UiError("The reviewed expiry was reached; no Runtime invocation was sent.")
        self.runtime_calls += 1
        self._event("reserved", "bedrock-agentcore", "InvokeAgentRuntime", 1)
        try:
            response = invoke(**kwargs)
        except BaseException as exc:
            self.failed = True
            self._event(
                "failed",
                "bedrock-agentcore",
                "InvokeAgentRuntime",
                1,
                error_type=type(exc).__name__,
            )
            raise
        self._event("returned", "bedrock-agentcore", "InvokeAgentRuntime", 1)
        return response


class SharedLedger(UiLedgerFiles):
    """Shared question quota with distinct verification and rollback reservations."""

    def __init__(
        self, root: Path, review: SharedReview, *, now: Callable[[], datetime] | None = None
    ) -> None:
        super().__init__(root, review, now=now)
        self.directory = self.root / "artifacts/ui-shared" / review.campaign_id
        self.path = self.directory / "question-attempts.jsonl"
        self.claims = self.directory / "reservations"
        self.sdk_path = self.directory / "sdk-attempts.jsonl"
        self.sdk_claims = self.directory / "sdk-reservations"
        self._check_paths()

    def _check_paths(self) -> None:
        super()._check_paths()
        for name in ("sdk_path", "sdk_claims"):
            path = getattr(self, name, None)
            if path is not None and path.resolve() != path:
                raise UiError(
                    "The shared SDK evidence path is aliased; preserve it for inspection."
                )

    def _read(self, stream: TextIO) -> list[dict[str, Any]]:
        stream.seek(0)
        rows: list[dict[str, Any]] = []
        reservations: dict[str, dict[str, Any]] = {}
        pending: set[str] = set()
        outcomes: set[str] = set()
        purposes = {"question": 0, "verification": 0, "rollback_smoke": 0}
        failed = rollback = False
        try:
            for line in stream:
                row = json.loads(line)
                if not line.endswith("\n") or not isinstance(row, dict):
                    raise ValueError("truncated row")
                if row.get("review_sha256") != self.review.sha256:
                    raise ValueError("changed review")
                identifier = row["request_id"]
                if not isinstance(identifier, str):
                    raise ValueError("invalid request identifier")
                if row["event"] == "reserved":
                    purpose = row["purpose"]
                    if purpose not in purposes or identifier in reservations or rollback:
                        raise ValueError("duplicate/invalid reservation")
                    if row["mode"] not in {"local_agent", "live"}:
                        raise ValueError("invalid question mode")
                    if purpose != "question" and row["mode"] != "live":
                        raise ValueError("smoke must invoke the reviewed Runtime")
                    if (pending or failed) and purpose != "rollback_smoke":
                        raise ValueError("attempt appended after failure/unknown outcome")
                    purposes[purpose] += 1
                    if purposes["question"] > self.review.maximum_calls - 2:
                        raise ValueError("protected question slots consumed")
                    if purposes["verification"] > 1 or purposes["rollback_smoke"] > 1:
                        raise ValueError("protected slot repeated")
                    if type(row["number"]) is not int or row["number"] != len(reservations) + 1:
                        raise ValueError("invalid question number")
                    if row["number"] > self.review.maximum_calls:
                        raise ValueError("reviewed cap exceeded")
                    reservations[identifier] = row
                    pending.add(identifier)
                    rollback = purpose == "rollback_smoke"
                elif row["event"] == "outcome" and identifier in pending:
                    if identifier in outcomes or row["status"] not in {
                        "answer",
                        "clarification",
                        "error",
                        "failed",
                    }:
                        raise ValueError("invalid outcome")
                    if row["status"] != "failed":
                        result = UiResult.model_validate(row["result"])
                        if result.mode != reservations[identifier]["mode"]:
                            raise ValueError("outcome mode changed")
                    outcomes.add(identifier)
                    pending.remove(identifier)
                    failed = failed or row["status"] in {"error", "failed"}
                else:
                    raise ValueError("invalid event order")
                rows.append(row)
            expected = {f"{row['number']}.json": row for row in reservations.values()}
            actual = list(self.claims.iterdir()) if self.claims.exists() else []
            if {path.name for path in actual} != set(expected):
                raise ValueError("receipt inventory differs")
            if any(
                path.resolve() != path or json.loads(path.read_text()) != expected[path.name]
                for path in actual
            ):
                raise ValueError("receipt changed")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise UiError("Shared UI ledger/receipts are invalid. Do not reset them.") from exc
        self._sdk_summary(rows)
        return rows

    def _sdk_summary(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "local_converse_attempts": 0,
            "agentcore_invocations": 0,
            "failed_sdk_attempts": 0,
            "incomplete_sdk_attempts": 0,
        }
        reservations = {row["request_id"]: row for row in rows if row["event"] == "reserved"}
        if not self.sdk_path.exists():
            self._verify_sdk_receipts({})
            return counts
        expected_receipts: dict[str, dict[str, Any]] = {}
        pending: set[tuple[str, int]] = set()
        per_question: dict[str, int] = {}
        failed: set[str] = set()
        try:
            for line in self.sdk_path.read_text().splitlines(keepends=True):
                event = json.loads(line)
                if (
                    not line.endswith("\n")
                    or not isinstance(event, dict)
                    or event.get("review_sha256") != self.review.sha256
                ):
                    raise ValueError("truncated/changed SDK journal")
                identifier = event["request_id"]
                question = reservations[identifier]
                mode = question["mode"]
                expected = (
                    ("bedrock-runtime", "Converse")
                    if mode == "local_agent"
                    else ("bedrock-agentcore", "InvokeAgentRuntime")
                )
                if (
                    event["mode"] != mode
                    or event["purpose"] != question["purpose"]
                    or event["question_number"] != question["number"]
                    or (event["service"], event["operation"]) != expected
                ):
                    raise ValueError("SDK journal question/operation differs")
                number = event["sdk_number"]
                key = (identifier, number)
                if event["event"] == "reserved":
                    wanted = per_question.get(identifier, 0) + 1
                    if (
                        type(number) is not int
                        or number != wanted
                        or identifier in failed
                        or any(item[0] == identifier for item in pending)
                        or number > (6 if mode == "local_agent" else 1)
                    ):
                        raise ValueError("SDK attempt count/order differs")
                    per_question[identifier] = number
                    expected_receipts[f"{question['number']}-{number}.json"] = event
                    pending.add(key)
                    counts[
                        "local_converse_attempts"
                        if mode == "local_agent"
                        else "agentcore_invocations"
                    ] += 1
                elif event["event"] in {"returned", "failed"} and key in pending:
                    pending.remove(key)
                    if event["event"] == "failed":
                        failed.add(identifier)
                        counts["failed_sdk_attempts"] += 1
                else:
                    raise ValueError("SDK outcome order differs")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise UiError(
                "Shared SDK attempt journal is invalid; preserve it for inspection."
            ) from exc
        self._verify_sdk_receipts(expected_receipts)
        completed = {
            row["request_id"]
            for row in rows
            if row["event"] == "outcome" and row["status"] in {"answer", "clarification"}
        }
        if any(identifier in completed for identifier, _ in pending):
            raise UiError("A completed question has incomplete SDK evidence; preserve it.")
        counts["incomplete_sdk_attempts"] = len(pending)
        return counts

    def _verify_sdk_receipts(self, expected: dict[str, dict[str, Any]]) -> None:
        try:
            actual = list(self.sdk_claims.iterdir()) if self.sdk_claims.exists() else []
            if {path.name for path in actual} != set(expected):
                raise ValueError("SDK reservation inventory differs from its journal")
            if any(
                path.resolve() != path
                or path.read_text() != json.dumps(expected[path.name], sort_keys=True) + "\n"
                for path in actual
            ):
                raise ValueError("SDK reservation differs from its journal")
        except (ValueError, OSError) as exc:
            raise UiError(
                "Shared SDK reservation evidence disagrees with its journal. Do not reset it."
            ) from exc

    def _summary(self, rows: list[dict[str, Any]]) -> dict[str, object]:
        result = super()._summary(rows)
        reserved = [row for row in rows if row["event"] == "reserved"]
        by_purpose = {
            purpose: sum(row["purpose"] == purpose for row in reserved)
            for purpose in ("question", "verification", "rollback_smoke")
        }
        result.update(
            regular_remaining=self.review.maximum_calls - 2 - by_purpose["question"],
            verification_remaining=1 - by_purpose["verification"],
            rollback_remaining=1 - by_purpose["rollback_smoke"],
            purposes=by_purpose,
            sdk_attempts=self._sdk_summary(rows),
            modes={
                mode: sum(row["mode"] == mode for row in reserved)
                for mode in ("local_agent", "live")
            },
        )
        result["blocked"] = bool(
            result["blocked"]
            or by_purpose["question"] >= self.review.maximum_calls - 2
            or by_purpose["rollback_smoke"]
        )
        return result

    def execute(
        self,
        request: AskRequest,
        prepare: Callable[[], Callable[[SdkAttemptRecorder], UiResult]],
        *,
        purpose: SharedPurpose = "question",
    ) -> UiResult:
        if request.mode not in {"local_agent", "live"}:
            raise UiError("Shared allowance is only for explicitly enabled agent modes.")
        if purpose != "question" and request.mode != "live":
            raise UiError("Verification and rollback smoke require the Runtime mode.")
        if purpose not in {"question", "verification", "rollback_smoke"}:
            raise UiError("Unknown trusted question purpose.")
        request_id = str(request.request_id)
        question_hash = hashlib.sha256(
            json.dumps([request.mode, purpose, request.question]).encode()
        ).hexdigest()
        with self._open(create=True) as stream:
            rows = self._read(stream)
            previous = next((row for row in rows if row["request_id"] == request_id), None)
            if previous is not None:
                if previous["question_sha256"] != question_hash:
                    raise UiError(
                        "This request ID belongs to a different mode, purpose or question."
                    )
                outcome = next(
                    (
                        row
                        for row in rows
                        if row["request_id"] == request_id and row["event"] == "outcome"
                    ),
                    None,
                )
                if outcome is not None and outcome["status"] in {"answer", "clarification"}:
                    return UiResult.model_validate(outcome["result"])
                raise UiError("This attempt already exists and cannot be repeated.")
            summary = self._summary(rows)
            purposes = summary["purposes"]
            assert isinstance(purposes, dict)
            unavailable = bool(
                summary["expired"]
                or sum(row["event"] == "reserved" for row in rows) >= self.review.maximum_calls
                or purposes["rollback_smoke"]
            )
            if purpose == "question":
                unavailable = unavailable or bool(summary["blocked"])
            elif purpose == "verification":
                unavailable = unavailable or bool(
                    summary["failed"] or summary["incomplete"] or purposes["verification"]
                )
            else:
                unavailable = unavailable or bool(purposes["rollback_smoke"])
            if unavailable:
                raise UiError(
                    "The shared allowance/slot is expired, exhausted or blocked. Do not reset it."
                )
            dispatch = prepare()
            if self.now() >= self.review.expires_at:
                raise UiError(
                    "The shared allowance expired during preflight; no invocation was sent."
                )
            reservation = {
                "event": "reserved",
                "request_id": request_id,
                "number": sum(row["event"] == "reserved" for row in rows) + 1,
                "question_sha256": question_hash,
                "mode": request.mode,
                "purpose": purpose,
            }
            self._append(stream, reservation)
            recorder = SdkAttemptRecorder(self, reservation)
            try:
                result = dispatch(recorder)
                if result.mode != request.mode:
                    raise UiError("Shared runner returned the wrong question mode.")
            except BaseException:
                recorder.closed = True
                self._append(
                    stream, {"event": "outcome", "request_id": request_id, "status": "failed"}
                )
                raise
            recorder.closed = True
            self._append(
                stream,
                {
                    "event": "outcome",
                    "request_id": request_id,
                    "status": result.response.status,
                    "result": result.model_dump(mode="json"),
                },
            )
            return result
