// The sessions the cursor moves over, as render.visible: snapshot order, HALTED teams left out (they have no
// team box), only the filtered team when teamFilter is set.

export function visible(snap, teamFilter) {
  const teams = (snap.teams || []).filter((t) => teamFilter === null || teamFilter === undefined || t.name === teamFilter);
  return teams
    .filter((t) => t.state !== "HALTED")
    .flatMap((t) => (t.sessions || []).map((s) => ({ id: `${t.name}/${s.key}`, team: t, session: s })));
}
