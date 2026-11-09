"""Injected, counted operator invocation; imports and response replay are offline."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import uuid4

from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.retail_evaluation.campaign import (
    CampaignError,
    CampaignLedger,
    Purpose,
    RestorationProof,
)
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget


class ResponseBody(Protocol):
    def read(self) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class RuntimeReply:
    body: ResponseBody
    invocation_id: str | None = None


class RuntimeInvoker(Protocol):
    def __call__(self, *, payload: bytes, session_id: str) -> RuntimeReply: ...


@dataclass(frozen=True)
class InvocationResult:
    response: AgentResponse
    elapsed_ms: int | None
    invocation_id: str | None
    raw_response: dict[str, object]


class InvocationError(RuntimeError):
    """Sanitized error; full underlying exceptions remain available via __cause__."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_target_response(response: AgentResponse, target: RetailTarget) -> None:
    if response.dataset_version != target.dataset_version:
        raise ValueError("response dataset differs from the approved target")
    if response.diagnostics.model_id != target.model_id:
        raise ValueError("response model differs from the approved target")
    if (
        response.diagnostics.configuration.get("reference_date")
        != target.reference_date.isoformat()
    ):
        raise ValueError("response reference date differs from the approved target")
    if any(
        response.metric_versions.get(result.metric_id) != result.definition_version
        for result in response.results
    ):
        raise ValueError("response metric version evidence is incomplete or inconsistent")


class CountedAgentClient:
    def __init__(
        self,
        target: RetailTarget,
        ledger: CampaignLedger,
        invoke_runtime: RuntimeInvoker,
        *,
        purpose: Purpose = "case",
        clock: Callable[[], float] = time.monotonic,
        restoration_verifier: Callable[[], RestorationProof] | None = None,
    ) -> None:
        if purpose == "restoration_smoke" and target.dataset_version != "parity-v1":
            raise ValueError("restoration smoke requires the parity target")
        if purpose != "restoration_smoke" and target.dataset_version != "retail-v1":
            raise ValueError("retail invocation requires the retail target")
        if purpose == "restoration_smoke" and restoration_verifier is None:
            raise ValueError("restoration smoke requires a fresh state verifier")
        self.target = target
        self.ledger = ledger
        self.invoke_runtime = invoke_runtime
        self.purpose = purpose
        self.clock = clock
        self.restoration_verifier = restoration_verifier

    def invoke(self, question: str, *, session_id: str | None = None) -> InvocationResult:
        request = AgentRequest(question=question)
        session_id = session_id or str(uuid4())
        # These checks precede reservation because no invocation can yet have happened.
        if not 33 <= len(session_id) <= 256 or any(ord(char) < 33 for char in session_id):
            raise ValueError("session ID must contain 33-256 printable non-space characters")
        proof = self.restoration_verifier() if self.restoration_verifier else None
        reservation = self.ledger.reserve(
            purpose=self.purpose,
            question=request.question,
            session_id=session_id,
            runtime_arn=self.target.runtime_arn,
            restoration_proof=proof,
        )
        started = self.clock()
        invocation_id: str | None = None
        stage = "sdk_error"
        try:
            reply = self.invoke_runtime(
                payload=request.model_dump_json().encode(), session_id=session_id
            )
            invocation_id = reply.invocation_id
            stage = "body_error"
            try:
                payload = reply.body.read()
            finally:
                reply.body.close()
            stage = "response_validation_error"
            decoded = json.loads(payload)
            if not isinstance(decoded, dict):
                raise ValueError("agent response must be a JSON object")
            response = AgentResponse.model_validate(decoded)
            validate_target_response(response, self.target)
            raw_response = cast(dict[str, object], decoded)
        except BaseException as exc:
            if isinstance(exc, TimeoutError):
                stage = "body_timeout" if stage == "body_error" else "sdk_timeout"
            elapsed = max(0, int((self.clock() - started) * 1000))
            # A logging failure must not obscure the dispatch/body/validation error.
            # Its existing durable reservation already accounts for this call.
            try:
                self.ledger.finish(
                    reservation,
                    outcome="failed",
                    elapsed_ms=elapsed,
                    invocation_id=invocation_id,
                    error_code=stage,
                )
            except (OSError, CampaignError):
                pass
            if not isinstance(exc, Exception):
                raise
            raise InvocationError(stage) from exc
        elapsed = max(0, int((self.clock() - started) * 1000))
        self.ledger.finish(
            reservation,
            outcome=response.status,
            elapsed_ms=elapsed,
            invocation_id=invocation_id,
        )
        return InvocationResult(response, elapsed, invocation_id, raw_response)
