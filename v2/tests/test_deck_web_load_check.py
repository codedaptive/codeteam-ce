"""The deck reports page-code failures while its initial placeholder is present."""
import json
import subprocess

from conftest import integration_only
from test_deck_web_page import Elements, JS, NODE, WEB, needs_node


MESSAGE = ("codeteam deck: the page's code did not load (a file is missing or stale); "
           "restart `codeteam2 deck --web` and reload.")
WAITING = "codeteam deck: waiting for the first snapshot…"


@integration_only
def test_index_loads_classic_check_before_main_module():
    elements = Elements((WEB / "index.html").read_text(encoding="utf-8")).found
    scripts = [el for el in elements if el["tag"] == "script"]
    checks = [el for el in scripts if el["attrs"].get("src") == "/js/loadCheck.js"]
    mains = [el for el in scripts if el["attrs"].get("src") == "/js/main.js"]
    assert len(checks) == len(mains) == 1
    assert checks[0]["attrs"].get("type", "").lower() != "module"
    assert mains[0]["attrs"].get("type") == "module"
    assert checks[0]["start"] < mains[0]["start"]


@integration_only
def test_load_check_contains_exact_recovery_message():
    assert MESSAGE in (JS / "loadCheck.js").read_text(encoding="utf-8")


def run_classic(event=None, waiting=True):
    source = (JS / "loadCheck.js").read_text(encoding="utf-8")
    script = r"""
const vm = require('node:vm');
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  const args = JSON.parse(input);
  const listeners = [];
  const selectors = [];
  const placeholder = args.waiting ? {textContent: args.initial} : null;
  const window = {
    addEventListener: (type, fn, capture) => listeners.push({type, fn, capture}),
    location: {href: 'http' + '://127.0.0.1:8770/'}
  };
  const document = {querySelector: selector => {
    selectors.push(selector);
    return selector === '#deck .waiting' ? placeholder : null;
  }};
  const context = vm.createContext({window, document, URL, location: window.location});
  vm.runInContext(args.source, context, {filename: 'loadCheck.js'});
  if (args.event !== null) {
    const listener = listeners.find(item => item.type === 'error');
    if (listener) listener.fn(args.event);
  }
  process.stdout.write(JSON.stringify({
    listeners: listeners.map(({type, capture}) => ({type, capture})),
    selectors,
    text: placeholder && placeholder.textContent
  }));
});
"""
    done = subprocess.run(
        [NODE, "-e", script],
        input=json.dumps({"source": source, "event": event, "waiting": waiting, "initial": WAITING}),
        capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@integration_only
@needs_node
def test_registers_one_capturing_window_error_listener():
    assert run_classic()["listeners"] == [{"type": "error", "capture": True}]


@integration_only
@needs_node
def test_script_resource_error_replaces_placeholder():
    result = run_classic({"target": {"tagName": "SCRIPT"}})
    assert "#deck .waiting" in result["selectors"]
    assert result["text"] == MESSAGE


@integration_only
@needs_node
def test_page_module_filename_error_replaces_placeholder():
    url = "http" + "://127.0.0.1:8770/js/teamsRow.js"
    result = run_classic({"filename": url})
    assert "#deck .waiting" in result["selectors"]
    assert result["text"] == MESSAGE


@integration_only
@needs_node
def test_link_resource_error_leaves_placeholder_unchanged():
    result = run_classic({"target": {"tagName": "LINK"}})
    assert result["text"] == WAITING
    assert result["listeners"] == [{"type": "error", "capture": True}]


@integration_only
@needs_node
def test_filename_outside_js_path_leaves_placeholder_unchanged():
    url = "http" + "://127.0.0.1:8770/other/teamsRow.js"
    result = run_classic({"filename": url})
    assert result["text"] == WAITING
    assert result["listeners"] == [{"type": "error", "capture": True}]


@integration_only
@needs_node
def test_script_error_after_placeholder_removed_does_not_throw():
    result = run_classic({"target": {"tagName": "SCRIPT"}}, waiting=False)
    assert "#deck .waiting" in result["selectors"]
    assert result["text"] is None
