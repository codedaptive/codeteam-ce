// A sparkline as inline SVG: one bar per value, scaled to the largest, as render.sparkline scales its glyphs.
// A zero or missing value is a faint dot; an object entry (a compaction in the turns trace) is a sky marker.

const STEP = 4;
const HEIGHT = 12;

export function spark(values, label) {
  const nums = values.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : 0));
  const top = Math.max(0, ...nums);
  const marks = values.map((v, i) => {
    const x = i * STEP;
    if (v && typeof v === "object") return `<rect class="f-sky" x="${x}" y="0" width="1.5" height="${HEIGHT}"/>`;
    if (nums[i] <= 0 || top <= 0) return `<rect class="f-faint" x="${x + 1}" y="${HEIGHT - 1.5}" width="1.5" height="1.5"/>`;
    const tall = Math.max(1.5, (nums[i] / top) * HEIGHT);
    return `<rect class="f-blue" x="${x}" y="${(HEIGHT - tall).toFixed(2)}" width="3" height="${tall.toFixed(2)}"/>`;
  });
  const width = Math.max(STEP, values.length * STEP);
  return `<svg class="spark" role="img" aria-label="${label}" width="${width}" height="${HEIGHT}" `
    + `viewBox="0 0 ${width} ${HEIGHT}">${marks.join("")}</svg>`;
}
