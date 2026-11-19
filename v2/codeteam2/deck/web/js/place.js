// Places the middle's boxes in its two columns: team boxes start on the left, detail panels on the right, and each
// box goes to the foot of the shorter column (the left on a tie). A column whose own list is used up takes the next
// box of the other list, so what is left of the longer list spills into both. Takes the boxes' heights in rows and
// returns [left, right], each a top-to-bottom list of ["t", i] (team i) or ["d", i] (detail i). Pure.
export function place(teams, details) {
  const lists = [teams, details];
  const kinds = ["t", "d"];
  const next = [0, 0];
  const cols = [[], []];
  const rows = [0, 0];
  while (next[0] < teams.length || next[1] < details.length) {
    const col = rows[0] <= rows[1] ? 0 : 1;
    const from = next[col] < lists[col].length ? col : 1 - col;
    cols[col].push([kinds[from], next[from]]);
    rows[col] += lists[from][next[from]];
    next[from] += 1;
  }
  return cols;
}
