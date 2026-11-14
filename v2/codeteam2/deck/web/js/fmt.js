// The terminal deck's value formats (render.py's _dur, _timer, _clock, _count, _g, _usd, _gb, _cap, _tail,
// _ctx_colour, _model), so the page and the terminal print the same numbers. One namespace: every panel uses them.

const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : null);
const pad2 = (n) => String(n).padStart(2, "0");

// Python's f"{x:g}": six significant digits, no trailing zeros.
const g = (x) => (num(x) === null ? "?" : Number.isInteger(x) ? String(x) : String(Number(x.toPrecision(6))));

function dur(s) {
  if (num(s) === null) return "?";
  s = Math.max(Math.trunc(s), 0);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h${pad2(Math.floor((s % 3600) / 60))}m`;
  return `${Math.floor(s / 86400)}d${Math.floor((s % 86400) / 3600)}h`;
}

function timer(s) {
  if (num(s) === null) return "?";
  s = Math.max(0, Math.trunc(s));
  return s < 3600 ? `${Math.floor(s / 60)}:${pad2(s % 60)}` : `${Math.floor(s / 3600)}h${pad2(Math.floor((s % 3600) / 60))}`;
}

// Local time from an epoch or ISO timestamp; `?` for a failed reading.
function clock(ts, secs = false) {
  const when = num(ts) !== null ? new Date(ts * 1000) : typeof ts === "string" ? new Date(ts) : null;
  if (!when || Number.isNaN(when.getTime())) return "?";
  const hm = `${pad2(when.getHours())}:${pad2(when.getMinutes())}`;
  return secs ? `${hm}:${pad2(when.getSeconds())}` : hm;
}

const count = (x) => (num(x) === null ? "?" : x >= 1000 ? `${(x / 1000).toFixed(1)}k` : x.toFixed(0));
const usd = (x) => (num(x) === null ? "$?" : `$${x.toFixed(2)}`);
const gb = (x) => (num(x) === null ? "?" : `${x.toFixed(1)}G`);

function cap(text, n) {
  text = String(text);
  return text.length <= n ? text : `${text.slice(0, n - 1)}…`;
}

function tail(path, n = 40) {
  const last = String(path || "?").replace(/\/+$/, "").split("/").pop();
  return last.length <= n ? last : `…${last.slice(-(n - 1))}`;
}

// Context heats up at 30%, 40% and 50% (SPEC-deck-motion B1); an unknown fill is amber.
function ctxColour(p) {
  if (p === null) return "amber";
  return p < 30 ? "green" : p < 40 ? "amber" : p < 50 ? "orange" : "salmon";
}

function model(s) {
  const m = String(s.model || "?").replace(/^claude-/, "");
  if (m.startsWith("opus-")) return `Opus ${m.slice(5).replaceAll("-", ".")}`;
  if (m.startsWith("sonnet-")) return `Sonnet ${m.slice(7).replaceAll("-", ".")}`;
  return m.slice(0, 12);
}

const dicts = (items) => (Array.isArray(items) ? items.filter((x) => x && typeof x === "object" && !Array.isArray(x)) : []);
const mapping = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});

// (waiting less broadcasts, broadcasts), as render._mail_counts.
function mailCounts(cell, waitingKey = "waiting", broadcastsKey = "broadcasts") {
  const waiting = num(cell[waitingKey]);
  const broadcasts = num(cell[broadcastsKey]);
  return [waiting !== null && broadcasts !== null ? waiting - broadcasts : waiting, broadcasts];
}

// The age of a session's oldest undelivered mail. Missing broadcast counts identify snapshots whose ages still
// cover every undelivered message (render._mail_age).
function mailAge(mail) {
  if (num(mail.broadcasts) === null) return mail.oldest_waiting_s;
  return "oldest_mail_s" in mail ? mail.oldest_mail_s : mail.oldest_waiting_s;
}

export const fmt = { num, g, dur, timer, clock, count, usd, gb, cap, tail, ctxColour, model, dicts, mapping, mailCounts,
  mailAge };
