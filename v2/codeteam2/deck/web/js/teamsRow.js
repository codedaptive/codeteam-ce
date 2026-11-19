// BUILDS' teams row (teams_chips.py): under a live runner, each team's running and waiting jobs, busiest first.
import { fmt } from "./fmt.js";
import { h } from "./h.js";

// More running first, then more waiting, then the name in UTF-16 code unit order, which is Python's order for
// the ASCII team names (busiest_teams.py).
function busiest(a, b) {
  return b.running - a.running || b.waiting - a.waiting || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
}

function chip(t) {
  return `<span class="chipline">${h.span(t.name, "bold")} ${h.span(`${fmt.g(t.running)} run ${fmt.g(t.waiting)} wait`, "dim")}</span>`;
}

// One row in the class chips' style: dim "teams", then "<name> <running> run <waiting> wait" per team. "" for any
// runner that is not live or has no teams.
export function teamsRow(runner) {
  const teams = Object.entries(fmt.mapping(runner.teams)).map(([name, c]) => ({
    name, running: fmt.num(fmt.mapping(c).running) || 0, waiting: fmt.num(fmt.mapping(c).waiting) || 0 }));
  if (runner.state !== "live" || !teams.length) return "";
  return h.row(h.span("teams", "dim") + teams.sort(busiest).map(chip).join(""), "chips");
}
