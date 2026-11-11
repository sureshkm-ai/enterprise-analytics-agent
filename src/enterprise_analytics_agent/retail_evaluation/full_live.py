"""Separate, review-bound accounting for a future complete live verification run.

Importing this module or inspecting an unused budget creates no files or clients.
The review records a proposed scope; it is not execution approval. The operator
must establish approval, identity and exact deployment proofs before installing
the SDK guard. Historical milestone/UI ledgers are never opened here.
"""

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal, TextIO
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.ui.live import UiLedgerFiles

type FullLivePhase = Literal["athena_parity", "agent_parity", "retail", "restoration_smoke"]
type Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

RUNTIME_ARN: Final = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:"
    "runtime/enterprise_analytics_dev_agent-HlWywlG60h"
)
_PHASE_LIMITS = {"athena_parity": 201, "agent_parity": 19, "retail": 36, "restoration_smoke": 1}


class FullLiveReview(BaseModel):
    """Exact operator scope, with no model-supplied identity or arbitrary target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["full-live-review-v1"] = "full-live-review-v1"
    campaign_id: Literal["full-live-v1"] = "full-live-v1"
    profile: Literal["analytics-dev"] = "analytics-dev"
    account: Literal["453711491609"] = "453711491609"
    region: Literal["us-west-2"] = "us-west-2"
    runtime_arn: Literal[
        "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/enterprise_analytics_dev_agent-HlWywlG60h"
    ] = RUNTIME_ARN
    qualifier: Literal["DEFAULT"] = "DEFAULT"
    model_id: Literal["us.amazon.nova-lite-v1:0"] = "us.amazon.nova-lite-v1:0"
    starting_runtime_version: Literal["13"] = "13"
    source_sha256: Literal["aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be"] = (
        "aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be"
    )
    archive_sha256: Literal["398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1"] = (
        "398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1"
    )
    artifact_version_id: Literal["V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu"] = (
        "V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu"
    )
    retail_template_sha256: Literal[
        "faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368"
    ] = "faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368"
    parity_template_sha256: Sha256
    aws_config_sha256: Literal[
        "3297efb9f47e3b5eab48bd0da0675d1f05002900482a44e56832e215eeaef91a"
    ] = "3297efb9f47e3b5eab48bd0da0675d1f05002900482a44e56832e215eeaef91a"
    maximum_runtime_invocations: Literal[56] = 56
    agent_parity_invocations: Literal[19] = 19
    retail_invocations: Literal[36] = 36
    protected_restoration_invocations: Literal[1] = 1
    maximum_direct_athena_submissions: Literal[201] = 201
    workgroup_name: Literal["enterprise-analytics-dev"] = "enterprise-analytics-dev"
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review expiry requires a timezone")
        return value.astimezone(UTC)

    @field_validator("parity_template_sha256")
    @classmethod
    def reviewed_parity_hash(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("parity assembly hash is pending; execution is not ready")
        return value

    @property
    def maximum_calls(self) -> int:
        return self.maximum_runtime_invocations + self.maximum_direct_athena_submissions

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()


class FullLiveBudgetError(RuntimeError):
    """A count, target, expiry or retained-evidence invariant prevents dispatch."""


class FullLiveBudget(UiLedgerFiles):
    """One separate SDK ledger; a restoration slot survives ordinary failure.

    SDK request acceptance is recorded as ``sdk_returned``, not test success.
    Structured-result/pytest judgments remain a separate acceptance gate.
    """

    def __init__(
        self,
        review: FullLiveReview,
        *,
        repository_root: Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        # Pydantic model_copy(update=...) deliberately skips validation. Treat an
        # already-instantiated review as input too, before selecting its paths.
        review = FullLiveReview.model_validate(review.model_dump())
        super().__init__(repository_root, review, now=now)
        self.directory = self.root / "artifacts/full-live" / review.campaign_id
        self.path = self.directory / "sdk-attempts.jsonl"
        self.claims = self.directory / "reservations"
        self.sdk_claim = self.directory.with_suffix(".sdk-claim.json")
        self.review: FullLiveReview = review
        self._check_paths()

    def _check_paths(self) -> None:
        super()._check_paths()
        claim = getattr(self, "sdk_claim", None)
        if claim is not None and claim.resolve() != claim:
            raise FullLiveBudgetError("The full-suite SDK claim is aliased; do not reset it")

    def _claim_value(self) -> dict[str, str]:
        return {
            "schema_version": "full-live-sdk-claim-v1",
            "campaign_id": self.review.campaign_id,
            "review_sha256": self.review.sha256,
        }

    def _validate_claim(self, *, required: bool) -> None:
        self._check_paths()
        if not self.sdk_claim.exists():
            if required:
                raise FullLiveBudgetError("Full-suite SDK claim is missing; do not reset it")
            return
        try:
            if json.loads(self.sdk_claim.read_bytes()) != self._claim_value():
                raise ValueError("review differs")
        except (ValueError, OSError) as exc:
            raise FullLiveBudgetError("Full-suite SDK claim differs from its review") from exc

    def _ensure_claim(self) -> None:
        if self.sdk_claim.exists():
            self._validate_claim(required=True)
            return
        descriptor = os.open(
            self.sdk_claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(self._claim_value(), sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(self.sdk_claim.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read(self, stream: TextIO) -> list[dict[str, Any]]:
        stream.seek(0)
        rows: list[dict[str, Any]] = []
        reserved: dict[str, dict[str, Any]] = {}
        outcomes: set[str] = set()
        counts = dict.fromkeys(_PHASE_LIMITS, 0)
        failed = restored = stopped = False
        try:
            for line in stream:
                row = json.loads(line)
                if (
                    not line.endswith("\n")
                    or not isinstance(row, dict)
                    or row.get("review_sha256") != self.review.sha256
                ):
                    raise ValueError("truncated/changed review")
                if row["event"] == "stopped":
                    if not isinstance(row.get("reason"), str) or not row["reason"]:
                        raise ValueError("invalid stop diagnostic")
                    stopped = True
                elif row["event"] == "reserved":
                    phase, identifier = row["phase"], row["request_id"]
                    if phase not in _PHASE_LIMITS or identifier in reserved or restored:
                        raise ValueError("invalid/duplicate reservation")
                    if type(row["number"]) is not int or row["number"] != len(reserved) + 1:
                        raise ValueError("invalid reservation sequence")
                    if (failed or stopped or len(reserved) != len(outcomes)) and (
                        phase != "restoration_smoke"
                    ):
                        raise ValueError("ordinary dispatch after failure/unknown outcome")
                    service, operation = row["service"], row["operation"]
                    wanted = (
                        ("athena", "StartQueryExecution")
                        if phase == "athena_parity"
                        else ("bedrock-agentcore", "InvokeAgentRuntime")
                    )
                    if (service, operation) != wanted:
                        raise ValueError("phase/service differs")
                    if not isinstance(row.get("parameters_sha256"), str):
                        raise ValueError("missing request fingerprint")
                    counts[phase] += 1
                    if counts[phase] > _PHASE_LIMITS[phase]:
                        raise ValueError("reviewed phase budget exceeded")
                    reserved[identifier] = row
                    restored = phase == "restoration_smoke"
                elif row["event"] == "outcome":
                    identifier = row["request_id"]
                    if identifier not in reserved or identifier in outcomes:
                        raise ValueError("invalid/duplicate outcome")
                    if row["status"] not in {"sdk_returned", "sdk_failed"}:
                        raise ValueError("invalid SDK outcome")
                    retryable = row.get("retryable", False)
                    if type(retryable) is not bool or (
                        retryable
                        and (
                            reserved[identifier]["phase"] != "athena_parity"
                            or row["status"] != "sdk_failed"
                        )
                    ):
                        raise ValueError("retry permission differs from the reviewed operation")
                    outcomes.add(identifier)
                    failed = failed or (row["status"] == "sdk_failed" and not retryable)
                else:
                    raise ValueError("unknown event")
                rows.append(row)
            expected = {f"{row['number']}.json": row for row in reserved.values()}
            actual = list(self.claims.iterdir()) if self.claims.exists() else []
            if {path.name for path in actual} != set(expected):
                raise ValueError("receipt inventory differs")
            if any(
                path.resolve() != path or json.loads(path.read_bytes()) != expected[path.name]
                for path in actual
            ):
                raise ValueError("receipt differs")
            self._validate_claim(required=bool(rows))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise FullLiveBudgetError(
                "Full-suite SDK ledger/receipts are invalid; preserve them, never reset"
            ) from exc
        return rows

    def _summary(self, rows: list[dict[str, Any]]) -> dict[str, object]:
        reservations = [row for row in rows if row["event"] == "reserved"]
        outcomes = [row for row in rows if row["event"] == "outcome"]
        phases = {
            phase: sum(row["phase"] == phase for row in reservations) for phase in _PHASE_LIMITS
        }
        runtime = sum(value for phase, value in phases.items() if phase != "athena_parity")
        incomplete = len(reservations) != len(outcomes)
        failures = [row for row in outcomes if row["status"] == "sdk_failed"]
        failed = any(not row.get("retryable", False) for row in failures)
        stopped = any(row["event"] == "stopped" for row in rows)
        expired = self.now() >= self.review.expires_at
        return {
            "campaign_id": self.review.campaign_id,
            "review_sha256": self.review.sha256,
            "runtime_used": runtime,
            "runtime_maximum": self.review.maximum_runtime_invocations,
            "runtime_remaining": self.review.maximum_runtime_invocations - runtime,
            "direct_athena_submissions": phases["athena_parity"],
            "direct_athena_maximum": self.review.maximum_direct_athena_submissions,
            "phases": phases,
            "phase_remaining": {key: _PHASE_LIMITS[key] - value for key, value in phases.items()},
            "incomplete": incomplete,
            "failed": failed,
            "failed_sdk_attempts": len(failures),
            "retryable_athena_failures": sum(bool(row.get("retryable")) for row in failures),
            "incomplete_sdk_attempts": len(reservations) - len(outcomes),
            "stopped": stopped,
            "expired": expired,
            "restoration_started": bool(phases["restoration_smoke"]),
            "ordinary_blocked": incomplete
            or failed
            or stopped
            or expired
            or bool(phases["restoration_smoke"]),
        }

    def summary(self) -> dict[str, object]:
        self._check_paths()
        if not self.path.exists():
            if self.sdk_claim.exists() or (self.claims.exists() and any(self.claims.iterdir())):
                raise FullLiveBudgetError("SDK ledger missing but durable claim/receipts remain")
            return self._summary([])
        with self._open(create=False) as stream:
            return self._summary(self._read(stream))

    def stop(self, reason: str) -> None:
        """Retain an operator/test failure without refunding already attempted SDK work."""
        if not reason or not re_safe_reason(reason):
            raise ValueError("Use a nonsecret diagnostic code, not a raw exception or payload")
        with self._open(create=True) as stream:
            self._read(stream)
            self._ensure_claim()
            self._append(stream, {"event": "stopped", "reason": reason})

    def call(
        self,
        phase: FullLivePhase,
        service: str,
        operation: str,
        parameters: dict[str, Any],
        dispatch: Callable[[], Any],
        *,
        retryable_failure: Callable[[BaseException], bool] | None = None,
        failure_detail: Callable[[BaseException], dict[str, object]] | None = None,
    ) -> Any:
        """Count one SDK dispatch; no retries and no inference of semantic success."""
        self._validate_target(phase, service, operation, parameters)
        if self.now() >= self.review.expires_at:
            raise FullLiveBudgetError("The approved full-suite window expired before dispatch")
        with self._open(create=True) as stream:
            rows = self._read(stream)
            summary = self._summary(rows)
            if summary["expired"] or summary["restoration_started"]:
                raise FullLiveBudgetError("The approved full-suite window/phase is closed")
            if phase != "restoration_smoke" and summary["ordinary_blocked"]:
                raise FullLiveBudgetError("Ordinary full-suite dispatch is blocked")
            remaining = summary["phase_remaining"]
            assert isinstance(remaining, dict)
            if remaining[phase] <= 0:
                raise FullLiveBudgetError("The reviewed phase allowance is exhausted")
            reservations = [row for row in rows if row["event"] == "reserved"]
            identifier = str(uuid4())
            self._ensure_claim()
            # Only a digest is retained: question text and query parameters can be sensitive.
            fingerprint = hashlib.sha256(
                json.dumps(parameters, sort_keys=True, default=str).encode()
            ).hexdigest()
            self._append(
                stream,
                {
                    "event": "reserved",
                    "request_id": identifier,
                    "number": len(reservations) + 1,
                    "phase": phase,
                    "service": service,
                    "operation": operation,
                    "parameters_sha256": fingerprint,
                },
            )
            try:
                response = dispatch()
            except BaseException as exc:
                try:
                    retryable = (
                        phase == "athena_parity"
                        and retryable_failure is not None
                        and retryable_failure(exc)
                    )
                    self._append(
                        stream,
                        {
                            "event": "outcome",
                            "request_id": identifier,
                            "status": "sdk_failed",
                            "error_type": type(exc).__name__,
                            "retryable": retryable,
                            "diagnostic": failure_detail(exc) if failure_detail else {},
                        },
                    )
                except BaseException:
                    pass  # Existing durable reservation remains spent/unknown.
                raise
            self._append(
                stream,
                {"event": "outcome", "request_id": identifier, "status": "sdk_returned"},
            )
            return response

    def _validate_target(
        self, phase: FullLivePhase, service: str, operation: str, parameters: dict[str, Any]
    ) -> None:
        if phase not in _PHASE_LIMITS:
            raise FullLiveBudgetError("Unknown full-suite phase")
        if phase == "athena_parity":
            if (service, operation) != ("athena", "StartQueryExecution") or parameters.get(
                "WorkGroup"
            ) != self.review.workgroup_name:
                raise FullLiveBudgetError("Direct query is outside the reviewed workgroup/phase")
        elif (
            (service, operation) != ("bedrock-agentcore", "InvokeAgentRuntime")
            or parameters.get("agentRuntimeArn") != self.review.runtime_arn
            or parameters.get("qualifier") != self.review.qualifier
        ):
            raise FullLiveBudgetError("Runtime invocation is outside the reviewed target/phase")
        else:
            try:
                AgentRequest.model_validate_json(parameters["payload"])
                session_id = parameters["runtimeSessionId"]
                if (
                    not isinstance(session_id, str)
                    or not 33 <= len(session_id) <= 256
                    or any(ord(char) < 33 for char in session_id)
                ):
                    raise ValueError("invalid session identifier")
            except (ValueError, TypeError, KeyError) as exc:
                raise FullLiveBudgetError(
                    "Runtime payload/session is outside the semantic request"
                ) from exc

    @contextmanager
    def counted_sdk(self, phase: FullLivePhase) -> Iterator[None]:
        """Delegate AWS-specific SDK guarding to the adapter without creating clients."""
        from enterprise_analytics_agent.adapters.full_live_sdk import counted_full_live_sdk

        with counted_full_live_sdk(self, phase):
            yield


def re_safe_reason(value: str) -> bool:
    """Keep stop diagnostics to small authored codes instead of signed SDK detail."""
    return len(value) <= 80 and all(
        char.isascii() and (char.isalnum() or char in "_-") for char in value
    )
