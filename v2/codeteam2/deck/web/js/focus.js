// The focus box for the cursor's session (render._focus): model and name in the title, state and age in the
// caption; effort, role and team; context with tokens and compactions; session and seat cost; then focusLines
// and the flags. The detail is the newest tools then messages (up to 5 of each). In a narrow column it shows only
// when expanded (Enter, or a click on the selected row), above the flags row, in the snapshot's order as the
// terminal's render._detail. In a wide column the box is two columns: those rows on the left, the detail on the
// right with tools newest first, cut to the left's row count so the box grows no taller; expanded shows all of it.
import { flags } from "./flags.js";
import { focusLines } from "./focusLines.js";
import { fmt } from "./fmt.js";
import { h } from "./h.js";
import { roleColour } from "./roleColour.js";
import { sessionState } from "./sessionState.js";

const EFFORT = { low: 1, medium: 2, high: 3, xhigh: 4, max: 5 };

// The narrowest middle column (px) that fits two columns: the 410px left track, the 16px gap and a side of at least
// 240px (666px), plus the box's 18px of edge and padding. Below it the side would cut its rows to a few words.
const WIDE = 684;

function effort(s, t) {
  const word = s.effort || "?";
  const level = EFFORT[word] || 0;
  const steps = [1, 2, 3, 4, 5].map((i) => `<i class="${i <= level ? "bg-coral" : "bg-faint"}"></i>`).join("");
  return h.span("effort", "dim") + ` <span class="steps">${steps}</span> ` + h.span(word, "coral bold")
    + h.span("   role ", "dim") + h.span(s.role || "?", roleColour(s.role)) + h.span(` · ${t.name || "?"}`, "dim");
}

function context(s) {
  const ctx = s.context || {};
  const pct = fmt.num(ctx.used_pct);
  const win = fmt.num(ctx.window);
  const heat = fmt.ctxColour(pct);
  const tokens = pct === null || win === null ? "?" : ((win * pct) / 100000).toFixed(0);
  return h.span("ctx", "dim") + " " + h.bar(pct, 100, heat, "wide") + " " + h.span(`${fmt.g(pct)}%`, `${heat} bold`)
    + h.span(` ${tokens}k/${win === null ? "?" : (win / 1e6).toFixed(1)}M`, "dim") + " "
    + h.span(`⟲${fmt.g(ctx.compactions)}${ctx.compactions_partial ? "+" : ""}`, "dim");
}

function cost(s) {
  const c = s.cost || {};
  return h.span(fmt.usd(c.session_usd), "bold") + h.span(" session   ", "dim")
    + h.span(fmt.usd(c.seat_today_usd) + (c.seat_today_partial ? "+" : ""), "bold") + h.span(" seat today", "dim");
}

// The detail rows. With a budget of k rows, tools take at least half (rounded up) and any rows messages leave
// unused, messages the rest; without one, every row. The snapshot lists tools oldest first and messages newest
// first; newestFirst reverses the tools, so a budget keeps the newest of them.
function detail(s, k = null, newestFirst = false) {
  const recent = s.recent || {};
  const listed = fmt.dicts(recent.tools);
  const tools = (newestFirst ? listed.reverse() : listed).slice(0, 5);
  const msgs = fmt.dicts(recent.messages).slice(0, 5);
  const t = k === null ? tools.length : Math.min(tools.length, Math.max(Math.ceil(k / 2), k - msgs.length));
  const m = k === null ? msgs.length : Math.min(msgs.length, k - t);
  const rows = tools.slice(0, t).map((x) => h.cut(`tool ${x.name || "?"} ${x.summary || ""}`, "dim"))
    .concat(msgs.slice(0, m).map((x) =>
      h.cut(`msg ${x.dir === "in" ? "←" : "→"} ${fmt.clock(x.ts)} ${x.peer || "?"} ${x.kind || "?"} ${x.text || ""}`, "dim")));
  return (rows.length ? rows : [h.span("nothing recent", "dim")]).map((r) => h.row(r, "detail"));
}

function split(left, right) {
  return `<div class="split" data-rows="${Math.max(left.length, right.length)}"><div class="split-l">${left.join("")}</div>`
    + `<div class="split-r">${right.join("")}</div></div>`;
}

export function focus(s, t, now, expanded, motion, width) {
  const [glyph, word, colour, age] = sessionState(s, now);
  const flagged = flags(s);
  const flagLine = h.span("flags", "dim") + " "
    + (flagged.length ? flagged.map(([text, words]) => h.span(text, words)).join(" ") : h.span("none", "dim"));
  const lines = [effort(s, t), context(s), cost(s)].map((r) => h.row(r)).concat(focusLines(s));
  const flagRow = h.row(flagLine, "wrap");
  const left = lines.concat(flagRow);
  const body = width >= WIDE ? split(left, detail(s, expanded ? null : left.length, true))
    : lines.concat(expanded ? detail(s) : [], flagRow).join("");
  const pulse = motion && word === "working" ? "pulse" : "";
  const right = `<span class="${h.cls(colour)} ${pulse}">${h.esc(`${glyph} ${word}`)}</span>` + h.span(` ${age}`, "dim");
  const title = h.cut(`${fmt.model(s)} · ${s.name || s.key || "?"}`, "coral bold");
  return h.box(title, right, body, "coral", "focus");
}
