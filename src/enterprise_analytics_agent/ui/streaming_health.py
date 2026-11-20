"""Read-only request diagnosis. A failed question is not model availability evidence."""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from enterprise_analytics_agent.adapters.bedrock_agent import _render
from enterprise_analytics_agent.ui.models import UiResult

# No retry is performed. Wait beyond the hosted 90s agent + 180s response window
# before allowing a new manual question after an uncertain transport outcome.
TRANSPORT_SETTLE_SECONDS = 300
TRANSPORT_ERRORS = frozenset(
    {"ReadTimeoutError", "ConnectTimeoutError", "EndpointConnectionError", "ConnectionClosedError"}
)
TEMPORARY_AWS_ERRORS = frozenset(
    {"ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException"}
)
QUESTION_LIMITS = frozenset({"iteration_limit", "token_limit", "deadline_exceeded"})


def acceptance_failure_message(root: Path, review_sha256: str, model_key: str) -> tuple[str, str]:
    """Explain retained acceptance evidence without implying a fresh AWS availability check."""
    path = root / "evaluations/bedrock-streaming/workbench.model-diagnostics.json"
    generic = ("Acceptance failed", "This model did not pass its deployed acceptance checks.")
    try:
        if path.resolve() != path:
            return generic
        report = json.loads(path.read_bytes())
        if not isinstance(report, dict) or report.get("review_sha256") != review_sha256:
            return generic
        models = report.get("models", [])
        if not isinstance(models, list):
            return generic
        for model in models:
            if not isinstance(model, dict) or model.get("model_key") != model_key:
                continue
            error = model.get("service_error", {})
            if (
                isinstance(error, dict)
                and error.get("code") == "AccessDeniedException"
                and "is not available for this account" in str(error.get("message", ""))
            ):
                return (
                    "Account access unavailable",
                    "AWS reported that this model is unavailable for this account "
                    "during acceptance. "
                    "The recorded error does not establish a missing IAM permission.",
                )
        return generic
    except (ValueError, OSError):
        return generic


def accepted_model(directory: Path, review_sha256: str, model_key: str) -> bool:
    path = directory / "acceptance" / f"{model_key}.json"
    try:
        if path.resolve() != path or not path.is_file():
            return False
        value = json.loads(path.read_bytes())
        return bool(
            isinstance(value, dict)
            and value.get("review_sha256") == review_sha256
            and value.get("model_key") == model_key
            and value.get("passed") is True
            and value.get("cases") == ["Q18", "all-five-regionals"]
        )
    except (ValueError, OSError):
        return False


def request_failures(
    directory: Path,
    rows: list[dict[str, Any]],
    model_ids: dict[str, str],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Classify only complete, recorded failures; unknown/correctness failures stay paused.

    Callers validate the journal and SDK receipts first. Old rows are read as-is;
    no result, outcome, reservation, acceptance or historical claim is rewritten.
    """
    failures = []
    for reservation in rows:
        if reservation["event"] != "reserved" or reservation["purpose"] != "question":
            continue
        identifier, key = reservation["request_id"], reservation["model_key"]
        events = [row for row in rows if row["request_id"] == identifier]
        failed = [row for row in events if row["event"] == "sdk_failed"]
        if not any(
            row["event"] in {"sdk_failed", "failure"} or row.get("status") == "failed"
            for row in events
        ):
            continue
        detail: dict[str, Any] = {
            "request_id": identifier,
            "model_key": key,
            "mode": reservation["mode"],
            "at": reservation["at"],
            "kind": "needs_inspection",
            "recoverable": False,
            "wait_seconds": 0,
            "sdk_errors": [
                {
                    name: row[name]
                    for name in ("operation", "error_type", "error_code")
                    if name in row
                }
                for row in failed
            ],
        }
        complete = any(row["event"] == "outcome" for row in events)
        transient = bool(failed) and all(
            row.get("error_type") in TRANSPORT_ERRORS
            or (
                row.get("error_type") == "ClientError"
                and row.get("error_code") in TEMPORARY_AWS_ERRORS
            )
            for row in failed
        )
        if complete and transient:
            # Start from the failure timestamp, not the earlier reservation: a
            # cold start can delay when remote execution actually begins.
            try:
                ended = max(datetime.fromisoformat(row["at"]) for row in failed)
                until = ended + timedelta(seconds=TRANSPORT_SETTLE_SECONDS)
                wait = max(0, math.ceil((until - now).total_seconds()))
                detail.update(kind="transport_failure", recoverable=True, wait_seconds=wait)
            except (ValueError, TypeError):
                pass  # Incomplete timestamp evidence cannot authorize recovery.
        elif complete and not failed:
            path = directory / f"result-{identifier}.json"
            try:
                if path.resolve() != path or not path.is_file():
                    raise ValueError("Missing unaliased result")
                result = UiResult.model_validate_json(path.read_bytes())
                response = result.response
                if (
                    result.mode != reservation["mode"]
                    or response.diagnostics.model_id != model_ids[key]
                    or response.dataset_version != "retail-v1"
                ):
                    raise ValueError("Result does not match this request's model/scope")
                detail["error_code"] = response.error_code
                if (
                    response.status == "answer"
                    and response.results
                    and result.presentation_status == "fallback"
                    and response.answer == _render(list(response.results))
                ):
                    detail.update(kind="presentation_fallback", recoverable=True)
                elif response.status == "error" and response.error_code in QUESTION_LIMITS:
                    detail.update(kind="question_limit", recoverable=True)
            except (ValueError, OSError, KeyError):
                pass
        failures.append(detail)
    return failures
