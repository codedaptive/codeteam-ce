// Markup pieces every panel draws with: escaped text in a colour, bars, pips, boxes. Bars and pips are CSS boxes
// whose fill width is a percentage, so a changed value eases by CSS transition; the terminal's block characters
// never appear. Colour words are render.py's (coral, dim, ...); each maps to a `c-<word>` class in deck.css.

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

// Colour words, space separated ("salmon bold"), as classes.
const cls = (words) => (words || "").split(" ").filter(Boolean).map((w) => (w === "bold" ? "b" : `c-${w}`)).join(" ");

const span = (text, words) => `<span class="${cls(words)}">${esc(text)}</span>`;

// A cell that may be cut by its column: an ellipsis in CSS, and the full text on hover.
const cut = (text, words, extra = "") => `<span class="cut ${cls(words)} ${extra}" title="${esc(text)}">${esc(text)}</span>`;

// The text of escaped markup, still escaped, for a title attribute: tags dropped, whitespace collapsed.
const textOf = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

// A row: one line, cut at its end, with its full text on hover (title, else the row's own text). A "wrap" row
// instead flows its parts onto more lines, as render._wrap does for mail, flags and worktree rows.
const row = (inner, extra = "", title = null) =>
  `<div class="row ${extra}" title="${title === null ? textOf(inner) : esc(title)}">${inner}</div>`;

const percent = (value, maximum) => Math.max(0, Math.min(100, (value / maximum) * 100));

// A bar of value against maximum in colour; `?` in amber when either is unreadable. Any value above zero shows.
function bar(value, maximum, colour, size = "") {
  const v = typeof value === "number" && Number.isFinite(value) ? value : null;
  if (v === null || !(maximum > 0)) return span("?", "amber");
  const width = v <= 0 ? 0 : Math.max(1.5, percent(v, maximum));
  return `<span class="bar ${size}"><i class="bg-${colour}" style="width:${width.toFixed(2)}%"></i></span>`;
}

// Python's round(): a value halfway between two integers goes to the even one.
function roundHalfEven(x) {
  const near = Math.round(x);
  return Math.abs(x % 1) === 0.5 && near % 2 ? near - 1 : near;
}

// Lanes pips: a count against its cap as cells, rounded half to even as render._pips rounds them.
function pips(value, maximum, cells, colour) {
  const v = typeof value === "number" && Number.isFinite(value) ? value : null;
  if (v === null || !(maximum > 0)) return span("?", "amber");
  const on = v <= 0 ? 0 : Math.max(1, Math.min(cells, roundHalfEven((v / maximum) * cells)));
  return `<span class="pips" style="--cells:${cells}"><i class="bg-${colour}" style="width:${((on / cells) * 100).toFixed(2)}%"></i></span>`;
}

// A box: title and right caption in its top edge (both markup), body rows below. kind is the border's colour word;
// panel names the box in data-panel ("fleet", "team:alpha", ...).
function box(title, right, body, kind, panel) {
  const extra = panel.split(":")[0];
  return `<section class="box k-${kind} ${extra}" data-panel="${esc(panel)}"><header><span class="title" title="${textOf(title)}">${title}</span>`
    + `<span class="right">${right || ""}</span></header><div class="body">${body}</div></section>`;
}

const dot = () => span(" · ", "dim");

export const h = { esc, cls, span, cut, row, bar, pips, box, dot };
