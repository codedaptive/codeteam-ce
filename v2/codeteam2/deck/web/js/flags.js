// Every flag that applies to a session, for the focus box (render._flags), as [text, colour words] pairs.
import { fmt } from "./fmt.js";

export function flags(s) {
  const f = s.flags || {};
  const parts = [];
  if (f.waiting_on_finished_child) parts.push(["child done", "salmon bold"]);
  if (f.blocked || (s.herdr || {}).status === "blocked") parts.push([`blocked ${fmt.dur(f.blocked_for_s)}`, "salmon bold"]);
  if ((s.draft_since !== null && s.draft_since !== undefined) || f.typing) parts.push(["typing", "amber"]);
  if (s.api_error || f.api_error) parts.push(["api error", "amber"]);
  if (fmt.num(s.idle_exit_in_s) !== null) parts.push([`exit ${fmt.dur(s.idle_exit_in_s)}`, "faint"]);
  return parts;
}
