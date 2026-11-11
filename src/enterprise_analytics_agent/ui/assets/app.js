"use strict";

const $ = (id) => document.getElementById(id);
const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
};
let state = null;
let mode = "local";
let busy = false;
const modeNames = {local:"Offline playground", local_agent:"Local Bedrock", live:"AWS AgentCore", replay:"Saved replay"};
let savedCases = [];
const history = [];
const viewNames = {playground:"Question playground", replay:"Saved runs", catalog:"Metric catalog", guide:"How it works"};

function message(text) { $("message").textContent = text || ""; $("message").hidden = !text; }
function showView(name) {
  if (busy) return;
  document.querySelectorAll(".view").forEach(node => { node.hidden = node.id !== `view-${name}`; });
  document.querySelectorAll("[data-view]").forEach(node => node.classList.toggle("active", node.dataset.view === name));
  $("breadcrumb").textContent = viewNames[name];
  message("");
}
function usage(config) {
  if (mode === "local") return "0 · deterministic planner";
  if (!config.budget) return "Not enabled";
  const sdk = config.budget.sdk_attempts;
  return `${config.budget.used} / ${config.budget.maximum} question attempts${config.budget.blocked ? " · blocked" : ""}` +
    (sdk ? ` · ${sdk.local_converse_attempts} direct model / ${sdk.agentcore_invocations} Runtime calls` : "");
}
function ready() {
  const config = state?.[mode];
  const blocked = mode !== "local" && (!config?.enabled || config.budget?.blocked);
  $("ask-button").disabled = busy || !state || blocked || !$("question").value.trim();
  $("question").disabled = busy;
  ["local", "local_agent", "live"].forEach(value => { $(`mode-${value}`).disabled = busy; });
  $("ask-button").textContent = busy ? "Running…" : mode === "live" ? "Ask AWS" : mode === "local_agent" ? "Ask Bedrock" : "Run offline question";
  $("execution-state").textContent = busy ? (mode === "local" ? "Calculating your answer…" : "Verifying release and requesting agent answer…") : "Ready for a question";
}
function selectMode(next) {
  if (busy || !state) return;
  mode = next;
  ["local", "local_agent", "live"].forEach(value => {
    $(`mode-${value}`).classList.toggle("selected", mode === value);
    $(`mode-${value}`).setAttribute("aria-pressed", String(mode === value));
  });
  const config = state[mode];
  $("dataset").textContent = config.dataset;
  $("reference-date").textContent = config.reference_date;
  $("usage-label").textContent = mode === "local" ? "MODEL CALLS" : "SHARED QUESTION ALLOWANCE";
  $("usage").textContent = usage(config);
  $("source-description").textContent = config.description;
  $("composer-hint").textContent = mode === "local" ? "Offline sample data · no model or AWS calls" : mode === "local_agent" ? "Local DuckDB + BILLABLE Bedrock · no automatic retries" : "BILLABLE AgentCore + Bedrock + Athena · no automatic retries";
  $("cost-notice").textContent = config.cost_notice;
  $("cost-notice").classList.toggle("billable", mode !== "local");
  $("live-notice").hidden = mode === "local" || config.enabled;
  if (mode !== "local" && config.error) message(config.error);
  else if (mode !== "local" && config.budget?.blocked) message("This shared allowance is exhausted, expired or needs inspection. See docs/ui-shared-code-live.md.");
  else message("");
  $("answer").hidden = true;
  $("welcome").hidden = false;
  ready();
}
async function post(path, data) {
  const response = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json", "X-UI-Token":state.token}, body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "The request could not be completed.");
  return value;
}
function labelFor(metric) { return state.metrics.find(item => item.metric_id === metric)?.display_name || metric; }
function formatValue(value) { return value === null ? "No value" : String(value); }
function facts(response, elapsed, unreported = []) {
  const row = element("div", "facts");
  const d = response.diagnostics;
  const work = key => unreported.includes(key) ? "Unreported" : (d[key] ?? "Unreported");
  [response.dataset_version, d.model_id,
   `${work("model_calls")} model calls`,
   `${work("input_tokens")} input / ${work("output_tokens")} output tokens`,
   elapsed === null ? "Run time unreported" : `${(elapsed / 1000).toFixed(3)} s run time`]
    .forEach(text => row.append(element("span", "", text)));
  return row;
}
function resultTable(result) {
  const wrapper = element("section", "metric-result");
  const caption = element("div", "metric-caption");
  caption.append(element("strong", "", labelFor(result.metric_id)), element("span", "", `${result.time_range.start} → ${result.time_range.end} exclusive · v${result.definition_version}`));
  wrapper.append(caption);
  if (!result.rows.length) { wrapper.append(element("p", "answer-description", "No rows match this question.")); return wrapper; }
  if (!result.group_by.length && result.rows.length === 1) {
    const number = element("div", "value-display", formatValue(result.rows[0].value));
    number.append(element("span", "", result.currency || (result.unit === "ratio" ? "fraction" : result.unit)));
    wrapper.append(number); return wrapper;
  }
  const scroll = element("div", "table-scroll");
  const table = element("table");
  const head = element("thead"); const tr = element("tr");
  [...result.group_by, result.currency ? `Value (${result.currency})` : `Value (${result.unit})`].forEach(value => tr.append(element("th", "", value)));
  head.append(tr); table.append(head);
  const body = element("tbody");
  result.rows.forEach(row => {
    const line = element("tr");
    result.group_by.forEach(key => line.append(element("td", "", row.dimensions[key] ?? "—")));
    line.append(element("td", "", formatValue(row.value))); body.append(line);
  });
  table.append(body); scroll.append(table); wrapper.append(scroll); return wrapper;
}
function metadataView(items) {
  const box = element("div");
  items.forEach(item => {
    const metrics = item.metrics || (item.metric ? [item.metric] : []);
    if (metrics.length) metrics.forEach(metric => box.append(metricCard(metric)));
    else box.append(element("pre", "", JSON.stringify(item, null, 2)));
  });
  return box;
}
function renderResult(container, result, question, caseStatus = null) {
  container.replaceChildren();
  const response = result.response;
  const shell = element("div", "answer-shell");
  const heading = element("div", "answer-heading");
  const names = {local:"OFFLINE · DUCKDB", local_agent:"LOCAL BEDROCK · DUCKDB", live:"AWS · AGENTCORE", replay:"SAVED · REPLAY"};
  heading.append(element("span", `badge ${result.mode}`, names[result.mode]));
  if (response.status !== "answer") heading.append(element("span", `badge ${response.status}`, response.status.toUpperCase()));
  if (caseStatus) heading.append(element("span", "small", `Recorded verdict: ${caseStatus}`));
  const download = element("button", "text-button", "Download JSON");
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(response, null, 2)], {type:"application/json"}));
    const link = element("a"); link.href = url; link.download = "analytics-response.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  heading.append(download);
  shell.append(heading, element("h2", "answer-title", question), element("p", "answer-description", response.answer));
  const tabs = element("div", "result-tabs"); const content = element("div", "result-body");
  const buttons = [];
  function select(tab) {
    buttons.forEach(node => node.classList.toggle("active", node.textContent === tab));
    content.replaceChildren();
    if (tab === "Results") {
      response.results.forEach(item => content.append(resultTable(item)));
      if (result.metadata?.length) content.append(metadataView(result.metadata));
      if (!response.results.length && !result.metadata?.length) content.append(element("p", "small", "This response contains no numeric result table. See the answer and execution details."));
    } else if (tab === "Execution") {
      content.append(facts(response, result.elapsed_ms, result.unreported_diagnostics));
      response.diagnostics.tool_calls?.forEach(tool => {
        const item = element("div", "tool-row");
        item.append(element("h4", "", `${tool.name} · ${tool.status}`), element("pre", "", JSON.stringify(tool.arguments, null, 2)));
        if (tool.error_code) item.append(element("p", "", tool.error_code)); content.append(item);
      });
      if (response.diagnostics.athena?.length) content.append(element("pre", "", JSON.stringify(response.diagnostics.athena, null, 2)));
    } else content.append(element("pre", "", JSON.stringify(response, null, 2)));
  }
  ["Results", "Execution", "JSON"].forEach(tab => { const button = element("button", "result-tab", tab); button.addEventListener("click", () => select(tab)); buttons.push(button); tabs.append(button); });
  shell.append(tabs, content); container.append(shell); select("Results");
}
function addHistory(question, result) {
  history.unshift({question, result}); history.splice(8);
  $("history").replaceChildren();
  history.forEach(item => {
    const button = element("button", "", `${modeNames[item.result.mode]} · ${item.question}`);
    button.addEventListener("click", () => { if (busy) return; $("welcome").hidden = true; $("answer").hidden = false; renderResult($("answer"), item.result, item.question); });
    $("history").append(button);
  });
}
async function ask(event) {
  event.preventDefault(); if (busy || $("ask-button").disabled) return;
  const question = $("question").value.trim(); const selectedMode = mode;
  busy = true; message(""); ready();
  try {
    const value = await post("/api/ask", {question, mode:selectedMode, request_id:crypto.randomUUID()});
    $("welcome").hidden = true; $("answer").hidden = false;
    renderResult($("answer"), value.result, question); addHistory(question, value.result);
  } catch (error) {
    message(error instanceof TypeError ? "Connection interrupted. A billable question may still be running; inspect the UI ledger before another live request. No automatic retry was sent." : error.message);
  } finally {
    busy = false;
    try {
      const response = await fetch("/api/state");
      if (!response.ok) throw new Error("State refresh failed");
      const refreshed = await response.json();
      state.live = refreshed.live;
      state.local_agent = refreshed.local_agent;
      $("usage").textContent = usage(state[mode]);
    } catch (_) {
      if (state.live) state.live.enabled = false;
      if (state.local_agent) state.local_agent.enabled = false;
    }
    ready();
  }
}
function metricCard(metric) {
  const card = element("article", "catalog-card");
  card.append(element("span", "badge local", metric.metric_id), element("h3", "", metric.display_name), element("p", "", metric.description));
  card.append(element("p", "rule", metric.calculation));
  card.append(element("p", "small", `Unit: ${metric.unit} · Definition: ${metric.definition_version} · Dimensions: ${(metric.dimensions || []).map(item => item.dimension_id).join(", ")}`));
  return card;
}
function loadReplay(report) {
  savedCases = report.cases; $("report-label").textContent = report.label;
  $("replay-empty").hidden = true; $("replay-content").hidden = false; $("saved-answer").replaceChildren();
  $("case-search").value = ""; filterCases();
  if (savedCases.length) openCase(savedCases[0]);
}
function openCase(item) {
  document.querySelectorAll(".case-button").forEach(button => button.classList.toggle("active", button.dataset.id === item.case_id));
  if (item.result) renderResult($("saved-answer"), item.result, item.question, item.status);
  else { $("saved-answer").replaceChildren(element("p", "answer-shell", `No recorded response. ${item.reasons.join(" ")}`)); }
}
function filterCases() {
  const search = $("case-search").value.toLowerCase(); $("case-list").replaceChildren();
  savedCases.filter(item => `${item.case_id} ${item.question}`.toLowerCase().includes(search)).forEach(item => {
    const button = element("button", "case-button"); button.dataset.id = item.case_id;
    button.append(element("strong", "", `${item.case_id} · ${item.status}`), element("span", "", item.question));
    button.addEventListener("click", () => openCase(item)); $("case-list").append(button);
  });
}
function buildGuide() {
  const steps = [
    ["Understand the business rules", "Metric definitions specify grains, joins, refunds, rounding and time boundaries.", "docs/metric-definitions.md · catalog.py"],
    ["Trace a typed semantic request", "Pydantic validates metric, period, grouping and filters. Trusted authorization is supplied separately.", "contracts_v2.py · adapter.py · agent/questions.py"],
    ["Follow the selected backend", "Offline playground uses a deterministic planner. Local Bedrock and AWS AgentCore use the same BedrockAnalyticsAgent with DuckDB or Athena, subject to verified source, release and canonical inputs.", "adapters/duckdb.py · adapters/bedrock_agent.py · adapters/athena.py"],
    ["Inspect execution and evidence", "The Execution tab shows validated tool arguments, model counters and available Athena diagnostics. Saved runs retain the original verdicts.", "agent/tools.py · retail_evaluation/judge.py · retail_evaluation/reporting.py"],
    ["Read the browser integration", "The UI serves only on loopback. Both billable modes share a new durable question allowance. Local Converse attempts and AgentCore invocations have separate SDK records; closed historical campaigns remain untouched.", "ui/server.py · ui/shared.py · adapters/ui_shared.py · adapters/ui_local_agent.py"]
  ];
  steps.forEach((step, index) => {
    const row = element("div", "code-step"); const body = element("div");
    body.append(element("h3", "", step[0]), element("p", "", step[1]), element("code", "", step[2]));
    row.append(element("span", "step-number", index + 1), body); $("code-map").append(row);
  });
}
async function start() {
  try {
    const response = await fetch("/api/state"); if (!response.ok) throw new Error("Cannot connect to the local application."); state = await response.json();
    const picks = [0, 1, 3]; const titles = ["Revenue", "Order volume", "Returns"];
    picks.forEach((index, position) => {
      const button = element("button", "suggestion");
      button.append(element("span", "", titles[position]), element("div", "", state.samples[index]));
      button.addEventListener("click", () => { if (busy) return; $("question").value = state.samples[index]; ready(); $("question").focus(); });
      $("suggestions").append(button);
    });
    state.metrics.forEach(metric => $("catalog").append(metricCard(metric)));
    if (state.replay) loadReplay(state.replay);
    buildGuide(); selectMode("local");
  } catch (error) { message(error.message); }
}
document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => showView(button.dataset.view)));
$("mode-local").addEventListener("click", () => selectMode("local"));
$("mode-live").addEventListener("click", () => selectMode("live"));
$("mode-local_agent").addEventListener("click", () => selectMode("local_agent"));
$("setup-guide").addEventListener("click", event => { event.preventDefault(); showView("guide"); });
$("question").addEventListener("input", ready);
$("question").addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") $("ask-form").requestSubmit(); });
$("ask-form").addEventListener("submit", ask);
$("clear").addEventListener("click", () => { if (busy) return; $("answer").hidden = true; $("welcome").hidden = false; $("question").value = ""; history.length = 0; $("history").replaceChildren(); message(""); ready(); });
$("case-search").addEventListener("input", filterCases);
$("report-file").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  try { if (file.size > 16 * 1024 * 1024) throw new Error("Choose a report smaller than 16 MiB."); loadReplay(await post("/api/replay", JSON.parse(await file.text()))); message(""); }
  catch (error) { message(error instanceof SyntaxError ? "This file is not valid JSON." : error.message); }
  finally { event.target.value = ""; }
});
start();
