// FLEET: one cell per team, up teams first by sessions running (render._fleet); the caption carries free space
// and the loops that are late.
import { fmt } from "./fmt.js";
import { freeSpace } from "./freeSpace.js";
import { h } from "./h.js";

// A loop older than this is late (render.HEARTBEAT_RED_S).
const HEARTBEAT_RED_S = 60;

function mail(t) {
  const [waiting, broadcasts] = fmt.mailCounts(t, "mail_waiting", "broadcasts_waiting");
  const up = t.state === "up";
  const letters = up || waiting ? h.span(`✉${fmt.g(waiting)}`, waiting === null || waiting > 0 ? "amber" : "faint") : "";
  const ring = broadcasts > 0 ? ` ${h.span(`◎${fmt.g(broadcasts)}`, "dim")}` : "";
  if (!up) return letters || ring ? letters + ring : h.span("loop off", "faint");
  return `${letters}${ring} ${h.span(`${fmt.g(t.msgs_last_hour)}/h`, "dim")}`;
}

function cell(t) {
  const up = t.state === "up";
  const name = h.span(up ? "●" : "■", up ? "green" : "salmon") + " " + h.cut(t.name || "?", up ? "bold" : "dim");
  const lanes = fmt.num(t.lanes_running);
  const capped = fmt.num(t.cap);
  const over = lanes !== null && capped !== null && lanes > capped;
  const state = up
    ? h.pips(lanes, capped, 6, over ? "salmon" : "blue") + " " + h.span(`${fmt.g(lanes)}/${fmt.g(capped)}`, over ? "salmon" : "dim")
    : h.span(t.state === "HALTED" ? "halted" : t.state || "?", "salmon");
  return `<div class="cell">${h.row(name)}${h.row(`${state} ${mail(t)}`)}</div>`;
}

export function fleet(teams, snap) {
  const up = (t) => t.state === "up";
  const order = teams.map((t, i) => [t, i]).sort(([a, i], [b, j]) =>
    (up(a) === up(b) ? (up(a) ? (fmt.num(b.running) || 0) - (fmt.num(a.running) || 0) : 0) : up(a) ? -1 : 1) || i - j);
  const late = teams.filter((t) => up(t) && (fmt.num(t.heartbeat_age_s) || 0) > HEARTBEAT_RED_S).map((t) => t.name || "?");
  const right = freeSpace(snap) + h.span(" · loops ", "dim") + h.span(late.length ? late.join(", ") : "all beating", late.length ? "salmon" : "green");
  const title = h.span("FLEET", "bold") + h.span(` · ${teams.length} team${teams.length === 1 ? "" : "s"}`, "dim");
  return h.box(title, right, `<div class="cells">${order.map(([t]) => cell(t)).join("")}</div>`, "edge", "fleet");
}
