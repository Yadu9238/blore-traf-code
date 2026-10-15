// Mapbox geocoding and traffic-aware routing. Results are used for display only
// and never stored, per Mapbox terms and the project's licensing decision.

export const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || '';

const BLR_BBOX = '77.30,12.75,77.90,13.25';
const BLR_CENTRE = '77.5946,12.9716';

export class RouteError extends Error {}

export async function geocode(query, signal) {
  const params = new URLSearchParams({
    q: query,
    access_token: MAPBOX_TOKEN,
    autocomplete: 'true',
    limit: '5',
    country: 'in',
    bbox: BLR_BBOX,
    proximity: BLR_CENTRE,
    language: 'en',
  });
  const res = await fetch(`https://api.mapbox.com/search/geocode/v6/forward?${params}`, { signal });
  if (!res.ok) throw new RouteError(`Place search failed (HTTP ${res.status}).`);
  const body = await res.json();
  return (body.features ?? []).map((f) => ({
    id: f.id ?? f.properties?.mapbox_id,
    name: f.properties?.name ?? f.properties?.full_address,
    detail: f.properties?.place_formatted ?? '',
    lon: f.geometry.coordinates[0],
    lat: f.geometry.coordinates[1],
  }));
}

export async function route(from, to, signal) {
  const coords = `${from.lon},${from.lat};${to.lon},${to.lat}`;
  const params = new URLSearchParams({
    access_token: MAPBOX_TOKEN,
    geometries: 'geojson',
    overview: 'full',
    alternatives: 'false',
  });
  const res = await fetch(`https://api.mapbox.com/directions/v5/mapbox/driving-traffic/${coords}?${params}`, {
    signal,
  });
  if (res.status === 429) throw new RouteError('The route service is busy. Try again in a minute.');
  if (!res.ok) throw new RouteError(`Route lookup failed (HTTP ${res.status}).`);
  const body = await res.json();
  const best = body.routes?.[0];
  if (!best) throw new RouteError('No drivable route between these places.');
  return {
    seconds: best.duration,
    meters: best.distance,
    line: best.geometry.coordinates,
  };
}

export function inBangalore({ lat, lon }) {
  return lat >= 12.75 && lat <= 13.25 && lon >= 77.3 && lon <= 77.9;
}
