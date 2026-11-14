// A role's colour word (render.ROLE): orc coral, designer purple, guard teal, lane blue; anything else (crew) dim.
const ROLE = { orc: "coral", designer: "purple", guard: "teal", lane: "blue" };

export function roleColour(role) {
  return ROLE[role] || "dim";
}
