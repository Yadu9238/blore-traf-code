// Serving files are produced by the daily transform and read from disk by the local API route.

export const REPO_URL = 'https://github.com/Yadu9238/blore-trf';
const BASE = '/api/serving';

async function getJson(name, signal, optional = false) {
  const res = await fetch(`${BASE}/${name}`, { cache: 'no-store', signal });
  if (!res.ok) {
    if (optional) return null;
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `${name} returned HTTP ${res.status}`);
  }
  return res.json();
}

export async function loadServing(signal) {
  const [corridors, baselines, latest, insights, health] = await Promise.all([
    getJson('corridors.json', signal),
    getJson('baselines.json', signal),
    getJson('latest.json', signal),
    getJson('insights.json', signal, true),
    getJson('health.json', signal, true),
  ]);
  return { corridors: corridors.corridors, baselines, latest, insights, health };
}
