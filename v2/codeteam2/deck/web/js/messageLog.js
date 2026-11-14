// log · <team>: the cursor team's last 10 messages and the top senders and recipients (render._messages). A message
// in flash (with motion) shows bold amber for a moment. Nothing for a v1 team; `messages ?` when unreadable.
import { fmt } from "./fmt.js";
import { h } from "./h.js";
import { roleColour } from "./roleColour.js";

const KIND = { REQUEST: "amber", ANSWER: "blue", DONE: "green", PUSHED: "green", READY: "teal", NOTE: "purple",
  BUG: "salmon", RULING: "coral" };

function line(x, roles, lit) {
  const sender = x.sender || "?";
  const recipient = x.recipient || "?";
  const kind = x.kind || "?";
  return `<div class="mrow${lit ? " flash" : ""}">` + h.span(fmt.clock(x.ts, true), "faint")
    + h.cut(sender, roles[sender] || "dim", "who") + h.span("→", "dim") + h.cut(recipient, roles[recipient] || "dim", "who")
    + h.span(kind, `${KIND[kind] || "dim"} bold`) + h.cut(x.text || "", "dim", "text") + "</div>";
}

function top(label, pairs) {
  const named = (pairs || []).slice(0, 5).map(([name, n]) => h.span(`${name} ${n}`, "dim"));
  return h.row(h.span(label, "dim") + " " + (named.length ? named.join("  ") : h.span("–", "dim")), "tops");
}

export function messageLog(t, flash, motion) {
  if (t.state === "v1") return "";
  const title = h.span("log · ", "dim") + h.span(t.name || "?", "bold");
  const m = t.messages;
  if (!m || typeof m !== "object") return h.box(title, "", h.row(h.span("messages ?", "amber")), "edge", "log");
  const roles = Object.fromEntries((t.sessions || []).map((s) => [s.name, roleColour(s.role)]));
  const lit = new Set(motion ? flash.filter(([team]) => team === t.name).map(([, id]) => id) : []);
  const rows = fmt.dicts(m.last).slice(0, 10).map((x) => line(x, roles, lit.has(x.id)));
  const right = h.span(`↓${fmt.g(m.delivered_today)} `, "dim") + h.span(`held ${fmt.g(m.held)}`, m.held ? "salmon" : "dim")
    + h.span(` queued ${fmt.g(m.queued)} bcast ${fmt.g(m.broadcasts_today)}`, "dim");
  return h.box(title, right, rows.join("") + top("from", m.top_senders) + top("to", m.top_recipients), "edge", "log");
}
