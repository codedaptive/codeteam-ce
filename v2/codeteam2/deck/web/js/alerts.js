// ALERTS, pinned at the foot (render._alerts): newest first as the log keeps them; each line has ▲, the time, the
// team and the text, salmon for trouble and amber otherwise. At most ALERT_ROWS lines, the rest counted in the caption.
import { fmt } from "./fmt.js";
import { h } from "./h.js";

// render.ALERT_ROWS: the alerts never crowd out the dashboard above them.
const ALERT_ROWS = 6;
const RED_KINDS = ["blocked", "held", "heartbeat", "stalled", "child_finished", "disk_low"];

export function alerts(list) {
  if (!list.length) return "";
  const shown = list.slice(0, ALERT_ROWS);
  const rows = shown.map((a) => {
    const colour = RED_KINDS.includes(a.kind) ? "salmon" : "amber";
    return h.row(h.span("▲", colour) + " " + h.span(fmt.clock(a.since), "faint") + " "
      + h.cut(a.team || "?", "dim", "tname") + h.cut(a.text || a.kind || "?", colour, "text"), "alert");
  });
  const more = list.length > shown.length ? h.span(` · +${list.length - shown.length} more`, "dim") : "";
  return h.box(h.span("ALERTS", "amber bold"), h.span("newest first", "dim") + more, rows.join(""), "amber", "alerts");
}
