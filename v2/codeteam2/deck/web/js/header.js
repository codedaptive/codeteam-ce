// The header line (counts, alerts, clock, filter, source errors) and the legend beside it (render._header).
import { fmt } from "./fmt.js";
import { h } from "./h.js";

const ROLES = [["orc", "coral"], ["designer", "purple"], ["guard", "teal"], ["lane", "blue"], ["crew", "dim"]];
const STATES = [["●", "working", "green"], ["◐", "between turns", "sky"], ["○", "idle", "dim"], ["✓", "done", "green"],
  ["■", "blocked", "salmon"]];

export function header(snap, teams, alerts, teamFilter) {
  const up = teams.filter((t) => t.state === "up").length;
  const lanes = teams.reduce((sum, t) => sum + (fmt.num(t.lanes_running) || 0), 0);
  const errors = Array.isArray(snap.errors) ? snap.errors.length : 0;
  const counts = h.span("CODETEAM DECK", "bold") + h.dot() + h.span(`${up} UP`, "green bold") + h.dot()
    + h.span(`${teams.length - up} HALTED`, "salmon bold") + h.dot()
    + h.span(`${fmt.g(lanes)} LANES`, "blue bold") + h.span(" WORKING", "bold") + h.dot()
    + h.span(`▲ ${alerts.length} ALERTS`, "amber bold") + h.dot() + h.span(fmt.clock(snap.at), "dim")
    + (teamFilter ? h.dot() + h.span(`team ${teamFilter}`, "blue") : "")
    + (errors ? h.dot() + h.span(`${errors} source errors`, "salmon") : "");
  const legend = ROLES.map(([role, colour]) => `<span class="key"><i class="chip bg-${colour}"></i>${h.span(role, colour)}</span>`)
    .concat(STATES.map(([glyph, word, colour]) => `<span class="key">${h.span(glyph, colour)} ${h.span(word, "dim")}</span>`));
  return `<header class="top"><div class="counts" data-panel="header">${counts}</div><div class="legend" data-panel="legend">${legend.join("")}</div></header>`;
}
