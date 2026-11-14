// Which session rows of a team flash for its newly arrived messages (render._flash_ids). flash is a list of
// [team, message id] pairs. A message with a `target` (the session key its recipient resolved to) lights the row
// with that key; one without lights the row whose name or key is its recipient. Returns a Set of
// "key:<key>" and "any:<name or key>" strings.
import { fmt } from "./fmt.js";

export function flashIds(t, flash) {
  const lit = new Set();
  if (!flash.length) return lit;
  const wanted = new Set(flash.filter(([team]) => team === t.name).map(([, id]) => id));
  for (const x of fmt.dicts(fmt.mapping(t.messages).last)) {
    const [kind, who] = "target" in x ? ["key", x.target] : ["any", x.recipient];
    if (who && wanted.has(x.id)) lit.add(`${kind}:${who}`);
  }
  return lit;
}
