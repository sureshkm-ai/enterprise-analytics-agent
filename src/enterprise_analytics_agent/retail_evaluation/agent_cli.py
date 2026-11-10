"""Question CLI with offline response replay and explicitly enabled counted dispatch."""

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.retail_evaluation.campaign import CampaignError, CampaignLedger
from enterprise_analytics_agent.retail_evaluation.client import CountedAgentClient, InvocationError
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget


def render_text(response: AgentResponse) -> str:
    lines = [response.answer, f"Status: {response.status}; dataset: {response.dataset_version}"]
    for result in response.results:
        lines.append(
            f"{result.metric_id} v{result.definition_version} "
            f"[{result.time_range.start}, {result.time_range.end}) "
            f"unit={result.unit} currency={result.currency or 'null'} "
            f"group_by={','.join(result.group_by) or '(none)'}"
        )
        if not result.rows:
            lines.append("  (no rows)")
        for row in result.rows:
            dimensions = ", ".join(f"{key}={value}" for key, value in row.dimensions.items())
            value = "null" if row.value is None else str(row.value)
            lines.append(f"  {dimensions + ': ' if dimensions else ''}{value}")
    for metric, version in sorted(response.metric_versions.items()):
        lines.append(f"Metric version: {metric}={version}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Display a saved answer or explicitly invoke M5.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--response-file", type=Path)
    mode.add_argument("--invoke-live", action="store_true")
    parser.add_argument("--target-config", type=Path)
    parser.add_argument("--question")
    purpose = parser.add_mutually_exclusive_group()
    purpose.add_argument("--restoration-smoke", action="store_true")
    purpose.add_argument("--warmup", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    elapsed: int | None = None
    try:
        if args.response_file is not None:
            if (
                args.target_config is not None
                or args.question is not None
                or args.restoration_smoke
                or args.warmup
            ):
                raise ValueError("response replay accepts neither a question nor a target")
            response = AgentResponse.model_validate_json(args.response_file.read_text())
        else:
            if args.target_config is None or args.question is None:
                raise ValueError("live invocation requires --target-config and --question")
            AgentRequest(question=args.question)
            target = RetailTarget.model_validate_json(args.target_config.read_text())
            if not args.restoration_smoke and target.dataset_version != "retail-v1":
                raise ValueError(
                    "parity invocation requires the verified restoration smoke workflow"
                )
            if args.warmup and args.question != "Show net_revenue for January 2025 by region.":
                raise ValueError("warm-up requires the fixed January net revenue question")
            if args.restoration_smoke and (
                target.dataset_version != "parity-v1"
                or args.question != "Show net_revenue for January 2025 by region."
            ):
                raise ValueError("restoration smoke requires the fixed parity query and target")
            # Lazy import is intentional: help/replay do not construct AWS clients.
            from enterprise_analytics_agent.adapters.agentcore_invocation import (
                create_runtime_invoker,
            )

            verifier = None
            if args.restoration_smoke:
                from enterprise_analytics_agent.adapters.retail_checkpoint import verify_restoration

                verifier = verify_restoration
            else:
                from enterprise_analytics_agent.adapters.retail_checkpoint import verify_checkpoint

                try:
                    checkpoint = verify_checkpoint(scope="retail-v1")
                except Exception as exc:
                    raise InvocationError("checkpoint_verification_error") from exc
                if checkpoint["runtime"]["agentRuntimeArn"] != target.runtime_arn:
                    raise ValueError("verified checkpoint addresses a different Runtime")
            result = CountedAgentClient(
                target,
                CampaignLedger(),
                create_runtime_invoker(target),
                purpose=(
                    "restoration_smoke"
                    if args.restoration_smoke
                    else "warmup"
                    if args.warmup
                    else "demo"
                ),
                restoration_verifier=verifier,
            ).invoke(args.question)
            response, elapsed = result.response, result.elapsed_ms
            if args.restoration_smoke:
                _check_restoration_smoke(response)
        print(
            response.model_dump_json(indent=2) if args.format == "json" else render_text(response)
        )
        diagnostic = {
            "model_id": response.diagnostics.model_id,
            "client_elapsed_ms": elapsed,
            "model_calls": (
                response.diagnostics.model_calls
                if "model_calls" in response.diagnostics.model_fields_set
                else None
            ),
            "tool_calls": (
                len(response.diagnostics.tool_calls)
                if "tool_calls" in response.diagnostics.model_fields_set
                else None
            ),
            "athena_records": (
                len(response.diagnostics.athena)
                if "athena" in response.diagnostics.model_fields_set
                else None
            ),
        }
        print(json.dumps(diagnostic), file=sys.stderr)
        return {"answer": 0, "clarification": 2, "error": 1}[response.status]
    except (OSError, ValueError, ValidationError, CampaignError, RuntimeError) as exc:
        # Never print SDK exceptions, signed URLs, response headers or arbitrary SQL.
        code = exc.code if isinstance(exc, InvocationError) else type(exc).__name__
        print(f"analytics-ask: {code}", file=sys.stderr)
        return 1


def _check_restoration_smoke(response: AgentResponse) -> None:
    if response.status != "answer" or len(response.results) != 1:
        raise ValueError("restoration smoke did not return one answer result")
    result = response.results[0]
    if (
        result.metric_id != "net_revenue"
        or result.definition_version != "1.0.0"
        or result.group_by != ("region",)
        or result.time_range.start.isoformat() != "2025-01-01"
        or result.time_range.end.isoformat() != "2025-02-01"
        or result.unit != "currency"
        or result.currency != "USD"
        or len(result.rows) != 2
        or {(tuple(row.dimensions.items()), row.value) for row in result.rows}
        != {((("region", "North"),), Decimal("28.50")), ((("region", "South"),), Decimal("13.00"))}
    ):
        raise ValueError("restoration smoke differs from independent parity expectations")
