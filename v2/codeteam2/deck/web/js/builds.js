// BUILDS · queue (render._build_box): the job strip (running green, queued grey), the counts, the runner's budget
// and swap, each team's running and waiting jobs (a live runner with teams only), class chips, the jobs, the 24 h
// waits and the warms. Empty when the queue has nothing to show. In a middle column at least WIDE px wide with jobs
// queued, the body is two columns: everything but the queued jobs on the left, the queued jobs #1..#n on the right.
// Narrower (or no width given, or nothing queued), one column with the queued jobs after the running ones.
import { buildJobs } from "./buildJobs.js";
import { fmt } from "./fmt.js";
import { h } from "./h.js";
import { rowsOf } from "./rowsOf.js";
import { teamsRow } from "./teamsRow.js";

// Worktree tails in the warm rows are capped as render.PATH_CAP.
const PATH_CAP = 14;
// Two columns from a middle column this wide: panels.css's 390px left track, its 16px gap and a right track of at
// least 390px (796px) fit in an 820px column less the box's 18px of border and padding.
const WIDE = 820;

function runnerLine(runner) {
  if (runner.state !== "live") {
    const beat = runner.state === "stale" ? ` (last beat ${fmt.dur(runner.beat_age_s)} ago)` : "";
    return h.span(`no live runner${beat}`, "amber");
  }
  const used = fmt.num(runner.used);
  const budget = fmt.num(runner.budget);
  const swap = fmt.num(runner.swap);
  const line = h.span("budget", "dim") + " " + h.bar(used, budget, "green") + " "
    + h.span(`${fmt.g(used === null ? null : Math.floor(used + 0.5))}/${fmt.g(budget)}`, "bold") + h.span("   swap", "dim") + " ";
  if (swap === null) return line + h.span("?", "amber");
  return line + h.bar(swap, 1, runner.swap_hold === true ? "salmon" : "green") + " " + h.span(`${(swap * 100).toFixed(0)}%`, "dim");
}

function chip(c) {
  const ceiling = c.ceiling === 0 ? "∞" : fmt.g(c.ceiling);
  return `<span class="chipline">${h.span(c.class || "?", "teal bold")} ${h.span(`${fmt.dicts(c.running).length}/${ceiling}`, "dim")}</span>`;
}

function waits(c) {
  const w = fmt.mapping(c.waits);
  return (fmt.num(w.n) || 0) > 0 ? h.row(h.span(`waits ${fmt.g(w.window_h)}h · ${c.class || "?"} · ${fmt.g(w.n)} · `
    + `med ${fmt.dur(w.median_s)} · max ${fmt.dur(w.max_s)}`, "dim")) : "";
}

// The two columns side by side; data-rows is the taller column's rows, which rowsOf counts for the split.
function split(left, right) {
  return `<div class="split" data-rows="${Math.max(rowsOf(left), rowsOf(right))}">`
    + `<div class="split-l">${left}</div><div class="split-r">${right}</div></div>`;
}

export function builds(snapBuilds, motion, width) {
  const b = fmt.mapping(snapBuilds);
  const queue = fmt.mapping(b.queue);
  const runner = fmt.mapping(queue.runner);
  const classes = fmt.dicts(queue.classes);
  const running = classes.flatMap((c) => fmt.dicts(c.running));
  const queued = classes.flatMap((c) => fmt.dicts(c.queued));
  const warms = fmt.dicts(b.warms);
  const active = classes.some((c) => (fmt.num(fmt.mapping(c.waits).n) || 0) > 0);
  if (!(running.length || queued.length || active || runner.state === "live" || warms.length)) return "";
  const sweep = motion && running.length ? " sweep" : "";
  const strip = running.map(() => `<i class="bg-green${sweep}"></i>`).join("") + queued.map(() => '<i class="bg-faint"></i>').join("");
  const head = h.row(`<span class="strip">${strip}</span>`)
    + h.row(h.span("■", "green") + " " + h.span(`${running.length} running`, "green") + "   "
      + h.span("■", "dim") + " " + h.span(`${queued.length} queued`, "dim"))
    + h.row(runnerLine(runner)) + teamsRow(runner) + h.row(classes.map(chip).join(""), "chips");
  const tail = classes.map(waits).join("")
    + warms.map((w) => h.row(h.span(`warm ${w.state || "?"} ${fmt.dur(w.elapsed_s)} ${fmt.tail(w.worktree, PATH_CAP)}`, "dim"))).join("");
  const body = width >= WIDE && queued.length
    ? split(head + buildJobs(running, []) + tail, buildJobs([], queued))
    : head + buildJobs(running, queued) + tail;
  const right = h.span(`${running.length + queued.length} jobs`, "dim") + (queue.state === "?" ? h.span(" · queue ?", "amber") : "");
  return h.box(h.span("BUILDS · queue", "green bold"), right, body, "green", "builds");
}
