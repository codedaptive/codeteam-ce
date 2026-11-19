// agents: the subagents of the cursor session (scope "session"), of every visible session in the cursor's team
// ("team") or of every visible session ("all"); render._agents, which has no team scope. Running agents come first,
// in start order, then finished ones from the last FINISHED_S, the last to finish first. With both groups shown, each
// opens with a label row, and finished rows are dimmed (.done). Each row is a grid (panels.css) of state glyph, number
// and description (depth is leading spaces, which the page collapses), a swimlane from start to last write on one time axis of at
// most AXIS_S, elapsed m:ss, one tags cell holding every badge (empty with none) and, in the team and all scopes,
// the owning session. The section carries has-tags when a shown agent has a badge, so the tags track has a width
// only then, and owners in the team and all scopes for the owner track. Expanded adds type, tokens and time since
// the last write. Empty with no agents.
import { fmt } from "./fmt.js";
import { h } from "./h.js";

// The time axis reaches back no further than the collector's window (collect.read_subagents' max_age_s, 6 h): no
// agent silent longer is sent, but one resumed after a long pause keeps its first start, and on 11-16 two acme leads
// started 74 h and 65 h ago pressed every other lane into the axis's last twelfth. A start before the axis draws
// from its left edge; elapsed stays the agent's whole time.
const AXIS_S = 6 * 3600;
// A finished agent shows for FINISHED_S after its last write (3 hours, to keep the
// list short; the collector sends 6 h, and keeps finished agents for the waits-on-a-finished-child
// flag). A running agent shows for the collector's whole window, so a silent one keeps its stalled badge.
const FINISHED_S = 3 * 3600;

// Running, or finished within FINISHED_S (or with no last write to tell by).
function shows(a, now) {
  const last = fmt.num(a.last_write);
  return !a.finished || last === null || now - last <= FINISHED_S;
}

// An agent's badges as [text, colour words], in row order.
function badges(a, now) {
  const f = a.flags || {};
  const last = fmt.num(a.last_write);
  return [
    f.stalled && [`stalled ${last === null ? "?" : fmt.dur(now - last)}`, "salmon chipped"],
    f.waiting_on_finished_child && ["waits on finished child", "salmon chipped"],
    f.orphan && ["orphan", "amber chipped"],
  ].filter(Boolean);
}

// The one tags cell: every badge, cut by its track, with all their text on hover.
function tags(list) {
  const title = list.length ? ` title="${h.esc(list.map(([text]) => text).join(" · "))}"` : "";
  return `<span class="tags"${title}>${list.map(([text, words]) => h.span(text, words)).join(" ")}</span>`;
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

function agentRow(s, a, i, t0, now, owners, motion) {
  const f = a.flags || {};
  const [glyph, colour] = a.finished ? ["✓", "green"] : f.stalled ? ["■", "salmon"] : ["●", "blue"];
  const indent = "  ".repeat(Math.max(0, Math.trunc(fmt.num(a.depth) || 1) - 1));
  const start = fmt.num(a.started);
  const end = a.finished ? fmt.num(a.last_write) : now;
  const elapsed = end !== null && start !== null ? fmt.timer(end - start) : "?";
  return h.row(h.span(glyph, colour) + " " + h.cut(`${indent}${i}: ${a.description || a.type || "?"}`, "", "label")
    + lane(a, t0, now, colour, motion && glyph === "●") + `<span class="num c-dim">${h.esc(elapsed)}</span>`
    + tags(badges(a, now)) + (owners ? h.cut(s.name || "?", "dim", "owner") : ""), a.finished ? "arow done" : "arow");
}

// The sessions a scope shows: the cursor's, every one in the cursor's team, or all of vis.
function shown(vis, cursor, scope) {
  const current = vis[cursor];
  if (scope === "all") return vis;
  if (!current) return [];
  const team = (current.team || {}).name;
  return scope === "team" ? vis.filter((v) => (v.team || {}).name === team) : [current];
}

const SCOPE_NOTE = { all: () => " · all sessions", team: (v) => ` · team ${(v?.team || {}).name || "?"}` };

const groupHead = (text, n, words) => h.row(h.span(text, words) + h.span(` · ${n}`, "dim"), "agroup");

// The head row: running and total counts, then the scope's note (none for one session).
function heading(running, total, note) {
  return h.row(h.span("agents", "bold") + h.dot() + h.span(`${running} running`, "green bold")
    + h.span(` · ${total} total`, "bold") + (note ? h.span(note, "dim") : "")
    + '<span class="c-faint push">⏎ expand</span>', "ahead");
}

// Expanded: type, tokens and time since the last write.
function detail(a, now) {
  const last = fmt.num(a.last_write);
  return h.row(h.span(`${a.type || "?"} · ${fmt.count(a.tokens)} tokens · last write `
    + `${last === null ? "?" : fmt.dur(now - last)} ago`, "dim"), "detail");
}

export function agents(vis, now, cursor, scope, expanded, motion) {
  const pairs = shown(vis, cursor, scope).flatMap((v) => fmt.dicts(v.session.agents).map((a) => [v.session, a]))
    .filter(([, a]) => shows(a, now))
    .sort(([, a], [, b]) => (fmt.num(a.started) || 0) - (fmt.num(b.started) || 0));
  if (!pairs.length) return "";
  const live = pairs.filter(([, a]) => !a.finished);
  const done = pairs.filter(([, a]) => a.finished)
    .sort(([, a], [, b]) => (fmt.num(b.last_write) || 0) - (fmt.num(a.last_write) || 0));
  const owners = Object.hasOwn(SCOPE_NOTE, scope);
  const starts = pairs.map(([, a]) => fmt.num(a.started)).filter((x) => x !== null);
  const t0 = starts.length ? Math.max(Math.min(...starts), now - AXIS_S) : now;
  const rows = [...live, ...done].map(([s, a], i) =>
    agentRow(s, a, i + 1, t0, now, owners, motion) + (expanded ? detail(a, now) : ""));
  if (live.length && done.length) {
    rows.splice(live.length, 0, groupHead("finished", done.length, "dim bold"));
    rows.unshift(groupHead("running", live.length, "blue bold"));
  }
  const extra = (pairs.some(([, a]) => badges(a, now).length) ? " has-tags" : "") + (owners ? " owners" : "");
  const head = heading(live.length, pairs.length, owners ? SCOPE_NOTE[scope](vis[cursor]) : "");
  return `<section class="agents${extra}" data-panel="agents">${head}${rows.join("")}</section>`;
}
