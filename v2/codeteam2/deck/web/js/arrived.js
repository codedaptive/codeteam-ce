// Messages new since the previous snapshot, as [team, id] pairs (motion.State.arrived over app._max_ids): a logged
// message whose id is above its team's max_id in prev. A team prev did not have, or the first snapshot, flashes
// nothing, so opening the page does not light every line.

export function arrived(prev, snap) {
  const before = new Map();
  for (const t of (prev && prev.teams) || []) {
    const maxId = t.messages && t.messages.max_id;
    if (maxId !== null && maxId !== undefined) before.set(t.name, maxId);
  }
  return (snap.teams || []).filter((t) => before.has(t.name)).flatMap((t) =>
    ((t.messages && t.messages.last) || []).filter((m) => m.id > before.get(t.name)).map((m) => [t.name, m.id]));
}
