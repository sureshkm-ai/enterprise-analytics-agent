"""Run with poetry run python -m enterprise_analytics_agent.ui."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from enterprise_analytics_agent.ui.live import LiveReview
from enterprise_analytics_agent.ui.models import UiError
from enterprise_analytics_agent.ui.server import AgentModel, LiveBackend, Workbench, make_server


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local analytics browser UI; AWS is disabled by default."
    )
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--report", type=Path, help="Optional saved report.json to inspect offline")
    parser.add_argument("--live-review", type=Path, help="Legacy original-v12 allowance JSON")
    parser.add_argument(
        "--shared-review", type=Path, help="Approved shared two-mode allowance JSON"
    )
    parser.add_argument(
        "--release-record", type=Path, help="Verified post-deployment shared release"
    )
    parser.add_argument(
        "--canonical-dir", type=Path, default=Path("artifacts/milestone-5/canonical/retail-v1")
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Explicitly enable approved billable agent questions",
    )
    parser.add_argument(
        "--streaming-review", type=Path, help="Separately reviewed multi-model scope"
    )
    parser.add_argument(
        "--streaming-releases", type=Path, help="Actual uploaded/deployed release pins"
    )
    parser.add_argument(
        "--streaming-approval", type=Path, help="Explicit approval record for that scope"
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    streaming = any((args.streaming_review, args.streaming_releases, args.streaming_approval))
    if streaming and (args.live_review or args.shared_review or args.release_record):
        parser.error("streaming and historical release reviews cannot be combined")
    if streaming and not all(
        (args.streaming_review, args.streaming_releases, args.streaming_approval, args.allow_live)
    ):
        parser.error(
            "streaming mode requires its exact review, actual releases, approval and --allow-live"
        )
    if args.live_review and (args.shared_review or args.release_record):
        parser.error("legacy and shared release reviews cannot be enabled together")
    shared = args.shared_review is not None or args.release_record is not None
    if shared and not (args.shared_review and args.release_record and args.allow_live):
        parser.error(
            "shared mode requires --allow-live, --shared-review and --release-record after approval"
        )
    if not shared and not streaming and args.allow_live != (args.live_review is not None):
        parser.error("--allow-live and --live-review must be supplied together after approval")
    live: LiveBackend | None = None
    local_agent: LiveBackend | None = None
    model_backends: tuple[AgentModel, ...] = ()
    try:
        if args.allow_live:
            root = Path(__file__).resolve().parents[3]
            if Path.cwd().resolve() != root:
                raise UiError("Start live UI from the original repository root.")
            if streaming:
                import json

                from enterprise_analytics_agent.adapters.bedrock_model_catalog import get_model
                from enterprise_analytics_agent.adapters.model_stream_ui import StreamingQuestions
                from enterprise_analytics_agent.ui.model_streams import (
                    StreamingReleases,
                    StreamingReview,
                )

                stream_review = StreamingReview.model_validate_json(
                    args.streaming_review.read_bytes()
                )
                stream_releases = StreamingReleases.model_validate_json(
                    args.streaming_releases.read_bytes()
                )
                approval = json.loads(args.streaming_approval.read_bytes())
                choices = []
                for target in stream_review.targets:
                    backend = StreamingQuestions(
                        root,
                        stream_review,
                        stream_releases,
                        approval,
                        target.model_key,
                        args.canonical_dir,
                    )
                    model = get_model(target.model_key)
                    choices.append(
                        AgentModel(
                            model.key,
                            model.label,
                            model.model_id,
                            local_agent=backend,
                            live=backend,
                        )
                    )
                model_backends = tuple(choices)
            elif shared:
                from enterprise_analytics_agent.adapters.ui_release import ReleaseRecord
                from enterprise_analytics_agent.adapters.ui_shared import SharedQuestions
                from enterprise_analytics_agent.ui.shared import SharedReview

                shared_review = SharedReview.model_validate_json(args.shared_review.read_text())
                release = ReleaseRecord.model_validate_json(args.release_record.read_text())
                live = local_agent = SharedQuestions(
                    root, shared_review, release, args.canonical_dir
                )
            else:
                from enterprise_analytics_agent.adapters.ui_live import LiveQuestions

                review = LiveReview.model_validate_json(args.live_review.read_text())
                live = LiveQuestions(root, review)
            if live is not None and live.ledger.summary()["blocked"]:
                raise UiError("UI live allowance is expired, exhausted or blocked.")
        from enterprise_analytics_agent.adapters.bedrock_model_catalog import model_catalog

        proposed: tuple[dict[str, object], ...] = tuple(
            {
                "key": model.key,
                "label": model.label,
                "model_id": model.model_id,
                "provider": model.provider,
                "note": model.eligibility_note,
            }
            for model in model_catalog()
        )
        with TemporaryDirectory(prefix="enterprise-analytics-ui-") as directory:
            app = Workbench(
                Path(directory),
                live=live,
                local_agent=local_agent,
                report=args.report,
                model_backends=model_backends,
                proposed_models=proposed,
            )
            server = make_server(app, args.port)
            print(f"Analytics Workbench: http://127.0.0.1:{server.server_address[1]}", flush=True)
            print("Local sample data is temporary. Each question is independent.", flush=True)
            print(
                "BILLABLE: Local Bedrock and AWS AgentCore share one reviewed allowance."
                if local_agent or model_backends
                else "AWS mode enabled by explicit review."
                if live
                else "Offline playground only; model/AWS modes disabled; no AWS calls.",
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (ValueError, OSError, UiError) as exc:
        print(
            f"analytics-ui: {type(exc).__name__}; check port, report or live review.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
