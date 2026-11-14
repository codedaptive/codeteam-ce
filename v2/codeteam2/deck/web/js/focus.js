// The focus box for the cursor's session (render._focus): model and name in the title, state and age in the
// caption; effort, role and team; context with tokens and compactions; session and seat cost; then focusLines
// and the flags. Enter (or a click on the selected row) adds the detail.
import { flags } from "./flags.js";
import { focusLines } from "./focusLines.js";
import { fmt } from "./fmt.js";
import { h } from "./h.js";
import { roleColour } from "./roleColour.js";
import { sessionState } from "./sessionState.js";

const EFFORT = { low: 1, medium: 2, high: 3, xhigh: 4, max: 5 };

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

export function focus(s, t, now, expanded, motion) {
  const [glyph, word, colour, age] = sessionState(s, now);
  const flagged = flags(s);
  const flagLine = h.span("flags", "dim") + " "
    + (flagged.length ? flagged.map(([text, words]) => h.span(text, words)).join(" ") : h.span("none", "dim"));
  const body = [effort(s, t), context(s), cost(s)].map((r) => h.row(r)).join("") + focusLines(s, expanded) + h.row(flagLine, "wrap");
  const pulse = motion && word === "working" ? "pulse" : "";
  const right = `<span class="${h.cls(colour)} ${pulse}">${h.esc(`${glyph} ${word}`)}</span>` + h.span(` ${age}`, "dim");
  const title = h.cut(`${fmt.model(s)} · ${s.name || s.key || "?"}`, "coral bold");
  return h.box(title, right, body, "coral", "focus");
}
