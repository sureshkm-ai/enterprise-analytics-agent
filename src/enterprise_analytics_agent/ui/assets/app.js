"use strict";

const $ = (id) => document.getElementById(id);
const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
};
// Small, safe Markdown vocabulary: no HTML, URLs, scripts or numeric conversion.
function inlineText(parent, text) {
  let plain = "";
  const flush = () => { if (plain) parent.append(element("span", "", plain)); plain = ""; };
  for (let i = 0; i < text.length;) {
    if (text[i] === "\\" && i + 1 < text.length) { plain += text[i + 1]; i += 2; continue; }
    const marker = text.startsWith("**", i) ? "**" : text[i] === "`" ? "`" : null;
    const end = marker ? text.indexOf(marker, i + marker.length) : -1;
    if (marker && end > i + marker.length) {
      flush(); parent.append(element(marker === "**" ? "strong" : "code", "", text.slice(i + marker.length, end)));
      i = end + marker.length;
    } else { plain += text[i]; i += 1; }
  }
  flush();
}
function readableContent(text) {
  const content = element("div", "readable-answer");
  const lines = String(text || "").split(/\r?\n/);
  const cells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map(cell => cell.trim());
  for (let i = 0; i < lines.length;) {
    if (!lines[i].trim()) { i += 1; continue; }
    const heading = lines[i].match(/^#{1,3}\s+(.+)$/);
    if (heading) { const node = element("h3"); inlineText(node, heading[1]); content.append(node); i += 1; continue; }
    if (lines[i].startsWith("|") && /^\|?\s*:?-{3,}/.test(lines[i + 1] || "")) {
      const scroll = element("div", "table-scroll"); const table = element("table");
      const head = element("thead"); const row = element("tr");
      cells(lines[i]).forEach(value => { const cell = element("th"); cell.setAttribute("scope", "col"); inlineText(cell, value); row.append(cell); });
      head.append(row); table.append(head); i += 2;
      const body = element("tbody");
      while (i < lines.length && lines[i].startsWith("|")) {
        const row = element("tr");
        cells(lines[i]).forEach(value => { const cell = element("td"); inlineText(cell, value); row.append(cell); });
        body.append(row); i += 1;
      }
      table.append(body); scroll.append(table); content.append(scroll); continue;
    }
    if (/^[-*] /.test(lines[i])) {
      const node = element("ul");
      while (i < lines.length && /^[-*] /.test(lines[i])) { const item = element("li"); inlineText(item, lines[i].slice(2)); node.append(item); i += 1; }
      content.append(node); continue;
    }
    const paragraph = element("p"); inlineText(paragraph, lines[i]); content.append(paragraph); i += 1;
  }
  return content;
}
let state = null;
let mode = "local";
let busy = false;
let modelKey = null;
let progressMessage = "";
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
function availableModels() {
  return (state?.model_options || []).filter(option => option.modes?.[mode]);
}
function selectedModel() {
  return availableModels().find(option => option.key === modelKey);
}
function activeConfig() {
  return selectedModel()?.modes[mode] || state?.[mode];
}
function modelPicker() {
  const picker = $("model-choice");
  const options = mode === "local" ? [] : availableModels();
  if (mode !== "local" && !options.some(option => option.key === modelKey)) modelKey = options.find(option => option.modes[mode].enabled && !option.modes[mode].budget?.blocked)?.key || options[0]?.key || null;
  picker.replaceChildren();
  if (!options.length) {
    const option = element("option", "", mode === "local" ? "No model · deterministic planner" : "No reviewed model configured");
    option.value = "";
    picker.append(option);
  } else {
    options.forEach(item => {
      const config = item.modes[mode];
      const status = config.availability_label ? ` · ${config.availability_label}` : config.enabled && !config.budget?.blocked ? (config.acceptance_status === "testing" ? " · Testing" : "") : " · Unavailable";
      const option = element("option", "", item.label + status);
      option.value = item.key;
      picker.append(option);
    });
    picker.value = modelKey;
  }
  if (mode !== "local") {
    const pending = (state?.proposed_models || []).filter(item => !options.some(active => active.key === item.key));
    if (pending.length) {
      const group = element("optgroup"); group.label = "Catalog models · not enabled in this workspace";
      pending.forEach(item => {
        const option = element("option", "", `${item.provider} · ${item.label}`);
        option.value = item.key; option.disabled = true; option.title = item.note;
        group.append(option);
      });
      picker.append(group);
    }
  }
  picker.disabled = busy || !options.length;
  $("model-help").textContent = mode === "local"
    ? "The offline playground uses its deterministic planner, with no model calls."
    : options.length > 1
      ? "Choose a server-configured model. Each choice keeps its reviewed release and allowance."
      : options.length === 1
        ? "One server-configured model is bound. Availability and allowance are shown below."
        : "No agent model is configured in this workspace. The offline playground does not use Bedrock.";
  $("model-identifier").textContent = selectedModel()?.model_id || "";
  if (activeConfig()?.acceptance_status === "testing") $("model-help").textContent = "Model testing · uses the approved allowance. This model has not passed full acceptance. A failed model is isolated; other models remain available.";
}
function modeAvailability(value) {
  if (value === "local") return "DuckDB · no model calls";
  if (!state) return "Checking availability…";
  const configs = (state.model_options || []).map(option => option.modes?.[value]).filter(Boolean);
  if (!configs.length) return "Not configured";
  if (configs.every(config => config.budget?.blocked)) return "Allowance blocked";
  if (!configs.some(config => config.enabled && !config.budget?.blocked)) return "Unavailable";
  return `${configs.filter(config => config.enabled && !config.budget?.blocked).length} model(s) · billable`;
}
function ready() {
  const config = activeConfig();
  const blocked = mode !== "local" && (!config?.enabled || config.budget?.blocked);
  $("ask-button").disabled = busy || !state || blocked || !$("question").value.trim();
  $("question").disabled = busy;
  ["local", "local_agent", "live"].forEach(value => {
    $(`mode-${value}`).disabled = busy;
    $(`mode-${value}-status`).textContent = modeAvailability(value);
  });
  $("model-choice").disabled = busy || mode === "local" || !availableModels().length;
  $("ask-button").textContent = busy ? "Running…" : mode === "live" ? "Ask AWS" : mode === "local_agent" ? "Ask Bedrock" : "Run offline question";
  let status;
  if (busy) status = progressMessage || "Submitting your question…";
  else if (!state) status = "Loading workspace availability…";
  else if (mode !== "local" && config?.budget?.blocked) status = `${modeNames[mode]} blocked · allowance unavailable`;
  else if (mode !== "local" && config?.error) status = `${modeNames[mode]} unavailable · inspect the message above`;
  else if (mode !== "local" && !config?.enabled) status = selectedModel() || config?.configured
    ? `${modeNames[mode]} unavailable · target is disabled`
    : `${modeNames[mode]} is not configured`;
  else if ($("ask-button").disabled) status = `${modeNames[mode]} · enter a question`;
  else status = mode === "local" ? "Offline question ready · no model calls" : `${modeNames[mode]} question ready · billable`;
  $("execution-state").textContent = status;
}
function selectMode(next) {
  if (busy || !state) return;
  mode = next;
  ["local", "local_agent", "live"].forEach(value => {
    $(`mode-${value}`).classList.toggle("selected", mode === value);
    $(`mode-${value}`).setAttribute("aria-pressed", String(mode === value));
  });
  modelPicker();
  updateContext();
  $("answer").hidden = true;
  $("welcome").hidden = false;
  ready();
}
function updateContext() {
  const config = activeConfig() || {};
  const configured = mode === "local" || config.configured === true || (config.configured !== false && Boolean(selectedModel()));
  $("dataset").textContent = configured ? config.dataset || "Not reported" : "Not configured";
  $("reference-date").textContent = configured ? config.reference_date || "Not reported" : "—";
  $("target-details").textContent = mode === "local"
    ? "Deterministic local planner · no Bedrock model or deployed target"
    : !configured
      ? "No agent target is bound to this workspace. Switching modes does not enable AWS execution."
      : `${selectedModel()?.model_id || config.model_id || "Model not reported"}${config.runtime_version ? ` · Bound Runtime version: v${config.runtime_version}` : ""}`;
  $("usage-label").textContent = mode === "local" ? "MODEL CALLS" : "SHARED QUESTION ALLOWANCE";
  $("usage").textContent = usage(config);
  $("source-description").textContent = configured ? config.description || modeNames[mode] : `${modeNames[mode]} · not configured in this workspace`;
  const available = Boolean(config.enabled && !config.budget?.blocked);
  $("composer-hint").textContent = mode === "local" ? "Offline sample data · no model or AWS calls" : !configured ? "No agent connection · submissions disabled" : !available ? "Configured target unavailable · submissions disabled" : mode === "local_agent" ? "Local DuckDB + BILLABLE Bedrock · no automatic retries" : "BILLABLE AgentCore + Bedrock + Athena · no automatic retries";
  $("cost-notice").textContent = mode !== "local" && !available
    ? "No live question can be submitted. No model or Runtime call will be made."
    : config.cost_notice || (mode === "local" ? "No model or AWS calls." : "Billable model execution · no automatic retries.");
  $("cost-notice").classList.toggle("billable", mode !== "local" && available);
  $("live-notice").hidden = mode === "local" || (available && !config.notice);
  if (!configured) {
    $("live-notice-title").textContent = `${modeNames[mode]} is not connected to this workbench`;
    $("live-notice-body").textContent = "This page has no live model connection. Open the workbench with its accepted Runtime configuration; changing tabs does not connect it.";
  } else if (available && config.notice) {
    $("live-notice-title").textContent = "Model ready · previous request failed";
    $("live-notice-body").textContent = config.notice;
  } else if (config.budget?.blocked) {
    $("live-notice-title").textContent = `${modeNames[mode]} question allowance is unavailable`;
    $("live-notice-body").textContent = config.error || "This configured target cannot submit questions because its existing allowance is exhausted, expired or needs inspection. Inspect its recorded status before another submission.";
  } else {
    $("live-notice-title").textContent = `${modeNames[mode]} is paused`;
    $("live-notice-body").textContent = config.error || "This configured target has been disabled. Its existing configuration and question history are preserved; inspect the recorded status before another submission.";
  }
  if (mode !== "local" && config.error) message(config.error);
  else if (mode !== "local" && config.budget?.blocked) message("This shared allowance is exhausted, expired or needs inspection. See docs/ui-shared-code-live.md.");
  else message("");
}
async function post(path, data) {
  const response = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json", "X-UI-Token":state.token}, body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "The request could not be completed.");
  return value;
}
function beginProgress(question, selectedMode) {
  $("welcome").hidden = true;
  $("answer").hidden = false;
  const shell = element("div", "answer-shell streaming-answer");
  const header = element("div", "answer-heading");
  const streamKind = element("span", "stream-label", "LIVE PROGRESS"); streamKind.id = "stream-kind";
  header.append(element("span", `badge ${selectedMode}`, modeNames[selectedMode]), streamKind);
  if (selectedModel()) header.append(element("span", "small", selectedModel().label));
  shell.append(header, element("h2", "answer-title", question));
  shell.append(element("p", "answer-description", "Progress updates arrive while your question runs. Exact answers appear after validation."));
  const status = element("div", "stream-status");
  status.id = "stream-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.setAttribute("aria-atomic", "true");
  status.append(element("span", "status-dot"), element("span", "", "Submitting your question…"));
  const elapsed = element("span", "stream-elapsed", "0.0 s");
  elapsed.id = "stream-elapsed";
  const timeline = element("ol", "stream-timeline");
  timeline.id = "stream-timeline";
  const words = element("div", "answer-description streamed-answer");
  words.id = "stream-answer";
  words.hidden = true;
  words.setAttribute("aria-live", "polite");
  shell.append(status, elapsed, timeline, words);
  $("answer").replaceChildren(shell);
}
function showProgress(event) {
  if (typeof event.message !== "string" || !Number.isFinite(event.elapsed_ms) || event.elapsed_ms < 0) {
    throw new Error("The progress stream was invalid. No automatic retry was sent.");
  }
  const changed = event.message !== progressMessage;
  progressMessage = event.message;
  $("execution-state").textContent = progressMessage;
  const status = $("stream-status");
  if (changed) status.replaceChildren(element("span", "status-dot"), element("span", "", progressMessage));
  $("stream-elapsed").textContent = `${(event.elapsed_ms / 1000).toFixed(1)} s`;
  if (changed) {
    const timeline = $("stream-timeline");
    timeline.append(element("li", "", progressMessage));
    while (timeline.children.length > 8) timeline.firstElementChild.remove();
  }
}
async function streamedQuestion(data) {
  const response = await fetch("/api/ask/stream", {
    method:"POST",
    headers:{"Content-Type":"application/json", "X-UI-Token":state.token, "Accept":"application/x-ndjson"},
    body:JSON.stringify(data)
  });
  if (!response.ok) {
    const value = await response.json();
    throw new Error(value.error || "The question could not be started.");
  }
  if (!response.body || !response.headers.get("Content-Type")?.startsWith("application/x-ndjson")) {
    throw new Error("The server did not provide a progress stream. No automatic retry was sent.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", {fatal:true});
  let buffer = "";
  let result = null;
  let terminal = false;
  let streamedText = "";
  function record(line) {
    if (!line.trim()) return;
    if (terminal) throw new Error("The server sent output after the final response.");
    const event = JSON.parse(line);
    if (!event || typeof event !== "object") throw new Error("The server sent an invalid progress record. No automatic retry was sent.");
    if (event.type === "status") {
      if (!streamedText) showProgress(event);
      else if (Number.isFinite(event.elapsed_ms)) $("stream-elapsed").textContent = `${(event.elapsed_ms / 1000).toFixed(1)} s`;
    }
    else if (event.type === "answer_delta") {
      if (event.source !== "bedrock" || event.validated !== true || typeof event.text !== "string" || streamedText.length + event.text.length > 262144) {
        throw new Error("The validated word stream was invalid. No automatic retry was sent.");
      }
      streamedText += event.text;
      const words = $("stream-answer");
      words.hidden = false;
      words.replaceChildren(readableContent(streamedText));
      $("stream-kind").textContent = "STREAMING VERIFIED ANSWER";
      $("stream-status").textContent = "Receiving Bedrock words checked against the verified answer…";
    }
    else if (event.type === "result" && event.result?.response) {
      if (streamedText && !event.result.response.answer.startsWith(streamedText) && !event.result.display_answer?.startsWith(streamedText)) {
        throw new Error("The streamed text differs from the verified answer. Inspect the run before another request.");
      }
      result = event.result;
      terminal = true;
    } else if (event.type === "error" && typeof event.error === "string") {
      terminal = true;
      throw new Error(event.error);
    } else throw new Error("The server sent an invalid progress record. No automatic retry was sent.");
  }
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream:true});
      if (buffer.length > 16 * 1024 * 1024) throw new Error("The progress record exceeded the browser limit.");
      let newline;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        record(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
      if (done) break;
    }
    if (buffer.trim()) record(buffer);
    if (!terminal || !result) throw new Error("The stream ended without a complete answer. A billable question may still be running; inspect the ledger before another request. No automatic retry was sent.");
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
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
  const answerModel = (state.model_options || []).find(option => option.model_id === response.diagnostics.model_id);
  if (answerModel) heading.append(element("span", "small", answerModel.label));
  if (response.status !== "answer") heading.append(element("span", `badge ${response.status}`, response.status.toUpperCase()));
  if (caseStatus) heading.append(element("span", "small", `Recorded verdict: ${caseStatus}`));
  if (result.presentation_status === "streamed") heading.append(element("span", "badge", "VERIFIED BEDROCK STREAM"));
  const download = element("button", "text-button", "Download JSON");
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(response, null, 2)], {type:"application/json"}));
    const link = element("a"); link.href = url; link.download = "analytics-response.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  heading.append(download);
  shell.append(heading, element("h2", "answer-title", question), readableContent(result.display_answer || response.answer));
  if (result.presentation_status === "fallback") shell.append(element("p", "small", "The model stream was unavailable or did not match. Showing the verified answer without another model call."));
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
  const details = element("details", "answer-details");
  details.append(element("summary", "", "Inspect data and execution details"), tabs, content);
  shell.append(details); container.append(shell); select("Results");
}
function addHistory(question, result) {
  history.unshift({question, result}); history.splice(8);
  $("history").replaceChildren();
  history.forEach(item => {
    const model = (state.model_options || []).find(option => option.model_id === item.result.response.diagnostics.model_id);
    const button = element("button", "", `${model?.label || modeNames[item.result.mode]} · ${item.question}`);
    button.addEventListener("click", () => { if (busy) return; $("welcome").hidden = true; $("answer").hidden = false; renderResult($("answer"), item.result, item.question); });
    $("history").append(button);
  });
}
async function ask(event) {
  event.preventDefault(); if (busy || $("ask-button").disabled) return;
  const question = $("question").value.trim(); const selectedMode = mode;
  const selectedKey = modelKey;
  $("question").value = "";
  busy = true; progressMessage = ""; message(""); ready();
  beginProgress(question, selectedMode);
  let requestError = "";
  try {
    const request = {question, mode:selectedMode, request_id:crypto.randomUUID()};
    if (selectedMode !== "local" && selectedKey) request.model_key = selectedKey;
    const result = await streamedQuestion(request);
    renderResult($("answer"), result, question); addHistory(question, result);
  } catch (error) {
    const text = error instanceof TypeError ? "Connection interrupted. A billable question may still be running; inspect the UI ledger before another live request. No automatic retry was sent." : error instanceof SyntaxError ? "The response stream was invalid. Inspect the UI ledger before another billable request. No automatic retry was sent." : error.message;
    requestError = text;
    message(text);
    const status = $("stream-status");
    if (status) { status.classList.add("failed"); status.textContent = "Question stopped. Inspect the message above before another submission."; }
  } finally {
    busy = false;
    try {
      const response = await fetch("/api/state");
      if (!response.ok) throw new Error("State refresh failed");
      const refreshed = await response.json();
      state.live = refreshed.live;
      state.local_agent = refreshed.local_agent;
      state.model_options = refreshed.model_options || [];
      modelPicker();
      updateContext();
    } catch (_) {
      if (state.live) state.live.enabled = false;
      if (state.local_agent) state.local_agent.enabled = false;
      (state.model_options || []).forEach(option => Object.values(option.modes).forEach(config => { config.enabled = false; }));
    }
    ready();
    if (requestError) message(requestError);
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
function initialMode() {
  const requested = new URLSearchParams(location.search).get("mode");
  return ["local", "local_agent", "live"].includes(requested) ? requested : "local";
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
    buildGuide(); selectMode(initialMode());
  } catch (error) { message(error.message); }
}
document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => showView(button.dataset.view)));
$("mode-local").addEventListener("click", () => selectMode("local"));
$("mode-live").addEventListener("click", () => selectMode("live"));
$("mode-local_agent").addEventListener("click", () => selectMode("local_agent"));
$("model-choice").addEventListener("change", () => {
  if (busy) return;
  modelKey = $("model-choice").value;
  modelPicker(); updateContext(); ready();
});
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
