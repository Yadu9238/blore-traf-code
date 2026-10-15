import assert from 'node:assert/strict';
import { test } from 'node:test';

import { matchCorridors, sliceRoute } from './match.js';
import { confidence, dayType, departureSlots, forecast, indexBaselines, istParts, routeVsNormal } from './forecast.js';

// A straight east-west road through Bangalore, ~10 km long.
const road = Array.from({ length: 11 }, (_, i) => [77.6 + i * 0.0092, 12.93]);
const corridor = (id, fromLon, toLon) => ({
  id,
  origin: { lat: 12.93, lon: fromLon },
  destination: { lat: 12.93, lon: toLon },
});

test('matches a corridor that lies on the route in the travel direction', () => {
  const { matched, coverage } = matchCorridors(road, [corridor('on', 77.61, 77.65)]);
  assert.deepEqual(matched.map((m) => m.id), ['on']);
  assert.ok(coverage > 0.4 && coverage < 0.5, `coverage ${coverage}`);
});

test('rejects the reverse direction and corridors off the route', () => {
  const offRoad = { id: 'off', origin: { lat: 12.97, lon: 77.61 }, destination: { lat: 12.97, lon: 77.65 } };
  const { matched, coverage } = matchCorridors(road, [corridor('reverse', 77.65, 77.61), offRoad]);
  assert.equal(matched.length, 0);
  assert.equal(coverage, 0);
});

test('overlapping corridors are not double counted in coverage', () => {
  const { coverage } = matchCorridors(road, [corridor('a', 77.6, 77.65), corridor('b', 77.62, 77.65)]);
  assert.ok(coverage < 0.6, `coverage ${coverage}`);
});

test('route slices alternate monitored and unmonitored stretches', () => {
  const { matched } = matchCorridors(road, [corridor('mid', 77.627, 77.655)]);
  const pieces = sliceRoute(road, matched);
  assert.deepEqual(pieces.map((p) => p.monitored), [false, true, false]);
});

test('IST calendar: 03:30 UTC Wednesday is 09:00 IST on a weekday; holidays count as weekend', () => {
  const ms = Date.parse('2026-10-14T03:30:00Z');
  assert.equal(istParts(ms).hour, 9);
  assert.equal(dayType(ms, new Set()), 'weekday');
  assert.equal(dayType(ms, new Set(['2026-10-14'])), 'weekend');
  assert.equal(dayType(Date.parse('2026-10-17T03:30:00Z'), new Set()), 'weekend');
});

function baselinesFor(id, medianByHour, n = 12) {
  const rows = [];
  for (const dt of ['weekday', 'weekend']) {
    for (let h = 0; h < 24; h += 1) {
      rows.push({ corridor_id: id, day_type: dt, hour: h, median_s: medianByHour(h), n, reliable: n >= 8 });
    }
  }
  return indexBaselines({ rows, holidays: [] });
}

test('forecast recommends the calm hour and reports the saving', () => {
  // Peak at 09:00-10:00 IST, calm from 12:00.
  const baselines = baselinesFor('a', (h) => (h >= 8 && h <= 10 ? 3600 : 1800));
  const now = Date.parse('2026-10-14T03:45:00Z'); // 09:15 IST
  const result = forecast({ liveSeconds: 3600, corridorIds: ['a'], baselines, nowMs: now });

  assert.ok(result.savingSeconds > 25 * 60, `saving ${result.savingSeconds}`);
  assert.ok(istParts(result.best.t).hour >= 11, `best ${istParts(result.best.t).hour}`);
  assert.equal(result.slots[0].t, now);
});

test('forecast says leave now when waiting saves under three minutes', () => {
  const baselines = baselinesFor('a', () => 1800);
  const now = Date.parse('2026-10-14T03:45:00Z');
  const result = forecast({ liveSeconds: 1800, corridorIds: ['a'], baselines, nowMs: now });
  assert.equal(result.best.t, now);
  assert.equal(result.savingSeconds, 0);
});

test('forecast is unavailable without matched corridors', () => {
  const baselines = baselinesFor('a', () => 1800);
  assert.equal(forecast({ liveSeconds: 900, corridorIds: [], baselines, nowMs: Date.now() }), null);
});

test('departure slots start now and step on the half hour for eight hours', () => {
  const now = Date.parse('2026-10-14T03:47:00Z');
  const slots = departureSlots(now);
  assert.equal(slots[0], now);
  assert.equal(new Date(slots[1]).getUTCMinutes() % 30, 0);
  assert.ok(slots.at(-1) <= now + 8 * 3600 * 1000);
});

test('confidence degrades with coverage and sample count', () => {
  assert.equal(confidence({ coverage: 0.8, nMin: 12 }).level, 'high');
  assert.equal(confidence({ coverage: 0.4, nMin: 6 }).level, 'medium');
  assert.equal(confidence({ coverage: 0.1, nMin: 12 }).level, 'low');
});

test('route vs normal compares the latest sample to its own hour', () => {
  const baselines = baselinesFor('a', () => 1000);
  const latest = { corridors: [{ corridor_id: 'a', captured_at_utc: '2026-10-14T03:30:00Z', duration_live_s: 1200 }] };
  assert.equal(Math.round(routeVsNormal(['a'], latest, baselines)), 20);
});
