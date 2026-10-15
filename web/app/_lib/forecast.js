// Departure forecast and "now vs normal" from published baselines. Pure functions.
// All calendar logic is IST (UTC+05:30, no daylight saving), matching the pipeline.

const IST_OFFSET_MS = 330 * 60 * 1000;
const HOUR_MS = 3600 * 1000;
export const STALE_AFTER_MS = 3 * HOUR_MS;
export const MIN_RELIABLE_N = 8;
// Waiting for a saving smaller than this is not worth recommending.
const WORTH_WAITING_S = 180;

export function istParts(ms) {
  const d = new Date(ms + IST_OFFSET_MS);
  return {
    date: d.toISOString().slice(0, 10),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    weekday: d.getUTCDay(),
  };
}

export function formatIstTime(ms) {
  const { hour, minute } = istParts(ms);
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

export function dayType(ms, holidays) {
  const { date, weekday } = istParts(ms);
  return weekday === 0 || weekday === 6 || holidays.has(date) ? 'weekend' : 'weekday';
}

export function indexBaselines(payload) {
  const index = new Map();
  for (const r of payload.rows) index.set(`${r.corridor_id}|${r.day_type}|${r.hour}`, r);
  return { index, holidays: new Set(payload.holidays ?? []) };
}

export function baselineAt(baselines, corridorId, ms) {
  const { hour } = istParts(ms);
  return baselines.index.get(`${corridorId}|${dayType(ms, baselines.holidays)}|${hour}`) ?? null;
}

function bucket(baselines, ids, ms) {
  let sum = 0;
  let nMin = Infinity;
  for (const id of ids) {
    const row = baselineAt(baselines, id, ms);
    if (!row) return null;
    sum += row.median_s;
    nMin = Math.min(nMin, row.n);
  }
  return { sum, nMin };
}

// Hourly medians describe the middle of their hour; interpolate between neighbours.
export function profileAt(baselines, ids, ms) {
  const centre = Math.floor((ms - HOUR_MS / 2) / HOUR_MS) * HOUR_MS + HOUR_MS / 2;
  const left = bucket(baselines, ids, centre);
  const right = bucket(baselines, ids, centre + HOUR_MS);
  if (!left || !right) return left ?? right;
  const w = (ms - centre) / HOUR_MS;
  return { sum: left.sum * (1 - w) + right.sum * w, nMin: Math.min(left.nMin, right.nMin) };
}

export function departureSlots(nowMs, horizonHours = 8, stepMinutes = 30) {
  const step = stepMinutes * 60 * 1000;
  const first = Math.ceil((nowMs + 60 * 1000) / step) * step;
  const slots = [nowMs];
  for (let t = first; t <= nowMs + horizonHours * HOUR_MS; t += step) slots.push(t);
  return slots;
}

/**
 * Scales the live ETA by how the route's corridors normally change over the next
 * hours, anchored to now. Returns null when the route has no usable baseline.
 */
export function forecast({ liveSeconds, corridorIds, baselines, nowMs }) {
  if (!corridorIds.length) return null;
  const anchor = profileAt(baselines, corridorIds, nowMs);
  if (!anchor || anchor.sum <= 0) return null;

  const slots = departureSlots(nowMs)
    .map((t) => {
      const p = profileAt(baselines, corridorIds, t);
      return p ? { t, seconds: (liveSeconds * p.sum) / anchor.sum, n: p.nMin } : null;
    })
    .filter(Boolean);

  const now = slots[0];
  const best = slots.reduce((a, b) => (b.seconds < a.seconds ? b : a), now);
  const worthWaiting = now.seconds - best.seconds >= WORTH_WAITING_S;

  return {
    slots,
    best: worthWaiting ? best : now,
    savingSeconds: worthWaiting ? now.seconds - best.seconds : 0,
    nMin: Math.min(...slots.map((s) => s.n)),
  };
}

export function confidence({ coverage, nMin }) {
  const reasons = [];
  if (coverage < 0.3) reasons.push(`only ${Math.round(coverage * 100)}% of the route is monitored`);
  else if (coverage < 0.6) reasons.push(`${Math.round(coverage * 100)}% of the route is monitored`);
  if (nMin < MIN_RELIABLE_N) reasons.push(`as few as ${nMin} past samples for some hours`);

  const level = coverage >= 0.6 && nMin >= MIN_RELIABLE_N ? 'high' : coverage >= 0.3 && nMin >= 4 ? 'medium' : 'low';
  return { level, reasons };
}

export function corridorNow(corridorId, latest, baselines) {
  const obs = latest?.corridors.find((c) => c.corridor_id === corridorId);
  if (!obs) return null;
  const at = Date.parse(obs.captured_at_utc);
  const normal = baselineAt(baselines, corridorId, at);
  return {
    capturedMs: at,
    nowSeconds: obs.duration_live_s,
    normalSeconds: normal?.median_s ?? null,
    n: normal?.n ?? 0,
    reliable: Boolean(normal?.reliable),
    deltaPct: normal ? (obs.duration_live_s / normal.median_s - 1) * 100 : null,
  };
}

export function routeVsNormal(corridorIds, latest, baselines) {
  let now = 0;
  let normal = 0;
  for (const id of corridorIds) {
    const c = corridorNow(id, latest, baselines);
    if (!c || c.normalSeconds == null) continue;
    now += c.nowSeconds;
    normal += c.normalSeconds;
  }
  return normal > 0 ? (now / normal - 1) * 100 : null;
}

export function boardRows(corridors, latest, baselines) {
  return corridors
    .map((c) => ({ ...c, ...corridorNow(c.id, latest, baselines) }))
    .sort((a, b) => (b.deltaPct ?? -Infinity) - (a.deltaPct ?? -Infinity));
}
