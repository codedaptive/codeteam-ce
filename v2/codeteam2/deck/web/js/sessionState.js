// A session's state glyph, word, colour and age (render._state). Blocked shows how long it has been blocked.
import { fmt } from "./fmt.js";

const STATUS = { working: ["●", "working", "green"], idle: ["○", "idle", "dim"], done: ["✓", "done", "green"],
  absent: ["·", "ended", "faint"] };

export function sessionState(s, now) {
  const herdr = s.herdr || {};
  const flags = s.flags || {};
  const since = fmt.num(herdr.since);
  const age = since === null ? "?" : fmt.dur(now - since);
  if (herdr.status === "blocked") {
    return ["■", "blocked", "salmon", fmt.num(flags.blocked_for_s) === null ? age : fmt.dur(flags.blocked_for_s)];
  }
  if (flags.between_turns) return ["◐", "between", "sky", age];
  return [...(STATUS[herdr.status] || ["?", "?", "amber"]), age];
}
