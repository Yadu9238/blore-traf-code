export function minutes(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '–';
  const total = Math.max(1, Math.round(seconds / 60));
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} h ${String(m).padStart(2, '0')} min` : `${h} h`;
}

export function signedPct(pct) {
  if (pct == null || Number.isNaN(pct)) return '–';
  const r = Math.round(pct);
  if (r === 0) return '0%';
  return `${r > 0 ? '+' : '−'}${Math.abs(r)}%`;
}

export function ago(ms, nowMs) {
  const mins = Math.max(0, Math.round((nowMs - ms) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const h = Math.floor(mins / 60);
  return `${h} h ${String(mins % 60).padStart(2, '0')} min ago`;
}
