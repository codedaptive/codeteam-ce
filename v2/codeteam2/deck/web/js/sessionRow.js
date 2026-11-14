// One session row in a team box (render._session_row): cursor, state glyph, name in its role colour, age,
// context bar and %, cost, badge. data-id lets a click select it; `lit` flashes it for arriving mail.
import { badge } from "./badge.js";
import { fmt } from "./fmt.js";
import { h } from "./h.js";
import { roleColour } from "./roleColour.js";
import { sessionState } from "./sessionState.js";

export function sessionRow(t, s, now, current, lit, motion) {
  const [glyph, word, colour, age] = sessionState(s, now);
  const pct = fmt.num((s.context || {}).used_pct);
  const heat = fmt.ctxColour(pct);
  const name = s.name || s.key || "?";
  const tag = badge(s);
  const pulse = motion && word === "working" ? "pulse" : "";
  const classes = ["srow", current ? "current" : "", lit && motion ? "flash" : ""].filter(Boolean).join(" ");
  return `<div class="${classes}" data-id="${h.esc(`${t.name}/${s.key}`)}" title="${h.esc(`${name} · ${word} ${age}`)}">`
    + `<span class="cur c-coral b">${current ? "▸" : ""}</span>`
    + `<span class="glyph ${h.cls(colour)} ${pulse}">${h.esc(glyph)}</span>`
    + h.cut(name, roleColour(s.role) + (current ? " bold" : ""), "name")
    + `<span class="num c-dim">${h.esc(age)}</span>`
    + h.bar(pct, 100, heat, "ctx")
    + `<span class="num ${h.cls(heat)}">${h.esc(fmt.g(pct))}%</span>`
    + `<span class="num">${h.esc(fmt.usd((s.cost || {}).session_usd))}</span>`
    + (tag ? h.cut(tag[0], tag[1], "badge") : "<span></span>")
    + "</div>";
}
