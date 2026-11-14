// A session row's one badge, the first that applies (render._badge), as [text, colour words] or null.
import { fmt } from "./fmt.js";

export function badge(s) {
  const f = s.flags || {};
  const m = s.mail || {};
  if (f.waiting_on_finished_child) return ["child done", "salmon bold chipped"];
  if (f.blocked || (s.herdr || {}).status === "blocked") return ["blocked", "salmon bold"];
  if (f.held || m.held) return [`held ${fmt.g(m.held)}`, "salmon"];
  if ((s.draft_since !== null && s.draft_since !== undefined) || f.typing) return ["typing", "amber"];
  if (s.api_error || f.api_error) return ["api error", "amber"];
  const [waiting, broadcasts] = fmt.mailCounts(m);
  if (waiting > 0) return [`✉${fmt.g(waiting)} ${fmt.dur(fmt.mailAge(m))}`, "amber"];
  if (broadcasts > 0) return [`◎${fmt.g(broadcasts)}`, "dim"];
  if (fmt.num(s.idle_exit_in_s) !== null) return [`exit ${fmt.dur(s.idle_exit_in_s)}`, "faint"];
  return null;
}
