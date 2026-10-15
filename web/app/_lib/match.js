// Route-to-corridor matching. Pure functions, no browser APIs.

const M_PER_DEG_LAT = 110540;
const M_PER_DEG_LON_AT_BLR = 111320 * Math.cos((12.97 * Math.PI) / 180);

const toXY = ([lon, lat]) => [lon * M_PER_DEG_LON_AT_BLR, lat * M_PER_DEG_LAT];

// Projects a point onto a polyline; returns distance off the line and distance along it.
export function locateOnLine(line, point) {
  const p = toXY(point);
  let best = { offM: Infinity, alongM: 0 };
  let walked = 0;

  for (let i = 0; i < line.length - 1; i += 1) {
    const a = toXY(line[i]);
    const b = toXY(line[i + 1]);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
    const off = Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
    const seg = Math.sqrt(len2);
    if (off < best.offM) best = { offM: off, alongM: walked + t * seg };
    walked += seg;
  }
  return best;
}

export function lineLength(line) {
  let total = 0;
  for (let i = 0; i < line.length - 1; i += 1) {
    const a = toXY(line[i]);
    const b = toXY(line[i + 1]);
    total += Math.hypot(b[0] - a[0], b[1] - a[1]);
  }
  return total;
}

function mergedLength(intervals) {
  const sorted = [...intervals].sort((x, y) => x[0] - y[0]);
  let total = 0;
  let [start, end] = sorted[0] ?? [0, 0];
  for (const [s, e] of sorted.slice(1)) {
    if (s > end) {
      total += end - start;
      [start, end] = [s, e];
    } else {
      end = Math.max(end, e);
    }
  }
  return total + (end - start);
}

/**
 * A corridor is on the route when both its endpoints lie within `toleranceM` of
 * the route line and its origin comes before its destination along the route.
 */
export function matchCorridors(line, corridors, toleranceM = 500) {
  const routeM = lineLength(line);
  const matched = [];

  for (const c of corridors) {
    const from = locateOnLine(line, [c.origin.lon, c.origin.lat]);
    const to = locateOnLine(line, [c.destination.lon, c.destination.lat]);
    if (from.offM <= toleranceM && to.offM <= toleranceM && to.alongM > from.alongM) {
      matched.push({ id: c.id, fromM: from.alongM, toM: to.alongM });
    }
  }

  const coverage = matched.length && routeM > 0 ? mergedLength(matched.map((m) => [m.fromM, m.toM])) / routeM : 0;
  return { routeM, matched, coverage: Math.min(1, coverage) };
}

// Splits the route into monitored and unmonitored stretches for drawing.
export function sliceRoute(line, matched) {
  if (!matched.length) return [{ monitored: false, coords: line }];

  const intervals = matched.map((m) => [m.fromM, m.toM]).sort((a, b) => a[0] - b[0]);
  const isMonitored = (alongM) => intervals.some(([s, e]) => alongM >= s && alongM <= e);

  const pieces = [];
  let walked = 0;
  let current = { monitored: isMonitored(0), coords: [line[0]] };

  for (let i = 0; i < line.length - 1; i += 1) {
    const a = toXY(line[i]);
    const b = toXY(line[i + 1]);
    walked += Math.hypot(b[0] - a[0], b[1] - a[1]);
    const state = isMonitored(walked);
    current.coords.push(line[i + 1]);
    if (state !== current.monitored) {
      pieces.push(current);
      current = { monitored: state, coords: [line[i + 1]] };
    }
  }
  if (current.coords.length > 1) pieces.push(current);
  return pieces;
}
