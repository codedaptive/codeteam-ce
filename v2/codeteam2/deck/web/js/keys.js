// The terminal deck's keys (app._handle) over the page's ui state. Returns a new ui and the action the page must
// take ("disk-now" or null); the ui given is never changed. q has no meaning in a tab, so it does nothing here.
import { visible } from "./visible.js";

// The team filter after current: null (all teams), then each team in turn, then null again (app._next_filter).
function nextFilter(snap, current) {
  const names = [null, ...(snap.teams || []).map((t) => t.name)];
  const at = names.indexOf(current);
  return at < 0 ? null : names[(at + 1) % names.length];
}

export function handleKey(key, ui, snap) {
  const ids = visible(snap, ui.teamFilter).map((v) => v.id);
  switch (key) {
    case "ArrowUp":
    case "k":
      return { ui: { ...ui, cursor: Math.max(ui.cursor - 1, 0) }, action: null };
    case "ArrowDown":
    case "j":
      return { ui: { ...ui, cursor: Math.min(ui.cursor + 1, Math.max(ids.length - 1, 0)) }, action: null };
    case "Enter": {
      if (!ids.length) return { ui: { ...ui }, action: null };
      const id = ids[Math.min(ui.cursor, ids.length - 1)];
      const expanded = ui.expanded.includes(id) ? ui.expanded.filter((x) => x !== id) : [...ui.expanded, id];
      return { ui: { ...ui, expanded }, action: null };
    }
    case "a":
      return { ui: { ...ui, allAgents: !ui.allAgents }, action: null };
    case "t":
      return { ui: { ...ui, teamFilter: nextFilter(snap, ui.teamFilter), cursor: 0 }, action: null };
    case "d":
      return { ui: { ...ui }, action: "disk-now" };
    default:
      return { ui: { ...ui }, action: null };
  }
}
