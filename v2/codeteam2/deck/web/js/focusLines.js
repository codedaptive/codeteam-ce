// The focus box's lower lines (render._cache, _tools, _turns, _mail, _detail): cache, tool trace, per-turn output,
// mail, and the expanded detail. Returns the rows' markup.
import { fmt } from "./fmt.js";
import { h } from "./h.js";
import { spark } from "./spark.js";

// The turns trace keeps the newest 43 turns, as render._turns does in the focus box's 49-cell body less `turns `
// (render._turns gives way further to a turns-left tail; the page keeps 43 either way).
const TURNS_SHOWN = 43;

function cache(s) {
  const c = s.cache || {};
  if (c.warm === null || c.warm === undefined) return h.span("cache ?", "amber");
  if (!c.warm) return h.span("cache", "dim") + " " + h.span("◇ cold", "dim");
  const hit = fmt.num(c.hit_ratio);
  return h.span("cache", "dim") + " " + h.span("◆ warm", "purple")
    + h.span(` ${fmt.dur(c.expires_in_s)} left · hit ${hit === null ? "?" : (hit * 100).toFixed(0)}%`, "dim");
}

function tools(s) {
  const recent = s.recent || {};
  const names = Array.isArray(recent.trace) ? recent.trace.map((n) => String(n).toLowerCase())
    : fmt.dicts(recent.tools).map((t) => String(t.name || "?").toLowerCase());
  if (!names.length) return h.span("tools –", "dim");
  // Cut from the left in CSS, so the newest calls stay in view; the whole trace is on hover.
  return h.span("tools", "dim") + " " + h.cut(names.join(" → "), "", "lead");
}

function turns(s) {
  const left = fmt.num(s.turns_left);
  const tail = left === null ? "" : " " + h.span(`~${left.toFixed(0)} turns left`,
    left > 30 ? "green" : left > 15 ? "amber" : left > 5 ? "orange" : "salmon");
  if (!Array.isArray(s.turns)) return h.span("turns", "dim") + " " + h.span("?", "amber") + tail;
  const shown = s.turns.filter((x) => fmt.num(x) !== null || (x && typeof x === "object" && x.compacted)).slice(-TURNS_SHOWN);
  if (!shown.length) return h.span("turns –", "dim") + tail;
  return h.span("turns", "dim") + " " + spark(shown, "output tokens per turn") + tail;
}

function mail(s) {
  const m = s.mail || {};
  const [waiting, broadcasts] = fmt.mailCounts(m);
  const oldest = fmt.mailAge(m);
  const parts = [h.span(`✉ ${fmt.g(waiting)}`, waiting ? "amber" : "dim") + " " + h.span("waiting", "dim")];
  if (broadcasts !== null) parts.push(h.span(`◎ ${fmt.g(broadcasts)} broadcasts`, "dim"));
  parts.push(h.span(`↓${fmt.g(m.delivered_today)} today`, "dim"),
    h.span(`oldest ${oldest === null || oldest === undefined ? "–" : fmt.dur(oldest)}`, "dim"));
  if (m.held) parts.push(h.span(`held ${fmt.g(m.held)}`, "salmon bold"));
  return h.span("mail", "dim") + " " + parts.join(h.dot());
}

function detail(s) {
  const recent = s.recent || {};
  const rows = fmt.dicts(recent.tools).slice(0, 5).map((t) => h.cut(`tool ${t.name || "?"} ${t.summary || ""}`, "dim"));
  for (const m of fmt.dicts(recent.messages).slice(0, 5)) {
    rows.push(h.cut(`msg ${m.dir === "in" ? "←" : "→"} ${fmt.clock(m.ts)} ${m.peer || "?"} ${m.kind || "?"} ${m.text || ""}`, "dim"));
  }
  return (rows.length ? rows : [h.span("nothing recent", "dim")]).map((r) => h.row(r, "detail")).join("");
}

export function focusLines(s, expanded) {
  const lines = [cache(s), tools(s), turns(s)].map((r) => h.row(r)).join("") + h.row(mail(s), "wrap");
  return lines + (expanded ? detail(s) : "");
}
