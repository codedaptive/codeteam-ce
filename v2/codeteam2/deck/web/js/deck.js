// The whole deck as one HTML string (render.render's panels in the page's layout): header and legend; FLEET; team
// boxes and the halted box on the left; the dock (focus, agents, log | BUILDS, DISK) on the right; ALERTS and the
// keys pinned at the foot. Pure: no DOM, no fetch, no clock; every age is taken against snap.at. Runs in node.
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
import { teamBox } from "./teamBox.js";
import { visible } from "./visible.js";

const KEYS = [["↑↓ j k", "move"], ["⏎", "expand"], ["click", "select"], ["a", "all agents"], ["t", "team"], ["d", "disk now"]];

// Team boxes in two columns, each box at the foot of the shorter one (render._left's two-across placement), counted
// in rows: a box is its title, stats and sessions; the halted box its title and lines. CSS columns would fill in
// order and push the last boxes into a hidden third column.
function columns(teams, boxed, now, currentId, flash, motion) {
  const cols = [[], []];
  const rows = [0, 0];
  const place = (markup, height) => {
    const i = rows[0] <= rows[1] ? 0 : 1;
    cols[i].push(markup);
    rows[i] += height;
  };
  for (const t of boxed) place(teamBox(t, now, currentId, flash, motion), 2.5 + (t.sessions || []).length);
  const down = teams.filter((t) => t.state !== "up").length;
  if (down) place(halted(teams), 1.5 + down);
  return cols.map((c) => `<div class="tcol">${c.join("")}</div>`).join("");
}

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
  const dockA = (current ? focus(current.session, current.team, now, expanded, ui.motion) : "")
    + agents(vis, now, cursor, ui.allAgents, expanded, ui.motion)
    + (current ? messageLog(current.team, flash, ui.motion) : "");
  const dockB = builds(snap.builds, ui.motion) + disk(teams, snap, now);
  return `<div class="deck">${header(snap, teams, alertList, ui.teamFilter)}${fleet(teams, snap)}`
    + `<main class="middle"><div class="teams">${columns(teams, boxed, now, current?.id, flash, ui.motion)}</div><div class="dock">${dockA}</div><div class="dock">${dockB}</div></main>`
    + `${alerts(alertList)}${keyLine()}</div>`;
}
