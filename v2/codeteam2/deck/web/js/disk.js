// DISK (render._disk): each team's size as a bar scaled to the largest, measured teams largest first, then the
// rest as `not measured yet`; under each, up to five worktrees with their build parts largest first; then the
// largest build folders. Caption: free space and the scan's age.
import { fmt } from "./fmt.js";
import { freeSpace } from "./freeSpace.js";
import { h } from "./h.js";

// Build parts as render.BUILD_PARTS; the first four over BUILD_RED_GB make a worktree salmon. Tails cap at PATH_CAP.
const BUILD_PARTS = ["cargo-target", "target", ".build", "node_modules", ".codegraph", "scratchpad"];
const BUILD_RED_GB = 10;
const PATH_CAP = 14;
const isDisk = (t) => t.disk && typeof t.disk === "object";

function worktree(w) {
  const parts = fmt.mapping(w.parts);
  const output = BUILD_PARTS.slice(0, 4).reduce((sum, p) => sum + (fmt.num(parts[p]) || 0), 0);
  const colour = output > BUILD_RED_GB ? "salmon" : "dim";
  const present = BUILD_PARTS.filter((p) => p in parts).sort((a, b) => (fmt.num(parts[b]) || 0) - (fmt.num(parts[a]) || 0));
  return h.row(h.span(`${fmt.tail(w.path, PATH_CAP)} ${fmt.gb(w.size_gb)}`, colour) + " "
    + present.map((p) => h.span(`${p} ${fmt.gb(parts[p])}`, colour)).join(" "), "wtrow wrap");
}

function team(t, largest) {
  const name = h.cut(t.name || "?", "bold", "tname");
  if (!isDisk(t)) return h.row(name + h.span("not measured yet", "dim"));
  return h.row(name + h.bar(t.disk.size_gb, largest, "blue", "disk") + `<span class="num">${h.esc(fmt.gb(t.disk.size_gb))}</span>`)
    + fmt.dicts(t.disk.worktrees).slice(0, 5).map(worktree).join("");
}

export function disk(teams, snap, now) {
  const biggest = fmt.dicts(fmt.mapping(snap.builds).largest)
    .map((x) => h.row(h.span(`largest ${fmt.gb(x.size_gb)} ${x.part || "?"} ${fmt.tail(x.path, PATH_CAP)}`, "dim")));
  if (!teams.length && !biggest.length) return "";
  const measured = teams.filter(isDisk).sort((a, b) => (fmt.num(b.disk.size_gb) || 0) - (fmt.num(a.disk.size_gb) || 0));
  const top = Math.max(0, ...measured.map((t) => fmt.num(t.disk.size_gb) || 0)) || 1;
  const rows = measured.concat(teams.filter((t) => !isDisk(t))).map((t) => team(t, top));
  const at = measured.length ? fmt.num(snap.disk_at) : null;
  const right = freeSpace(snap) + h.span(` · ${at === null ? "?" : fmt.dur(now - at)} ago`, "dim");
  return h.box(h.span("DISK", "blue bold"), right, rows.join("") + biggest.join(""), "edge", "disk");
}
