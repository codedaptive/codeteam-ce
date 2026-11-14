// One team's box (render._team_box): lanes, mail, broadcasts and cost today, then its session rows. The caption is
// the 24 h message sparkline and last hour, then `● up · loop 5s`, or the state of a team that is not up. The cursor's team is blue.
import { flashIds } from "./flashIds.js";
import { fmt } from "./fmt.js";
import { h } from "./h.js";
import { sessionRow } from "./sessionRow.js";
import { spark } from "./spark.js";

// A loop older than this is late (render.HEARTBEAT_RED_S).
const HEARTBEAT_RED_S = 60;

function stats(t, sessions) {
  const lanes = fmt.num(t.lanes_running);
  const capped = fmt.num(t.cap);
  const over = lanes !== null && capped !== null && lanes > capped;
  const known = sessions.map((s) => fmt.num((s.cost || {}).session_usd)).filter((c) => c !== null);
  const [mail, broadcasts] = fmt.mailCounts(t, "mail_waiting", "broadcasts_waiting");
  return h.row(h.pips(lanes, capped, 10, over ? "salmon" : "blue") + " "
    + h.span(`${fmt.g(lanes)}/${fmt.g(capped)} lanes`, over ? "salmon" : "dim") + h.dot()
    + h.span(`✉ ${fmt.g(mail)}`, mail ? "amber" : "dim")
    + (broadcasts > 0 ? h.dot() + h.span(`◎ ${fmt.g(broadcasts)}`, "dim") : "") + h.dot()
    + h.span(`${fmt.usd(known.length ? known.reduce((a, b) => a + b, 0) : null)} today`, "coral"));
}

// The 24 h sparkline and the last hour, which lead the caption so the box spends one row on its stats.
function hours(messages) {
  if (!messages || typeof messages !== "object") return h.span("24h ?", "amber");
  return `${h.span("24h", "dim")} ${spark(messages.hourly || [], "messages per hour, 24 h")} `
    + h.span(`${fmt.g(messages.last_hour)}/h`, "bold");
}

function caption(t) {
  if (t.state !== "up") return hours(t.messages) + h.dot() + h.span(t.state || "?", "salmon");
  const beat = fmt.num(t.heartbeat_age_s);
  return hours(t.messages) + h.dot() + h.span("● up", "green") + h.span(" · loop ", "dim")
    + h.span(fmt.dur(beat), beat === null ? "amber" : beat > HEARTBEAT_RED_S ? "salmon" : "dim");
}

export function teamBox(t, now, currentId, flash, motion) {
  const sessions = t.sessions || [];
  const lit = flashIds(t, flash);
  const rows = sessions.map((s) => {
    const hit = lit.has(`key:${s.key}`) || lit.has(`any:${s.name}`) || lit.has(`any:${s.key}`);
    return sessionRow(t, s, now, `${t.name}/${s.key}` === currentId, hit, motion);
  });
  const isCurrent = sessions.some((s) => `${t.name}/${s.key}` === currentId);
  const title = h.span(t.name || "?", "bold") + h.span(` · ${sessions.length} session${sessions.length === 1 ? "" : "s"}`, "dim");
  return h.box(title, caption(t), stats(t, sessions) + rows.join(""),
    isCurrent ? "blue" : "edge", `team:${t.name}`);
}
