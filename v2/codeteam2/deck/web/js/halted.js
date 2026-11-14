// The `halted` box: one line per team that is not up (render._halted), with how long its loop has been off and
// any mail waiting. Empty when every team is up.
import { fmt } from "./fmt.js";
import { h } from "./h.js";

function line(t) {
  const beat = fmt.num(t.heartbeat_age_s);
  const [mail, broadcasts] = fmt.mailCounts(t, "mail_waiting", "broadcasts_waiting");
  return h.row(h.span("■", "salmon") + " " + h.cut(t.name || "?", "dim", "tname")
    + h.span(t.state === "HALTED" ? "halted" : t.state || "?", "salmon")
    + h.span(` · loop off ${beat === null ? "never started" : fmt.dur(beat)}`, "faint")
    + (mail > 0 ? h.span(` · ✉ ${fmt.g(mail)} waiting`, "amber") : "")
    + (broadcasts > 0 ? h.span(` · ◎ ${fmt.g(broadcasts)}`, "dim") : ""));
}

export function halted(teams) {
  const down = teams.filter((t) => t.state !== "up");
  return down.length ? h.box(h.span("halted", "dim bold"), "", down.map(line).join(""), "edge", "halted") : "";
}
