// agents: the cursor session's subagents, or every visible session's with allAgents (render._agents). Each row:
// state glyph, number and description indented by depth, a swimlane from start to last write on one time axis,
// elapsed m:ss and badges. Expanded adds type, tokens and time since the last write. Empty with no agents.
import { fmt } from "./fmt.js";
import { h } from "./h.js";

function badges(a, now) {
  const f = a.flags || {};
  const last = fmt.num(a.last_write);
  return (f.stalled ? " " + h.span(`stalled ${last === null ? "?" : fmt.dur(now - last)}`, "salmon chipped") : "")
    + (f.waiting_on_finished_child ? " " + h.span("waits on finished child", "salmon chipped") : "")
    + (f.orphan ? " " + h.span("orphan", "amber chipped") : "");
}

function lane(a, t0, now, colour, flow) {
  const start = fmt.num(a.started);
  const last = fmt.num(a.last_write);
  if (start === null || last === null) return h.span("?", "amber");
  const span = Math.max(1, now - t0);
  const x0 = Math.max(0, Math.min(98, ((start - t0) / span) * 100));
  const x1 = Math.max(x0 + 2, Math.min(100, ((last - t0) / span) * 100));
  return `<span class="lane"><i class="bg-${colour} ${flow ? "flow" : ""}" style="left:${x0.toFixed(2)}%;`
    + `width:${(x1 - x0).toFixed(2)}%"></i></span>`;
}

function agentRow(s, a, i, t0, now, all, motion) {
  const f = a.flags || {};
  const [glyph, colour] = a.finished ? ["✓", "green"] : f.stalled ? ["■", "salmon"] : ["●", "blue"];
  const indent = "  ".repeat(Math.max(0, Math.trunc(fmt.num(a.depth) || 1) - 1));
  const start = fmt.num(a.started);
  const end = a.finished ? fmt.num(a.last_write) : now;
  const elapsed = end !== null && start !== null ? fmt.timer(end - start) : "?";
  return h.row(h.span(glyph, colour) + " " + h.cut(`${indent}${i}: ${a.description || a.type || "?"}`, "", "label")
    + lane(a, t0, now, colour, motion && glyph === "●") + `<span class="num c-dim">${h.esc(elapsed)}</span>`
    + badges(a, now) + (all ? " " + h.cut(s.name || "?", "dim", "owner") : ""), "arow");
}

export function agents(vis, now, cursor, all, expanded, motion) {
  const chosen = all ? vis : vis.slice(cursor, cursor + 1);
  const pairs = chosen.flatMap((v) => fmt.dicts(v.session.agents).map((a) => [v.session, a]))
    .sort(([, a], [, b]) => (fmt.num(a.started) || 0) - (fmt.num(b.started) || 0));
  if (!pairs.length) return "";
  const running = pairs.filter(([, a]) => !a.finished).length;
  const head = h.span("agents", "bold") + h.dot() + h.span(`${running} running`, "green bold")
    + h.span(` · ${pairs.length} total`, "bold") + (all ? h.span(" · all sessions", "dim") : "");
  const starts = pairs.map(([, a]) => fmt.num(a.started)).filter((x) => x !== null);
  const t0 = starts.length ? Math.min(...starts) : now;
  const rows = pairs.map(([s, a], i) => {
    const last = fmt.num(a.last_write);
    const more = expanded ? h.row(h.span(`${a.type || "?"} · ${fmt.count(a.tokens)} tokens · last write `
      + `${last === null ? "?" : fmt.dur(now - last)} ago`, "dim"), "detail") : "";
    return agentRow(s, a, i + 1, t0, now, all, motion) + more;
  });
  return `<section class="agents" data-panel="agents">${h.row(head + '<span class="c-faint push">⏎ expand</span>', "ahead")}${rows.join("")}</section>`;
}
