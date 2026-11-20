"""Execute the shipped browser script offline to check truthful availability states."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ASSETS = Path(__file__).parents[1] / "src/enterprise_analytics_agent/ui/assets"
HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const nodes = new Map();
class Node {
  constructor() {
    this.textContent = ""; this.value = ""; this.children = [];
    this.disabled = false; this.hidden = false; this.dataset = {};
    this.classList = {toggle() {}, add() {}};
  }
  addEventListener() {}
  setAttribute() {}
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
}
const get = id => {
  if (!nodes.has(id)) nodes.set(id, new Node());
  return nodes.get(id);
};
const calls = [];
const scenario = JSON.parse(process.argv[2]);
const context = vm.createContext({
  document: {getElementById: get, querySelectorAll: () => [], createElement: () => new Node()},
  fetch: (...args) => {
    calls.push(args);
    return scenario.startup
      ? Promise.resolve({ok: true, json: async () => scenario.state})
      : new Promise(() => {});
  },
  location: {search: scenario.search || ""},
  URLSearchParams,
  console
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
context.scenario = scenario;
async function snapshot() {
if (scenario.startup) await new Promise(setImmediate);
else vm.runInContext(`
  state = scenario.state; mode = scenario.mode || "local"; busy = Boolean(scenario.busy);
  $("question").value = scenario.question || "";
  if (state) { modelPicker(); updateContext(); }
  ready();
`, context);
const ids = ["execution-state", "dataset", "reference-date", "target-details",
  "source-description", "mode-live-status", "mode-local_agent-status", "model-help",
  "live-notice-title", "live-notice-body", "composer-hint", "cost-notice"];
const result = Object.fromEntries(ids.map(id => [id, get(id).textContent]));
result.selected_mode = vm.runInContext("mode", context);
result.ask_disabled = get("ask-button").disabled;
result.picker_disabled = get("model-choice").disabled;
result.notice_hidden = get("live-notice").hidden;
result.model_groups = get("model-choice").children.map(child => child.label || child.textContent);
result.fetch_paths = calls.map(call => call[0]);
console.log(JSON.stringify(result));
}
snapshot().catch(error => { console.error(error); process.exitCode = 1; });
"""


