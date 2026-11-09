"""Offline review by default; upload binding and execution require separate explicit gates."""

import argparse
import json
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from enterprise_analytics_agent.retail_evaluation.repair_config import load_review, select_repair


@contextmanager
def interruption_guard() -> Iterator[None]:
    """Make ordinary SIGTERM follow the same restoration path as Ctrl-C."""

    def terminate(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt("termination requested; restoring the original runtime")

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    action = parser.add_subparsers(dest="action", required=True)
    action.add_parser("verify-offline")
    bind = action.add_parser("bind-upload")
    bind.add_argument("--verify-upload", action="store_true", required=True)
    bind.add_argument("--upload-response", type=Path, required=True)
    bind.add_argument("--output", type=Path, required=True)
    for name in ("run", "restore"):
        command = action.add_parser(name)
        command.add_argument("--invoke-live", action="store_true", required=True)
        command.add_argument("--version-record", type=Path, required=True)
        command.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.campaign != "q18-repair-v1":
            raise ValueError("unknown reviewed campaign")
        review = load_review()
        if args.action == "verify-offline":
            from enterprise_analytics_agent.retail_evaluation.deployment import (
                review_candidate_assemblies,
            )

            print(
                json.dumps(
                    {
                        "review_sha256": review.review_sha256,
                        "artifacts": review_candidate_assemblies(review),
                    },
                    indent=2,
                )
            )
            return 0
        if args.action == "bind-upload":
            from enterprise_analytics_agent.adapters.repair_operations import (
                verify_uploaded_version,
                write_version_record,
            )

            # Constructing/reading this model never invents a production VersionId.
            uploaded = json.loads(args.upload_response.read_bytes())
            if not isinstance(uploaded, dict):
                raise ValueError("upload response must be an object")
            version = verify_uploaded_version(review, uploaded)
            write_version_record(args.output, version)
            print(version.model_dump_json(indent=2))
            return 0
        review, version, _ = select_repair(args.campaign, args.version_record)
        if args.report_dir.exists():
            raise ValueError("report directory already exists; preserve previous evidence")
        from enterprise_analytics_agent.adapters.repair_operations import operations_for
        from enterprise_analytics_agent.retail_evaluation.repair_workflow import run_repair

        with interruption_guard():
            state = run_repair(
                review,
                version,
                operations_for(
                    review, version, args.report_dir, restore_only=args.action == "restore"
                ),
                args.report_dir,
                restore_only=args.action == "restore",
            )
        print(json.dumps(state, indent=2))
        if args.action == "restore":
            return 0 if state["restored"] and state["smoke_passed"] else 1
        return 0 if state["accepted"] else 1
    except Exception as exc:
        print(f"analytics-repair: {type(exc).__name__}; inspect retained evidence", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
