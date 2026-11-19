// A panel's height in rows of --row, counted from its markup, for place(): each line element (class starting with
// row, srow or mrow) is one row, and a wrap row counts as one line though it may wrap onto more. A two-column split
// counts as its data-rows (the taller column's rows) in place of the rows inside it, since its columns sit side by
// side. Each boxed section adds 1.5: its header edge, padding and border take about a row and a half of --row.
const BOX = /<section class="box/g;
const LINE = /class="(?:row|srow|mrow)/g;
const SPLIT = /<div class="split" data-rows="(\d+)">/g;
const DIV = /<(\/?)div\b/g;

const lines = (markup) => (markup.match(LINE) || []).length;

// The index just past the </div> that closes the div opening at start.
function endOf(markup, start) {
  let depth = 0;
  for (const tag of markup.slice(start).matchAll(DIV)) {
    depth += tag[1] ? -1 : 1;
    if (depth === 0) return start + tag.index + tag[0].length;
  }
  return markup.length;
}

export function rowsOf(markup) {
  let rows = 1.5 * (markup.match(BOX) || []).length;
  let at = 0;
  for (const split of markup.matchAll(SPLIT)) {
    rows += lines(markup.slice(at, split.index)) + Number(split[1]);
    at = endOf(markup, split.index);
  }
  return rows + lines(markup.slice(at));
}
