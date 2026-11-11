"""Separately reviewed full offline/live validation; no cloud calls on import.

Run prepare/verify-offline first. Execution and restoration require explicit approval;
neither a flag nor the proposed review supplies that approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import boto3
import pytest

from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
from enterprise_analytics_agent.adapters.aws_runtime import load_runtime_config
from enterprise_analytics_agent.adapters.deployment_controller import DeploymentController
from enterprise_analytics_agent.adapters.operator_reads import ReadPool
from enterprise_analytics_agent.adapters.retail_checkpoint import _verify_checkpoint
from enterprise_analytics_agent.adapters.ui_release import verify_local_release, verify_publication
from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2
from enterprise_analytics_agent.retail_evaluation.assembly_assets import (
    rewrite_template_asset,
    validate_assembly,
)
from enterprise_analytics_agent.retail_evaluation.client import InvocationResult
from enterprise_analytics_agent.retail_evaluation.deployment import TEMPLATE_NAME, digest
from enterprise_analytics_agent.retail_evaluation.full_live import (
    FullLiveBudget,
    FullLiveContinuationReview,
    FullLiveReview,
)
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.retail_evaluation.reporting import _redact
from enterprise_analytics_agent.retail_evaluation.runner import LiveRunDependencies
from enterprise_analytics_agent.ui.shared import SharedReview
from infrastructure.agentcore.ui_workflow import _operator_lease

ROOT = Path(__file__).resolve().parents[2]
PREPARED = ROOT / "artifacts/full-live/prepared"
CANDIDATE = ROOT / "artifacts/milestone-5/q18-repair-v1/cdk.candidate.out"
REVIEW_PATH = ROOT / "evaluations/full-live/review.proposed.json"
_PHASE: dict[str, Any] = {}
MIN_START_SECONDS = 4 * 3600
MIN_SWITCH_SECONDS = 2 * 3600


def write(path: Path, value: object) -> None:
    encoded = json.dumps(_redact(value), indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def local_review(root: Path = ROOT) -> dict[str, Any]:
    ui = SharedReview.model_validate_json(
        (root / "evaluations/ui-shared/review.proposed.json").read_bytes()
    )
    return verify_local_release(root, ui, root / "artifacts/milestone-5/canonical/retail-v1")


def retail_target(review: FullLiveReview | FullLiveContinuationReview) -> RetailTarget:
    return RetailTarget(
        profile=review.profile,
        account=review.account,
        region=review.region,
        runtime_arn=review.runtime_arn,
        qualifier=review.qualifier,
        model_id=review.model_id,
        dataset_version="retail-v1",
        reference_date="2025-04-01",
    )


def validate_smoke(
    result: AgentResponse, review: FullLiveReview | FullLiveContinuationReview
) -> None:
    """Full independent Q18 plan/result gate without canonical files or adapter output."""
    expected_query = QueryMetricRequestV2.model_validate(
        {"metric_id": "net_revenue", "time_range": {"start": "2025-03-31", "end": "2025-04-01"}}
    )
    queries = [
        QueryMetricRequestV2.model_validate(call.arguments)
        for call in result.diagnostics.tool_calls
        if call.name == "query_metric" and call.status == "success"
    ]
    expected_config = {
        "model_id": review.model_id,
        "reference_date": "2025-04-01",
        "max_iterations": 6,
        "max_tool_calls": 16,
        "max_output_tokens": 1024,
        "max_total_tokens": 12000,
        "timeout_seconds": 90.0,
    }
    if (
        result.status != "answer"
        or result.dataset_version != "retail-v1"
        or result.metric_versions != {"net_revenue": "1.0.0"}
        or queries != [expected_query]
        or len(result.results) != 1
        or result.diagnostics.model_id != review.model_id
        or result.diagnostics.configuration != expected_config
    ):
        raise ValueError("Restored retail Q18 plan/configuration differs")
    metric = result.results[0]
    if (
        metric.metric_id != "net_revenue"
        or metric.definition_version != "1.0.0"
        or metric.currency != "USD"
        or metric.unit != "currency"
        or metric.group_by != ()
        or len(metric.rows) != 1
        or metric.rows[0].dimensions != {}
        or str(metric.rows[0].value) != "110.25"
        or metric.time_range != expected_query.time_range
    ):
        raise ValueError("Restored retail Q18 result differs from independent expectation")
    if not any(
        diagnostic.get("metric_id") == "net_revenue"
        and diagnostic.get("dataset_version") == "retail-v1"
        and diagnostic.get("metric_version") == "1.0.0"
        and diagnostic.get("state") == "SUCCEEDED"
        and isinstance(diagnostic.get("query_id"), str)
        and bool(diagnostic["query_id"])
        and type(diagnostic.get("scanned_bytes")) is int
        and cast(int, diagnostic["scanned_bytes"]) >= 0
        for diagnostic in result.diagnostics.athena
    ):
        raise ValueError("Restored retail Q18 Athena evidence is incomplete")


def parity_variant(retail: dict[str, Any]) -> dict[str, Any]:
    """Derive the only allowed temporary configuration without changing code/IAM."""
    parity = json.loads(json.dumps(retail))
    env = parity["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"]
    settings = json.loads(env["ANALYTICS_RUNTIME_CONFIG"])
    settings.update(dataset_version="parity-v1", tenant_id="t1", reference_date="2025-02-01")
    env["ANALYTICS_RUNTIME_CONFIG"] = json.dumps(settings, sort_keys=True)
    return parity  # type: ignore[no-any-return]


def prepare(output: Path, *, root: Path = ROOT) -> dict[str, Any]:
    """Copy frozen code assemblies and change only trusted parity configuration."""
    local = local_review(root)
    if output.exists():
        raise ValueError("Preserve existing full-validation preparation")
    output.mkdir(parents=True)
    source = root / "artifacts/milestone-5/q18-repair-v1/cdk.candidate.out"
    if any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("Retained assembly contains symlinks")
    for name in ("retail", "parity"):
        shutil.copytree(source, output / name)
    retail_path = output / "retail" / TEMPLATE_NAME
    retail = json.loads(retail_path.read_bytes())
    parity = parity_variant(retail)
    parity_path = output / "parity" / TEMPLATE_NAME
    parity_path.write_text(json.dumps(parity, indent=2) + "\n")
    validate_assembly(output / "retail", digest(retail_path))
    rewrite_template_asset(output / "parity")
    validate_assembly(output / "parity", digest(parity_path))
    # Fail if any resource/IAM/code difference sneaks into the environment-only variant.
    compared = json.loads(json.dumps(parity))
    compared["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"] = retail[
        "Resources"
    ]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"]
    if compared != retail:
        raise ValueError("Full-validation delta exceeds trusted environment")
    target = json.loads((root / "evaluations/ui-shared/review.proposed.json").read_bytes())[
        "target"
    ]
    agent = {**target, "dataset_version": "parity-v1", "reference_date": "2025-02-01"}
    write(output / "agent.parity.json", agent)
    write(output / "retail.json", target)
    record = {
        "schema_version": "full-live-assemblies-v1",
        "retail_template_sha256": digest(retail_path),
        "parity_template_sha256": digest(parity_path),
        "configuration_delta": {
            "dataset_version": ["retail-v1", "parity-v1"],
            "tenant_id": ["retail_demo", "t1"],
            "reference_date": ["2025-04-01", "2025-02-01"],
        },
        "files": {
            str(path.relative_to(output)): digest(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
        "local": local,
    }
    write(output / "assembly-review.json", record)
    return record


def verify_offline(
    review: FullLiveReview | FullLiveContinuationReview,
    *,
    root: Path = ROOT,
    restore_only: bool = False,
    prepared: Path | None = None,
) -> dict[str, Any]:
    if not restore_only:
        config_path = root / "infrastructure/cdk/config.development.json"
        if digest(config_path) != review.aws_config_sha256:
            raise ValueError("Athena development configuration differs from the reviewed pin")
        config = load_runtime_config(config_path)
        if (
            config.profile != review.profile
            or config.account != review.account
            or config.region != review.region
            or config.workgroup_name != review.workgroup_name
        ):
            raise ValueError("Athena profile/account/region/workgroup differs from review")
    prepared = prepared if prepared is not None else root / "artifacts/full-live/prepared"
    record_path = prepared / "assembly-review.json"
    if (
        isinstance(review, FullLiveContinuationReview)
        and digest(record_path) != review.prepared_inventory_sha256
    ):
        raise ValueError("Continuation prepared inventory differs from its reviewed pin")
    record = json.loads(record_path.read_bytes())
    expected = {
        name: value
        for name, value in record["files"].items()
        if not restore_only or name.startswith("retail/")
    }
    actual = {
        str(path.relative_to(prepared)): digest(path)
        for path in prepared.rglob("*")
        if path.is_file()
        and path.name != "assembly-review.json"
        and (not restore_only or path.is_relative_to(prepared / "retail"))
    }
    checked = prepared / "retail" if restore_only else prepared
    if actual != expected or any(p.is_symlink() for p in checked.rglob("*")):
        raise ValueError("Full-validation assembly inventory differs")
    if (
        not restore_only
        and digest(prepared / "parity" / TEMPLATE_NAME) != review.parity_template_sha256
    ):
        raise ValueError("Parity template differs from reviewed pin")
    if digest(prepared / "retail" / TEMPLATE_NAME) != review.retail_template_sha256:
        raise ValueError("Retail restoration template differs from reviewed pin")
    validate_assembly(prepared / "retail", review.retail_template_sha256)
    if not restore_only:
        validate_assembly(prepared / "parity", review.parity_template_sha256)
    retail = json.loads((prepared / "retail" / TEMPLATE_NAME).read_bytes())
    derived = json.dumps(parity_variant(retail), indent=2) + "\n"
    if hashlib.sha256(derived.encode()).hexdigest() != review.parity_template_sha256:
        raise ValueError("Temporary parity variant exceeds the reviewed environment-only delta")
    if restore_only:
        archive = root / "artifacts/milestone-5/q18-repair-v1/candidate/agent.zip"
        if digest(archive) != review.archive_sha256:
            raise ValueError("Frozen candidate restoration ZIP differs")
        local = {"scope": "Frozen retail restoration; no current source/data required"}
    else:
        local = local_review(root)
    return {
        "review_sha256": review.sha256,
        "prepared": record["configuration_delta"],
        "local": local,
        "budget": {"scope": "Restoration does not depend on readable accounting"}
        if restore_only
        else FullLiveBudget(review, repository_root=root).summary(),
        "scope": "Offline verification only; no execution approval or AWS access is inferred.",
    }


def checkpoint(
    review: FullLiveReview | FullLiveContinuationReview,
    kind: str,
    reads: ReadPool,
    *,
    root: Path = ROOT,
    deadline: float | None = None,
    prepared: Path | None = None,
) -> dict[str, Any]:
    if kind not in {"retail", "parity"}:
        raise ValueError("Unknown reviewed configuration")
    path = (prepared or root / "artifacts/full-live/prepared") / kind / TEMPLATE_NAME
    expected = review.retail_template_sha256 if kind == "retail" else review.parity_template_sha256
    if digest(path) != expected:
        raise ValueError("Reviewed template changed")
    deadline = deadline if deadline is not None else time.monotonic() + 180
    proof = _verify_checkpoint(
        scope="retail-v1" if kind == "retail" else "parity-v1",
        path=path,
        artifact_path=root / "artifacts/milestone-5/q18-repair-v1/candidate/agent.zip",
        artifact_sha256=review.archive_sha256,
        artifact_version_id=review.artifact_version_id,
        review={"full_live_review_sha256": review.sha256},
        session=reads.view(deadline, "full-live-" + kind),
    )
    stack = (
        reads.view(deadline, "full-live-parameters")
        .client("cloudformation")
        .describe_stacks(StackName="enterprise-analytics-dev-agent-runtime")["Stacks"][0]
    )
    if {p["ParameterKey"]: p["ParameterValue"] for p in stack["Parameters"]} != {
        "ArtifactVersionId": review.artifact_version_id,
        "BootstrapVersion": "/cdk-bootstrap/hnb659fds/version",
    }:
        raise ValueError("Runtime parameter inventory differs")
    return proof


def operations(
    review: FullLiveReview | FullLiveContinuationReview,
    output: Path,
    *,
    restore_only: bool = False,
    prepared: Path | None = None,
) -> dict[str, Callable[..., Any]]:
    prepared = prepared if prepared is not None else PREPARED
    verify_offline(review, restore_only=restore_only, prepared=prepared)
    session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
    reads = ReadPool(session, output / "operator-reads.jsonl")
    identity = (
        reads.view(time.monotonic() + 90, "full-live-identity").client("sts").get_caller_identity()
    )
    if identity.get("Account") != "453711491609":
        raise ValueError("Full validation account differs")
    if not restore_only:
        ui = SharedReview.model_validate_json(
            (ROOT / "evaluations/ui-shared/review.proposed.json").read_bytes()
        )
        publication = verify_publication(
            ui, reads.view(time.monotonic() + 180, "full-live-publication")
        )
        write(output / "publication.json", publication)
    templates = {
        kind: json.loads((prepared / kind / TEMPLATE_NAME).read_bytes())
        for kind in (("retail",) if restore_only else ("parity", "retail"))
    }
    if restore_only:
        templates["parity"] = parity_variant(templates["retail"])

    def baseline(stack: dict[str, Any], template: dict[str, Any]) -> None:
        if template not in templates.values():
            raise ValueError("Current template is outside the two reviewed configurations")
        params = {p["ParameterKey"]: p["ParameterValue"] for p in stack["Parameters"]}
        if params.get("ArtifactVersionId") != review.artifact_version_id:
            raise ValueError("Current Runtime code version differs")

    controller = DeploymentController(
        output,
        reads.view(time.monotonic() + 120, "full-live-controller").client("cloudformation"),
        lock_path=ROOT / "artifacts/milestone-5/runtime-deployment.lock",
        baseline_validator=baseline,
        read_client=lambda deadline: reads.view(deadline, "full-live-reconcile").client(
            "cloudformation"
        ),
    )

    def deploy(kind: str) -> dict[str, Any]:
        return controller.deploy(
            str(prepared / kind),
            review.artifact_version_id,
            kind,
            lambda deadline: checkpoint(review, kind, reads, deadline=deadline, prepared=prepared),
            template_sha256=(
                review.retail_template_sha256 if kind == "retail" else review.parity_template_sha256
            ),
        )

    def smoke() -> AgentResponse:
        proof = checkpoint(review, "retail", reads, prepared=prepared)
        target = retail_target(review)
        invoke = create_runtime_invoker(
            target,
            session=session,
            identity_session=reads.view(time.monotonic() + 30, "full-live-smoke-setup"),
        )
        from uuid import uuid4

        reply = invoke(
            payload=AgentRequest(question="Show net_revenue for yesterday.")
            .model_dump_json()
            .encode(),
            session_id=str(uuid4()),
        )
        try:
            result = AgentResponse.model_validate_json(reply.body.read())
        finally:
            reply.body.close()
        validate_smoke(result, review)
        write(
            output / "restoration-smoke.json",
            {
                "proof": proof,
                "response": result.model_dump(mode="json"),
            },
        )
        return result

    return {
        "verify": lambda kind: checkpoint(review, kind, reads, prepared=prepared),
        "deploy": deploy,
        "smoke": smoke,
    }


def run_phase(
    phase: str,
    review: FullLiveReview | FullLiveContinuationReview,
    review_path: Path,
    output: Path,
) -> bool:
    reports = output / phase
    reports.mkdir()
    base = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "--fail-on-skip",
        "-x",
        "-q",
        "--junitxml=" + str(reports / "junit.xml"),
    ]
    selected = {
        "offline": ["-m", "not aws_integration and not agent_live and not retail_live"],
        "athena_parity": [
            "-m",
            "aws_integration",
            "--run-aws",
            "--aws-config=infrastructure/cdk/config.development.json",
        ],
        "agent_parity": [
            "-m",
            "agent_live",
            "--run-agent-live",
            "--agent-config=" + str(PREPARED / "agent.parity.json"),
        ],
        "retail": [
            "-m",
            "retail_live",
            "--run-retail-live",
            "--retail-config=" + str(PREPARED / "retail.json"),
        ],
    }
    env = dict(os.environ)
    if phase != "offline":
        base += ["-p", "infrastructure.agentcore.full_live"]
        env.update(
            ANALYTICS_FULL_LIVE_REVIEW=str(review_path.resolve()),
            ANALYTICS_FULL_LIVE_PHASE=phase,
            ANALYTICS_FULL_LIVE_OUTPUT=str(reports.resolve()),
            ANALYTICS_FULL_LIVE_APPROVAL=review.sha256,
        )
    with (reports / "pytest.log").open("x") as log:
        process = subprocess.Popen(
            [*base, *selected[phase]],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            status = process.wait(timeout=1800)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            raise
    if status != 0:
        return False
    import xml.etree.ElementTree as ET

    cases = list(ET.parse(reports / "junit.xml").getroot().iter("testcase"))
    required = {"athena_parity": 66, "agent_parity": 18, "retail": 1}
    if (
        not cases
        or len({(case.get("classname"), case.get("name")) for case in cases}) != len(cases)
        or any(
            c.find("skipped") is not None
            or c.find("failure") is not None
            or c.find("error") is not None
            for c in cases
        )
        or phase in required
        and len(cases) != required[phase]
    ):
        return False
    return True


def execute(
    review: FullLiveReview,
    review_path: Path,
    output: Path,
    *,
    restore_only: bool = False,
    ops: dict[str, Callable[..., Any]] | None = None,
    phase_runner: Callable[..., bool] = run_phase,
) -> dict[str, Any]:
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("Run full validation from the reviewed repository root")
    if output.exists():
        raise ValueError("Preserve prior full-suite output")
    if (
        not restore_only
        and (review.expires_at - datetime.now(UTC)).total_seconds() < MIN_START_SECONDS
    ):
        raise ValueError("Less than four hours remain for bounded tests and restoration")
    output.mkdir(parents=True)
    budget: FullLiveBudget | None = None
    budget_setup_error = None
    try:
        budget = FullLiveBudget(review, repository_root=ROOT)
    except Exception as exc:
        if not restore_only:
            raise
        budget_setup_error = error_record(exc, "full-live-budget-setup")
    result: dict[str, Any] = {
        "review_sha256": review.sha256,
        "accepted": False,
        "phases": {},
        "temporary_update_attempted": False,
        "restored": False,
    }
    if budget_setup_error is not None:
        result["budget_setup_error"] = budget_setup_error
    calls: dict[str, Callable[..., Any]] | None = None
    with _operator_lease(ROOT):
        claim = ROOT / "artifacts/full-live/full-live-v1/execution-claim.json"
        if restore_only:
            if not claim.exists():
                raise ValueError("No retained full-suite attempt to restore")
            retained = json.loads(claim.read_bytes())
            if retained.get("review_sha256") != review.sha256:
                raise ValueError("Retained full-suite claim differs from review")
            original_output = Path(retained.get("output", "")).resolve()
            if not original_output.is_relative_to(ROOT / "artifacts/full-live"):
                raise ValueError("Retained full-suite output binding differs")
        else:
            write(
                claim,
                {"review_sha256": review.sha256, "output": str(output), "parent_pid": os.getpid()},
            )
        try:
            calls = ops or operations(review, output, restore_only=restore_only)
            if not restore_only:
                assert budget is not None
                start = calls["verify"]("retail")
                if start["runtime"]["agentRuntimeVersion"] != review.starting_runtime_version:
                    raise ValueError("Starting retail checkpoint version differs")
                write(output / "starting-checkpoint.json", start)
                for phase in ("offline", "athena_parity", "retail"):
                    passed = phase_runner(phase, review, review_path, output)
                    result["phases"][phase] = passed
                    if not passed:
                        budget.stop("pytest_" + phase + "_failed")
                        raise RuntimeError(phase + " verification failed; no retry")
                if (review.expires_at - datetime.now(UTC)).total_seconds() < MIN_SWITCH_SECONDS:
                    raise ValueError("Less than two hours remain for parity tests and restoration")
                result["temporary_update_attempted"] = True
                write(output / "parity-checkpoint.json", calls["deploy"]("parity"))
                result["phases"]["agent_parity"] = phase_runner(
                    "agent_parity", review, review_path, output
                )
                if not result["phases"]["agent_parity"]:
                    budget.stop("agent_parity_failed")
                    raise RuntimeError("Agent parity verification failed; no retry")
            result["tests_passed"] = not restore_only
        except BaseException as exc:
            result["error"] = error_record(exc, "full-live-verification")
            if not isinstance(exc, Exception):
                result["interruption"] = type(exc).__name__
        finally:
            # Any attempted config switch requires exact candidate-retail restoration.
            # Restoration-only also handles a retained interrupted attempt.
            need_cleanup = restore_only or result["temporary_update_attempted"]
            if not need_cleanup and result.get("error"):
                try:
                    if budget is None:
                        raise ValueError("Runtime accounting is unavailable")
                    used = budget.summary()["runtime_used"]
                    if not isinstance(used, int):
                        raise ValueError("Runtime accounting is unavailable")
                    need_cleanup = used > 0
                except Exception:
                    # Unknown accounting may not prevent nonbillable state verification.
                    need_cleanup = True
            if need_cleanup and calls is not None:
                try:
                    result["restoration_action"] = (
                        "deploy-retail"
                        if restore_only or result["temporary_update_attempted"]
                        else "verify-unchanged-retail"
                    )
                    restored = (
                        calls["deploy"]("retail")
                        if restore_only or result["temporary_update_attempted"]
                        else calls["verify"]("retail")
                    )
                    write(output / "restored-checkpoint.json", restored)
                    result["restored"] = True
                    if budget is None:
                        raise ValueError("Accounting unavailable; no restoration smoke dispatched")
                    with budget.counted_sdk("restoration_smoke"):
                        calls["smoke"]()
                    result["restoration_smoke_passed"] = True
                except BaseException as exc:
                    result["restoration_error"] = error_record(exc, "full-live-restoration")
            try:
                if budget is None:
                    raise ValueError("Runtime accounting is unavailable")
                result["budget"] = budget.summary()
            except Exception as exc:
                result["budget"] = {"runtime_used": None}
                result["budget_error"] = error_record(exc, "full-live-accounting")
            result["accepted"] = bool(
                result.get("tests_passed")
                and result["restored"]
                and result.get("restoration_smoke_passed")
                and not result.get("error")
                and result["budget"]["runtime_used"] == 56
                and result["budget"]["phases"]["agent_parity"] == 19
                and result["budget"]["phases"]["retail"] == 36
                and result["budget"]["phases"]["restoration_smoke"] == 1
                and 67 <= result["budget"]["direct_athena_submissions"] <= 201
                and not result["budget"]["failed"]
                and not result["budget"]["incomplete"]
                and not result["budget"].get("stopped", False)
            )
            write(output / "result.json", result)
    return result


# Explicit pytest -p plugin, loaded only by the separately approved operator.
def pytest_configure(config: pytest.Config) -> None:
    phase = os.environ.get("ANALYTICS_FULL_LIVE_PHASE")
    if not phase:
        return
    if phase not in {"athena_parity", "agent_parity", "retail"}:
        raise pytest.UsageError("Unknown reviewed full-live pytest phase")
    review_path = Path(os.environ["ANALYTICS_FULL_LIVE_REVIEW"])
    review = FullLiveReview.model_validate_json(review_path.read_bytes())
    if os.environ.get("ANALYTICS_FULL_LIVE_APPROVAL") != review.sha256:
        raise pytest.UsageError("Full live review approval binding differs")
    verify_offline(review)
    option, expected_path = {
        "athena_parity": ("aws_config", ROOT / "infrastructure/cdk/config.development.json"),
        "agent_parity": ("agent_config", PREPARED / "agent.parity.json"),
        "retail": ("retail_config", PREPARED / "retail.json"),
    }[phase]
    selected_path = config.getoption(option)
    if not selected_path or Path(selected_path).resolve() != expected_path.resolve():
        raise pytest.UsageError("Selected live suite configuration differs from its reviewed path")
    output = Path(os.environ["ANALYTICS_FULL_LIVE_OUTPUT"])
    claim = json.loads(
        (ROOT / "artifacts/full-live/full-live-v1/execution-claim.json").read_bytes()
    )
    if claim.get("review_sha256") != review.sha256 or claim.get("parent_pid") != os.getppid():
        raise pytest.UsageError("Missing reviewed parent operator attempt")
    budget = FullLiveBudget(review, repository_root=ROOT)
    _PHASE.update(review=review, budget=budget, phase=phase, output=output)
    if phase == "retail":
        reads = ReadPool(
            boto3.Session(profile_name="analytics-dev", region_name="us-west-2"),
            output / "operator-reads.jsonl",
        )
        cached: dict[str, Any] = {}

        def proof(target: RetailTarget) -> dict[str, object]:
            expected = retail_target(review)
            if target != expected:
                raise ValueError("Retail target differs from full-suite review")
            return checkpoint(review, "retail", reads)

        def invoke(question: str, *, session_id: str | None = None) -> InvocationResult:
            if "client" not in cached:
                cached["client"] = create_runtime_invoker(
                    retail_target(review),
                    session=reads.session,
                    identity_session=reads.view(time.monotonic() + 30, "full-retail-client"),
                )
            from uuid import uuid4

            from enterprise_analytics_agent.retail_evaluation.client import validate_target_response

            started = time.monotonic()
            reply = cached["client"](
                payload=AgentRequest(question=question).model_dump_json().encode(),
                session_id=session_id or str(uuid4()),
            )
            try:
                raw = json.loads(reply.body.read())
                response = AgentResponse.model_validate(raw)
            finally:
                reply.body.close()
            target = retail_target(review)
            validate_target_response(response, target)
            return InvocationResult(
                response, round((time.monotonic() - started) * 1000), reply.invocation_id, raw
            )

        config._reviewed_retail_dependencies = LiveRunDependencies(  # type: ignore[attr-defined]
            proof, invoke, budget.summary
        )
        config._reviewed_retail_report_dir = output / "retail-report"  # type: ignore[attr-defined]


def pytest_sessionstart(session: pytest.Session) -> None:
    if _PHASE:
        context = _PHASE["budget"].counted_sdk(_PHASE["phase"])
        context.__enter__()
        _PHASE["context"] = context


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _PHASE.get("context"):
        _PHASE["context"].__exit__(None, None, None)
        _PHASE.clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("prepare", "verify-offline", "preflight", "run", "restore")
    )
    parser.add_argument("--review", type=Path, default=REVIEW_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            value = prepare(args.output)
        else:
            review = FullLiveReview.model_validate_json(args.review.read_bytes())
            if args.action == "verify-offline":
                value = verify_offline(review)
                write(args.output, value)
            elif args.action == "preflight":
                with _operator_lease(ROOT):
                    calls = operations(review, args.output)
                    value = calls["verify"]("retail")
                    if value["runtime"]["agentRuntimeVersion"] != review.starting_runtime_version:
                        raise ValueError("Fresh starting checkpoint differs")
                    write(args.output / "preflight.json", value)
            else:
                if not args.execute_approved:
                    raise ValueError("Reviewed execution approval is required")
                from enterprise_analytics_agent.retail_evaluation.repair_cli import (
                    interruption_guard,
                )

                with interruption_guard():
                    value = execute(
                        review, args.review, args.output, restore_only=args.action == "restore"
                    )
        print(json.dumps(_redact(value), indent=2))
        return (
            0
            if args.action not in {"run", "restore"}
            or value.get("accepted")
            or (args.action == "restore" and value.get("restoration_smoke_passed"))
            else 1
        )
    except Exception as exc:
        print(json.dumps(error_record(exc, "full-live-command"), indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
