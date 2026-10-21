/**
 * Squarified treemap layout (Bruls, Huizing, van Wijk 2000). Pure: no imports, so a spec can load it directly.
 *
 *   squarify([{ item: "A", value: 6 }, { item: "B", value: 3 }], { x: 0, y: 0, w: 300, h: 200 })
 *
 * Each returned rectangle has an area proportional to its value (the areas add up to the rectangle's area), and
 * none overlap. Items whose value is not a positive number are left out, since they have no area to take.
 */
export interface Rect { x: number; y: number; w: number; h: number }
export interface SqItem<T> { item: T; value: number }
export type Placed<T> = Rect & { item: T };

/** The worst (largest) aspect ratio in a row of areas laid along a side of this length. */
function worst(areas: number[], side: number): number {
  let sum = 0;
  let max = -Infinity;
  let min = Infinity;
  for (const a of areas) { sum += a; if (a > max) max = a; if (a < min) min = a; }
  const s2 = side * side;
  return Math.max((s2 * max) / (sum * sum), (sum * sum) / (s2 * min));
}

export function squarify<T>(items: SqItem<T>[], rect: Rect): Placed<T>[] {
  const kept = items.filter((i) => Number.isFinite(i.value) && i.value > 0).sort((a, b) => b.value - a.value);
  if (!kept.length || rect.w <= 0 || rect.h <= 0) return [];
  const total = kept.reduce((s, i) => s + i.value, 0);
  const scale = (rect.w * rect.h) / total;
  const queue = kept.map((i) => ({ item: i.item, area: i.value * scale }));
  const out: Placed<T>[] = [];
  let { x, y, w, h } = rect;
  let i = 0;
  while (i < queue.length) {
    const side = Math.min(w, h);
    let end = i + 1;
    let row = [queue[i].area];
    while (end < queue.length) {
      const next = [...row, queue[end].area];
      if (worst(next, side) > worst(row, side)) break;
      row = next;
      end += 1;
    }
    const sum = row.reduce((s, a) => s + a, 0);
    if (w >= h) {
      // The row is a column down the left edge.
      const cw = sum / h;
      let cy = y;
      for (let k = 0; k < row.length; k += 1) {
        const ch = row[k] / cw;
        out.push({ item: queue[i + k].item, x, y: cy, w: cw, h: ch });
        cy += ch;
      }
      x += cw;
      w -= cw;
    } else {
      // The row runs along the top edge.
      const rh = sum / w;
      let cx = x;
      for (let k = 0; k < row.length; k += 1) {
        const cw = row[k] / rh;
        out.push({ item: queue[i + k].item, x: cx, y, w: cw, h: rh });
        cx += cw;
      }
      y += rh;
      h -= rh;
    }
    i = end;
  }
  return out;
}
