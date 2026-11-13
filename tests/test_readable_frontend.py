"""Execute the shipped JavaScript: rendering and fragmented UTF-8 stream delivery."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from test_model_stream_ui import metric_answer

from enterprise_analytics_agent.agent.presentation import readable_answer

APP = Path(__file__).parents[1] / "src/enterprise_analytics_agent/ui/assets/app.js"
HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const scenario = JSON.parse(process.argv[2]), nodes = new Map();
class Node {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.textContent = ''; this.hidden = false;
    this.value = ''; this.dataset = {}; this.classList = {add(){},toggle(){}};
  }
  set id(value) { nodes.set(value, this); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  setAttribute() {} addEventListener() {}
}
const get = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
const snap = node => ({tag:node.tag, text:node.textContent, children:node.children.map(snap)});
const context = vm.createContext({
  document:{getElementById:get,createElement:tag=>new Node(tag),querySelectorAll:()=>[]},
  fetch:()=>new Promise(()=>{}), location:{search:''}, URLSearchParams, TextDecoder, console,
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.scenario = scenario;
async function run() {
  if (scenario.text !== undefined) {
    const output = vm.runInContext('readableContent(scenario.text)', context);
    console.log(JSON.stringify(snap(output))); return;
  }
  const data = Buffer.from(scenario.events.map(event=>JSON.stringify(event)+'\n').join(''));
  let offset = 0, calls = 0, partials = [], released = false;
  context.fetch = async () => { calls++; return {
    ok:true,headers:{get:()=> 'application/x-ndjson'},body:{getReader:()=>({
    async read() {
      partials.push(snap(get('stream-answer')));
      return offset < data.length
        ? {done:false,value:data.subarray(offset, ++offset)} : {done:true};
    },releaseLock(){released=true;},async cancel(){}
  })}}; };
  vm.runInContext('state = {token:"fixture"}; beginProgress("Revenue?", "live")', context);
  try {
    const result = await vm.runInContext(
      'streamedQuestion({question:"Revenue?",mode:"live"})', context);
    console.log(JSON.stringify({result,calls,released,partials,answer:snap(get('stream-answer')),kind:get('stream-kind').textContent}));
  } catch (error) { console.log(JSON.stringify({error:error.message,calls,released})); }
}
run().catch(error=>{console.error(error); process.exitCode=1;});
"""


def run(value: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "Node is required for the shipped JavaScript checks"
    result = subprocess.run(
        [node, "-e", HARNESS, str(APP), json.dumps(value)],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def flatten(value: dict[str, Any]) -> list[dict[str, Any]]:
    return [value, *[child for item in value["children"] for child in flatten(item)]]


def test_readable_markdown_has_tables_bold_and_literal_untrusted_html() -> None:
    output = run(
        {
            "text": "### Net revenue\n\nFor **March 31, 2025**:\n\n| Region | Value |\n"
            "| --- | --- |\n| North \\| South | 9007199254740993.01 USD |\n\n"
            "<script>alert('x')</script>\n<img src=x onerror=alert(1)>"
        }
    )
    nodes = flatten(output)
    assert sum(item["tag"] == "table" for item in nodes) == 1
    assert [item["text"] for item in nodes if item["tag"] == "strong"] == ["March 31, 2025"]
    assert not any(item["tag"] in {"script", "img", "a"} for item in nodes)
    assert any(item["text"] == "9007199254740993.01 USD" for item in nodes)
    assert any(item["text"] == "North | South" for item in nodes)


def test_actual_browser_parser_renders_partial_answer_before_final_without_retries() -> None:
    response = metric_answer()
    text = readable_answer(response)
    events = [{"type": "status", "message": "Verifying…", "elapsed_ms": 1}]
    events += [
        {"type": "answer_delta", "text": word, "source": "bedrock", "validated": True}
        for word in ("Net revenue: ", "**110.25 USD** ", "for **March 31, 2025**.")
    ]
    events += [
        {
            "type": "result",
            "result": {"response": response.model_dump(mode="json"), "display_answer": text},
        }
    ]
    output = run({"events": events})
    assert "error" not in output and output["calls"] == 1 and output["released"]
    assert any(
        any(node["text"] == "110.25 USD" for node in flatten(part)) for part in output["partials"]
    )
    assert output["kind"] == "STREAMING VERIFIED ANSWER"
    assert [node["text"] for node in flatten(output["answer"]) if node["tag"] == "strong"] == [
        "110.25 USD",
        "March 31, 2025",
    ]


def test_changed_final_cannot_replace_a_validated_stream() -> None:
    response = metric_answer()
    events = [
        {
            "type": "answer_delta",
            "text": "Unverified 9999.99",
            "source": "bedrock",
            "validated": True,
        },
        {
            "type": "result",
            "result": {
                "response": response.model_dump(mode="json"),
                "display_answer": readable_answer(response),
            },
        },
    ]
    result = run({"events": events})
    assert "differs" in result["error"] and result["calls"] == 1 and result["released"]
