// The page's only DOM and network module. It polls /snapshot.json every data-interval seconds (never while the tab
// is hidden, so a hidden tab lets the server go idle), keeps the ui state, morphs #deck in place, routes keys
// through handleKey and clicks on a session row to the cursor, POSTs /disk-now for `d`, and keeps arriving mail
// lit for FLASH_MS. Each middle column keeps its scroll position across every redraw; after a key that moves the
// cursor or changes the list, and after a click select, the cursor row is scrolled just into view. A poll's redraw
// never scrolls to the cursor, so it does not fight the user's wheel. ui.width is the measured width of a middle
// column (clientWidth of `.middle > .col`), which decides whether focus and BUILDS draw two columns: after each draw
// that finds it changed (the first draw, a window resize), the deck is drawn once more with the measured width.
import { arrived } from "./arrived.js";
import { renderDeck } from "./deck.js";
import { handleKey } from "./keys.js";
import { morph } from "./morph.js";
import { visible } from "./visible.js";

// SPEC-deck-motion A3: arriving mail shows for about 2 s.
const FLASH_MS = 2000;
const root = document.getElementById("deck");
const html = document.documentElement;
const interval = (Number(html.dataset.interval) || 2) * 1000;
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
const motionOn = () => html.dataset.motion === "on" && !reduced.matches;

let snap = null;
let ui = { cursor: 0, expanded: [], allAgents: false, teamAgents: false, teamFilter: null, flash: [],
  motion: motionOn() };
let lit = new Map();

const columns = () => root.querySelectorAll(".middle > .col");

// Morph #deck to the current state, each middle column keeping its scroll position.
function paint() {
  const tops = [...columns()].map((col) => col.scrollTop);
  morph(root, renderDeck(snap, ui));
  columns().forEach((col, i) => {
    if (i < tops.length && col.scrollTop !== tops[i]) col.scrollTop = tops[i];
  });
}

// reveal: scroll the cursor row into view after the redraw, as far as needed and no further. The second paint uses
// the width the first one measured, so a draw paints at most twice.
function draw(reveal = false) {
  if (!snap) return;
  paint();
  const width = columns()[0]?.clientWidth || 0;
  if (width !== (ui.width || 0)) {
    ui = { ...ui, width };
    paint();
  }
  if (reveal) root.querySelector(".srow.current")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function relight(next) {
  const now = performance.now();
  for (const [team, id] of arrived(snap, next)) {
    const key = `${team}\u0000${id}`;
    if (!lit.has(key)) lit.set(key, { pair: [team, id], until: now + FLASH_MS });
  }
  lit = new Map([...lit].filter(([, v]) => v.until > now));
  return [...lit.values()].map((v) => v.pair);
}

async function poll() {
  if (!document.hidden) {
    try {
      const response = await fetch("/snapshot.json", { cache: "no-store" });
      if (response.ok) {
        const next = await response.json();
        ui = { ...ui, flash: relight(next), motion: motionOn() };
        snap = next;
        draw();
      }
    } catch {
      // The server is gone or restarting: the page keeps its last frame and the next poll tries again.
    }
  }
  setTimeout(poll, interval);
}

const KEYS = new Set(["ArrowUp", "ArrowDown", "j", "k", "Enter", "a", "t", "f", "d"]);
// The keys that move the cursor, change the list (f, the team filter) or (Enter) change the focus panel's height.
const REVEAL = new Set(["ArrowUp", "ArrowDown", "j", "k", "Enter", "f"]);

document.addEventListener("keydown", (event) => {
  if (!snap || !KEYS.has(event.key) || event.metaKey || event.ctrlKey || event.altKey) return;
  event.preventDefault();
  const result = handleKey(event.key, ui, snap);
  ui = result.ui;
  if (result.action === "disk-now") fetch("/disk-now", { method: "POST" }).catch(() => {});
  draw(REVEAL.has(event.key));
});

// A click selects a session; a click on the selected one expands it, as Enter does.
root.addEventListener("click", (event) => {
  const row = event.target.closest("[data-id]");
  if (!row || !snap) return;
  const at = visible(snap, ui.teamFilter).findIndex((v) => v.id === row.dataset.id);
  if (at < 0) return;
  ui = at === ui.cursor ? handleKey("Enter", ui, snap).ui : { ...ui, cursor: at };
  draw(true);
});

window.addEventListener("resize", () => draw());

reduced.addEventListener("change", () => {
  ui = { ...ui, motion: motionOn() };
  draw();
});

poll();