def render(scenario: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for offline browser-script verification."
    result = subprocess.run(
        [node, "-e", HARNESS, str(ASSETS / "app.js"), json.dumps(scenario)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    value: dict[str, Any] = json.loads(result.stdout)
    assert value["fetch_paths"] == ["/api/state"]  # No question/invocation is dispatched.
    return value


def unconfigured_state() -> dict[str, Any]:
    return {
        "local": {
            "enabled": True,
            "dataset": "local-retail-samples",
            "reference_date": "2025-04-01",
        },
        # Reproduce the former misleading fallback. The browser must not present
        # this as a deployed target when no backend/model is actually configured.
        "local_agent": {"enabled": False, "dataset": "retail-v1"},
        "live": {"enabled": False, "dataset": "parity-v1", "runtime_version": "12"},
        "model_options": [],
    }


def configured_state(*, blocked: bool = False, error: str | None = None) -> dict[str, Any]:
    state = unconfigured_state()
    config = {
        "enabled": error is None,
        "configured": True,
        "dataset": "retail-v1",
        "reference_date": "2025-04-01",
        "model_id": "reviewed.model",
        "runtime_version": "15",
        "description": "A bound AWS target",
        "budget": {"used": 2, "maximum": 20, "blocked": blocked},
    }
    if error:
        config["error"] = error
    state["model_options"] = [
        {
            "key": "approved",
            "label": "Approved model",
            "model_id": "reviewed.model",
            "modes": {"live": config},
        }
    ]
    return state


def test_initial_page_does_not_claim_readiness_before_loading() -> None:
    html = (ASSETS / "index.html").read_text()
    assert 'id="execution-state">Loading workspace availability…' in html
    assert "Ready for a question" not in html
    assert "Agent modes need a reviewed release and a new allowance" not in html
    result = render({"state": None})
    assert result["ask_disabled"]
    assert result["execution-state"] == "Loading workspace availability…"


@pytest.mark.parametrize("mode", ["local_agent", "live"])
def test_unconfigured_modes_hide_fallback_deployment_and_cannot_look_ready(mode: str) -> None:
    result = render({"state": unconfigured_state(), "mode": mode, "question": "Revenue?"})
    assert result["ask_disabled"] and result["picker_disabled"]
    assert "not configured" in result["execution-state"]
    assert result["dataset"] == "Not configured"
    assert result["reference-date"] == "—"
    assert "v12" not in result["target-details"]
    assert "not configured" in result["source-description"]
    assert result["mode-live-status"] == "Not configured"
    assert not result["notice_hidden"]
    assert "is not connected to this workbench" in result["live-notice-title"]
    assert "changing tabs does not connect it" in result["live-notice-body"]
    assert "new allowance" not in result["live-notice-body"]
    assert "No live question can be submitted" in result["cost-notice"]


def test_offline_playground_is_usable_and_explicitly_has_no_model_or_aws_target() -> None:
    result = render({"state": unconfigured_state(), "question": "Revenue?"})
    assert not result["ask_disabled"]
    assert result["picker_disabled"]
    assert result["execution-state"] == "Offline question ready · no model calls"
    assert "no Bedrock model or deployed target" in result["target-details"]


@pytest.mark.parametrize("question", ["", "  "])
def test_empty_question_does_not_claim_ready_even_for_enabled_backend(question: str) -> None:
    result = render({"state": configured_state(), "mode": "live", "question": question})
    assert result["ask_disabled"]
    assert result["execution-state"] == "AWS AgentCore · enter a question"
    assert "ready" not in result["execution-state"].lower()
    assert "Bound Runtime version: v15" in result["target-details"]


def test_enabled_backend_can_be_ready_only_with_a_question() -> None:
    result = render({"state": configured_state(), "mode": "live", "question": "Revenue?"})
    assert not result["ask_disabled"] and not result["picker_disabled"]
    assert result["execution-state"] == "AWS AgentCore question ready · billable"
    assert result["dataset"] == "retail-v1"
    assert result["mode-live-status"] == "1 model(s) · billable"
    assert result["notice_hidden"]


def test_recovered_model_is_ready_and_shows_counted_previous_failure() -> None:
    state = configured_state()
    config = state["model_options"][0]["modes"]["live"]
    config.update(notice="Previous response timed out. A new submission is a billable attempt.")
    result = render({"state": state, "mode": "live", "question": "Revenue?"})
    assert not result["ask_disabled"] and not result["notice_hidden"]
    assert result["live-notice-title"] == "Model ready · previous request failed"
    assert "timed out" in result["live-notice-body"]
    assert "Unavailable" not in result["model_groups"][0]


@pytest.mark.parametrize("label", ["Acceptance failed", "Waiting after connection failure"])
def test_picker_distinguishes_acceptance_from_a_temporary_request_failure(label: str) -> None:
    state = configured_state(error="Inspect the recorded request.")
    state["model_options"][0]["modes"]["live"]["availability_label"] = label
    result = render({"state": state, "mode": "live", "question": "Revenue?"})
    assert result["ask_disabled"]
    assert result["model_groups"][0] == "Approved model · " + label


def test_closed_allowance_keeps_bound_metadata_but_cannot_look_ready() -> None:
    result = render(
        {"state": configured_state(blocked=True), "mode": "live", "question": "Revenue?"}
    )
    assert result["ask_disabled"]
    assert result["execution-state"] == "AWS AgentCore blocked · allowance unavailable"
    assert result["mode-live-status"] == "Allowance blocked"
    assert result["dataset"] == "retail-v1"
    assert not result["notice_hidden"]
    assert result["live-notice-title"] == "AWS AgentCore question allowance is unavailable"
    assert "existing allowance" in result["live-notice-body"]
    assert "permission" not in result["live-notice-body"]


def test_backend_failure_is_unavailable_instead_of_unconfigured_or_ready() -> None:
    result = render(
        {
            "state": configured_state(error="Ledger needs inspection"),
            "mode": "live",
            "question": "Revenue?",
        }
    )
    assert result["ask_disabled"]
    assert result["execution-state"] == "AWS AgentCore unavailable · inspect the message above"
    assert result["mode-live-status"] == "Unavailable"
    assert not result["notice_hidden"]
    assert result["live-notice-title"] == "AWS AgentCore is paused"
    assert result["live-notice-body"] == "Ledger needs inspection"


def test_configured_but_disabled_target_is_not_mislabeled_unconfigured() -> None:
    state = configured_state()
    state["model_options"][0]["modes"]["live"]["enabled"] = False
    result = render({"state": state, "mode": "live", "question": "Revenue?"})
    assert result["ask_disabled"]
    assert result["execution-state"] == "AWS AgentCore unavailable · target is disabled"
    assert result["mode-live-status"] == "Unavailable"
    assert result["dataset"] == "retail-v1"


def test_pending_catalog_is_labeled_unavailable_not_selectable() -> None:
    state = unconfigured_state()
    state["proposed_models"] = [
        {
            "key": "pending",
            "label": "Pending model",
            "provider": "Provider",
            "note": "Acceptance incomplete",
        }
    ]
    result = render({"state": state, "mode": "live", "question": "Revenue?"})
    assert result["ask_disabled"] and result["picker_disabled"]
    assert "Catalog models · not enabled in this workspace" in result["model_groups"]


@pytest.mark.parametrize(
    ("search", "expected_mode"),
    [
        ("?mode=live", "live"),
        ("?mode=local_agent", "local_agent"),
        ("?mode=local", "local"),
        ("", "local"),
        ("?mode=unknown", "local"),
        ("?mode=__proto__&profile=default&model=untrusted&tenant_id=other", "local"),
    ],
)
def test_url_preselects_only_existing_modes_without_submitting_a_question(
    search: str, expected_mode: str
) -> None:
    state = configured_state()
    state.update(samples=["Revenue?", "Orders?", "Average?", "Returns?"], metrics=[])
    result = render({"state": state, "startup": True, "search": search})
    assert result["selected_mode"] == expected_mode
    assert result["ask_disabled"]  # Explicit user submission still requires a question.
    if expected_mode == "live":
        assert result["dataset"] == "retail-v1"
        assert result["execution-state"] == "AWS AgentCore · enter a question"
        assert "reviewed.model" in result["target-details"]
    elif expected_mode == "local":
        assert "no Bedrock model or deployed target" in result["target-details"]
