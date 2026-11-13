"""Verify a client-only workbench repair and inspect retained attempts without AWS calls.

The deployed archive, agent, semantic code, approvals and allowance stay pinned.
Only the enumerated operator/UI files may differ from the accepted source inventory.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from enterprise_analytics_agent.ui.model_streams import StreamingLedger, StreamingReview
from enterprise_analytics_agent.ui.models import UiError

SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
OPERATOR_FILES = frozenset(
    "src/enterprise_analytics_agent/" + name
    for name in (
        "adapters/model_stream_ui.py",
        "ui/__main__.py",
        "ui/model_streams.py",
        "ui/streaming_health.py",
        "ui/workbench_repair.py",
        "ui/assets/app.js",
    )
)


class OperatorRepair(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["workbench-client-repair-v1"]
    review_sha256: SHA
    baseline_source_files: dict[str, SHA]
    operator_source_files: dict[str, SHA]
    minimum_recorded_attempts: Annotated[int, Field(strict=True, ge=1, le=40)] = 1


def source_inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted((root / "src").rglob("*")):
        if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}:
            if path.resolve() != path:
                raise UiError("Operator source must not contain aliased files.")
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def verify_operator_repair(root: Path, review: StreamingReview, repair: OperatorRepair) -> None:
    if (
        review.schema_version != "bedrock-model-workbench-v1"
        or repair.review_sha256 != review.sha256
    ):
        raise UiError("This client repair is not bound to the current workbench review.")
    baseline_hash = hashlib.sha256(
        json.dumps(repair.baseline_source_files, sort_keys=True).encode()
    ).hexdigest()
    if baseline_hash != review.source_sha256:
        raise UiError("The repair baseline differs from the accepted agent source.")
    if not repair.operator_source_files or not set(repair.operator_source_files) <= OPERATOR_FILES:
        raise UiError("A client repair cannot change agent, semantic, hosting or model code.")
    current = source_inventory(root)
    expected = {**repair.baseline_source_files, **repair.operator_source_files}
    if current != expected:
        raise UiError("Current source differs from the exact client repair; no AWS call was sent.")


def verify_retained_attempts(ledger: StreamingLedger, repair: OperatorRepair) -> None:
    if not ledger.path.is_file():
        raise UiError(
            "The retained workbench ledger is missing. Restore it from the original checkout."
        )
    used = ledger.summary()["used"]
    if not isinstance(used, int) or used < repair.minimum_recorded_attempts:
        raise UiError(
            "The retained ledger predates the failure checkpoint; do not create a new allowance."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--operator-repair", type=Path)
    parser.add_argument("--last", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.last <= 40:
        parser.error("--last must be between 1 and 40")
    root = Path(__file__).resolve().parents[3]
    if Path.cwd().resolve() != root:
        parser.error("Run from the original repository root")
    try:
        review = StreamingReview.model_validate_json(args.review.read_bytes())
        if review.schema_version != "bedrock-model-workbench-v1":
            raise UiError("This diagnostic applies only to the current workbench campaign.")
        if args.operator_repair:
            repair = OperatorRepair.model_validate_json(args.operator_repair.read_bytes())
            verify_operator_repair(root, review, repair)
        ledger = StreamingLedger(root, review, recover_requests=bool(args.operator_repair))
        if not ledger.path.is_file():
            raise UiError(
                "Local attempt evidence is unavailable here; this is not a zero-use campaign."
            )
        if args.operator_repair:
            verify_retained_attempts(ledger, repair)
        # summary validates the immutable journal and all matching SDK receipts.
        state = ledger.summary()
        rows = ledger._rows()
        reserved = [row for row in rows if row["event"] == "reserved"]
        latest = {row["request_id"] for row in reserved[-args.last :]}
        report = {
            "mode": "offline-read-only",
            "campaign_id": review.campaign_id,
            "operator_repair_verified": bool(args.operator_repair),
            "budget": state,
            "latest_attempts": [
                {
                    **{key: row[key] for key in ("request_id", "model_key", "mode", "at")},
                    "outcome": next(
                        (
                            r["status"]
                            for r in rows
                            if r["event"] == "outcome" and r["request_id"] == row["request_id"]
                        ),
                        "incomplete",
                    ),
                    "sdk_errors": [
                        {k: r[k] for k in ("operation", "error_type", "error_code") if k in r}
                        for r in rows
                        if r["event"] == "sdk_failed" and r["request_id"] == row["request_id"]
                    ],
                }
                for row in reserved
                if row["request_id"] in latest
            ],
            "aws_calls": 0,
            "ledger_modified": False,
        }
        print(json.dumps(report, indent=2))
        return 0
    except (UiError, ValueError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc), "aws_calls": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
