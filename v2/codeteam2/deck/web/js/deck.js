// The whole deck as one HTML string (render.render's panels in the page's layout): header and legend; FLEET; the
// middle in two columns, team boxes and the halted box on the left, the detail panels (focus, agents, log, BUILDS,
// DISK) on the right, and whatever one list has left over spilling into whichever column is shorter; ALERTS and the
// keys pinned at the foot. ui.width, the px width of a middle column, goes to focus and BUILDS, which draw two
// columns when it is wide enough (missing or 0: one). Pure: no DOM, no fetch, no clock; every age is taken against
// snap.at. Runs in node.
import { agents } from "./agents.js";
import { alerts } from "./alerts.js";
import { builds } from "./builds.js";
import { disk } from "./disk.js";
import { fleet } from "./fleet.js";
import { fmt } from "./fmt.js";
import { focus } from "./focus.js";
import { h } from "./h.js";
import { halted } from "./halted.js";
import { header } from "./header.js";
import { messageLog } from "./messageLog.js";
import { place } from "./place.js";
import { rowsOf } from "./rowsOf.js";
import { teamBox } from "./teamBox.js";
import { visible } from "./visible.js";

const KEYS = [["↑↓ j k", "move"], ["⏎", "expand"], ["click", "select"], ["a", "all agents"], ["t", "team agents"],
  ["f", "team filter"], ["d", "disk now"]];

// The middle's two columns, each box at the foot of the shorter one (place), counted in rows (rowsOf). CSS columns
// would fill in order and push the last boxes into a hidden column.
function middle(teamList, detailList) {
  const lists = { t: teamList, d: detailList };
  const cols = place(teamList.map(rowsOf), detailList.map(rowsOf));
  return `<main class="middle">${cols.map((col) => `<div class="col">${col.map(([kind, i]) => lists[kind][i]).join("")}</div>`).join("")}</main>`;
}

// The agents panel's scope: a shows all agents, T the cursor team's, neither the cursor session's.
const agentScope = (ui) => (ui.allAgents ? "all" : ui.teamAgents ? "team" : "session");

const keyLine = () => `<footer class="keys" data-panel="keys">${KEYS.map(([key, word]) => `<span>${h.span(key, "bold")} ${h.span(word, "dim")}</span>`).join("")}</footer>`;

export function renderDeck(snap, ui) {
  snap = snap || {};
  const now = fmt.num(snap.at) || 0;
  const flash = ui.motion ? ui.flash || [] : [];
  const teams = (snap.teams || []).filter((t) => !ui.teamFilter || t.name === ui.teamFilter);
  const vis = visible(snap, ui.teamFilter || null);
  const cursor = Math.max(0, Math.min(ui.cursor, vis.length - 1));
  const current = vis[cursor] || null;
  const expanded = current !== null && ui.expanded.includes(current.id);
  const alertList = fmt.dicts(Array.isArray(snap.alert_log) ? snap.alert_log : snap.alerts);
  // A team box for each team that is up or has sessions (HALTED teams keep only their halted line), the cursor's first.
  const boxed = teams.filter((t) => t.state !== "HALTED" && (t.state === "up" || (t.sessions || []).length))
    .sort((a, b) => (b === current?.team) - (a === current?.team));
  const teamList = boxed.map((t) => teamBox(t, now, current?.id, flash, ui.motion)).concat(halted(teams));
  const detailList = [
    current ? focus(current.session, current.team, now, expanded, ui.motion, ui.width) : "",
    agents(vis, now, cursor, agentScope(ui), expanded, ui.motion),
    current ? messageLog(current.team, flash, ui.motion) : "",
    builds(snap.builds, ui.motion, ui.width),
    disk(teams, snap, now),
  ];
  return `<div class="deck">${header(snap, teams, alertList, ui.teamFilter)}${fleet(teams, snap)}`
    + middle(teamList.filter(Boolean), detailList.filter(Boolean))
    + `${alerts(alertList)}${keyLine()}</div>`;
}
