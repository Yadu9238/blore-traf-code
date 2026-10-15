'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { ArrowUpDown, ArrowUpRight, RotateCw } from 'lucide-react';
import ThemeToggle from './_components/ThemeToggle';
import Board from './_components/Board';
import DepartureStrip from './_components/DepartureStrip';
import PlaceField from './_components/PlaceField';
import { loadServing, REPO_URL } from './_lib/data';
import {
  boardRows,
  confidence,
  forecast,
  formatIstTime,
  indexBaselines,
  routeVsNormal,
  STALE_AFTER_MS,
} from './_lib/forecast';
import { ago, minutes, signedPct } from './_lib/format';
import { geocode, inBangalore, MAPBOX_TOKEN, route as fetchRoute, RouteError } from './_lib/mapbox';
import { matchCorridors, sliceRoute } from './_lib/match';

const RouteMap = dynamic(() => import('./_components/RouteMap'), { ssr: false });

const CONFIDENCE_LABEL = { high: 'High', medium: 'Medium', low: 'Low' };

async function resolvePlace(place, text, signal) {
  if (place) return place;
  if (!text || text.trim().length < 3) return null;
  const [first] = await geocode(text.trim(), signal);
  return first ?? null;
}

function Answer({ trip }) {
  const { forecast: fc, live, matched } = trip;

  if (!matched.length) {
    return (
      <>
        <h2 className="t-answer">No monitored corridor on this route.</h2>
        <p className="t-answer-sub">
          Live estimate: <strong>{minutes(live.seconds)}</strong>. A departure forecast needs at least one of the
          monitored tech corridors along the way, so this trip gets the live time only.
        </p>
      </>
    );
  }
  if (!fc) {
    return (
      <>
        <h2 className="t-answer">Not enough history for this route yet.</h2>
        <p className="t-answer-sub">
          Live estimate: <strong>{minutes(live.seconds)}</strong>. The corridors on this route have no baseline for the
          coming hours yet.
        </p>
      </>
    );
  }
  if (fc.savingSeconds > 0) {
    return (
      <>
        <h2 className="t-answer">Leave at {formatIstTime(fc.best.t)}.</h2>
        <p className="t-answer-sub">
          About <strong>{minutes(fc.best.seconds)}</strong> instead of {minutes(fc.slots[0].seconds)} if you leave now,{' '}
          {minutes(fc.savingSeconds)} faster.
        </p>
      </>
    );
  }
  return (
    <>
      <h2 className="t-answer">Leave now.</h2>
      <p className="t-answer-sub">
        About <strong>{minutes(fc.slots[0].seconds)}</strong>, and the next 8 hours are no better.
      </p>
    </>
  );
}

function TripResult({ trip, latest, baselines, focusRef }) {
  const vsNormal = trip.matched.length ? routeVsNormal(trip.matched.map((m) => m.id), latest, baselines) : null;
  const conf = trip.forecast ? confidence({ coverage: trip.coverage, nMin: trip.forecast.nMin }) : null;
  const pieces = useMemo(() => sliceRoute(trip.live.line, trip.matched), [trip]);

  return (
    <section className="t-result" aria-labelledby="t-result-title" tabIndex={-1} ref={focusRef}>
      <p id="t-result-title" className="mono t-result-route">
        {trip.from.name} → {trip.to.name}
      </p>
      <Answer trip={trip} />

      <dl className="facts mono">
        <div>
          <dt>Live ETA</dt>
          <dd>{minutes(trip.live.seconds)}</dd>
        </div>
        <div>
          <dt>Your corridors now</dt>
          <dd>{vsNormal == null ? 'No recent sample' : `${signedPct(vsNormal)} vs normal`}</dd>
        </div>
        <div>
          <dt>Monitored</dt>
          <dd>
            {Math.round(trip.coverage * 100)}% of {(trip.live.meters / 1000).toFixed(1)} km
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{conf ? CONFIDENCE_LABEL[conf.level] : 'n/a'}</dd>
        </div>
      </dl>
      {conf?.reasons.length > 0 && <p className="t-note">Confidence is {conf.level}: {conf.reasons.join('; ')}.</p>}

      {trip.forecast && <DepartureStrip forecast={trip.forecast} />}
      <RouteMap pieces={pieces} line={trip.live.line} />
    </section>
  );
}

export default function TrafficPage() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [from, setFrom] = useState(null);
  const [to, setTo] = useState(null);
  const [fromText, setFromText] = useState('');
  const [toText, setToText] = useState('');
  const [trip, setTrip] = useState(null);
  const [tripState, setTripState] = useState({ status: 'idle', message: '' });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const resultRef = useRef(null);
  const tripAbort = useRef(null);

  const load = useCallback(async () => {
    setLoadError(null);
    setData(null);
    try {
      setData(await loadServing());
    } catch (err) {
      setLoadError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
    const tick = setInterval(() => setNowMs(Date.now()), 60000);
    return () => clearInterval(tick);
  }, [load]);

  const baselines = useMemo(() => (data ? indexBaselines(data.baselines) : null), [data]);
  const rows = useMemo(() => (data ? boardRows(data.corridors, data.latest, baselines) : []), [data, baselines]);
  const latestMs = data ? Date.parse(data.latest.captured_at_utc) : null;
  const stale = latestMs != null && nowMs - latestMs > STALE_AFTER_MS;
  const onRoute = useMemo(() => new Set(trip?.matched.map((m) => m.id) ?? []), [trip]);

  useEffect(() => {
    if (trip) resultRef.current?.focus({ preventScroll: false });
  }, [trip]);

  const submit = async (e) => {
    e.preventDefault();
    if (!data) return;
    tripAbort.current?.abort();
    const controller = new AbortController();
    tripAbort.current = controller;
    setTripState({ status: 'loading', message: '' });

    try {
      const [a, b] = await Promise.all([
        resolvePlace(from, fromText, controller.signal),
        resolvePlace(to, toText, controller.signal),
      ]);
      if (!a || !b) throw new RouteError(`Pick a ${!a ? 'starting point' : 'destination'} from the suggestions.`);
      if (!inBangalore(a) || !inBangalore(b)) throw new RouteError('Both places need to be inside Bangalore.');
      setFrom(a);
      setTo(b);

      const live = await fetchRoute(a, b, controller.signal);
      const { matched, coverage } = matchCorridors(live.line, data.corridors);
      const now = Date.now();
      setNowMs(now);
      setTrip({
        from: a,
        to: b,
        live,
        matched,
        coverage,
        forecast: forecast({ liveSeconds: live.seconds, corridorIds: matched.map((m) => m.id), baselines, nowMs: now }),
      });
      setTripState({ status: 'idle', message: '' });
    } catch (err) {
      if (err.name === 'AbortError') return;
      setTripState({
        status: 'error',
        message: err instanceof RouteError ? err.message : 'Something went wrong looking up that route. Try again.',
      });
    }
  };

  const swap = () => {
    setFrom(to);
    setTo(from);
    setFromText(toText);
    setToText(fromText);
  };

  const tokenMissing = !MAPBOX_TOKEN;
  const health = data?.health;
  const coverage = data?.insights?.coverage;

  return (
    <>
      <a href="#t-main" className="skip">
        Skip to content
      </a>
      <header className="t-bar-top">
        <span className="t-wordmark">blore-trf</span>
        <ThemeToggle compact />
      </header>

      <main id="t-main" className="t-page">
        <header className="t-head-block">
          <dl className="docmeta mono t-meta">
            <div>
              <dt>Latest sample</dt>
              <dd>
                {latestMs ? (
                  <>
                    <time dateTime={data.latest.captured_at_utc}>{formatIstTime(latestMs)} IST</time>
                    {' · '}
                    {ago(latestMs, nowMs)}
                  </>
                ) : (
                  'Loading…'
                )}
              </dd>
            </div>
            <div>
              <dt>Corridors</dt>
              <dd>{data ? data.corridors.length : '–'}</dd>
            </div>
            <div>
              <dt>History</dt>
              <dd>{coverage ? `${coverage.days} days, ${coverage.samples.toLocaleString('en-IN')} samples` : '–'}</dd>
            </div>
            <div>
              <dt>Pipeline</dt>
              <dd>
                {health == null ? '–' : health.healthy ? 'Healthy' : `${health.checks.filter((c) => !c.passed).length} checks failing`}
              </dd>
            </div>
          </dl>

          <h1>Bangalore tech corridors, right now.</h1>
          <p className="abstract">
            Travel time on the city&apos;s tech corridors, compared with what is <strong>normal for this hour</strong>.
            Enter a trip to see <strong>when to leave</strong>.
          </p>

          <form className="t-query" onSubmit={submit} aria-describedby={tokenMissing ? 't-token-note' : undefined}>
            <PlaceField label="From" value={from} onChange={setFrom} onText={setFromText} disabled={tokenMissing} allowLocate />
            <button type="button" className="icon-btn t-swap" onClick={swap} aria-label="Swap from and to" disabled={tokenMissing}>
              <ArrowUpDown size={18} aria-hidden="true" />
            </button>
            <PlaceField label="To" value={to} onChange={setTo} onText={setToText} disabled={tokenMissing} />
            <button
              type="submit"
              className="btn btn-solid t-go"
              disabled={tokenMissing || !data || tripState.status === 'loading'}
            >
              {tripState.status === 'loading' ? 'Finding…' : 'Find best time'}
            </button>
          </form>
          {tokenMissing && (
            <p id="t-token-note" className="t-note">
              Route search needs a Mapbox token. Add NEXT_PUBLIC_MAPBOX_TOKEN to web/.env.local and restart. The
              corridor board below works without it.
            </p>
          )}
          {tripState.status === 'error' && (
            <p className="t-note t-error" role="alert">
              {tripState.message}
            </p>
          )}
        </header>

        {trip && data && <TripResult trip={trip} latest={data.latest} baselines={baselines} focusRef={resultRef} />}

        <section className="t-section" aria-labelledby="t-board-title">
          <h2 id="t-board-title" className="t-h2">
            Corridors now vs normal
          </h2>
          <p className="t-sub">
            {latestMs
              ? `As of ${formatIstTime(latestMs)} IST. Normal is the median at that hour for the same kind of day: weekday, or weekend and holidays.`
              : 'Loading the latest samples.'}
          </p>

          {stale && (
            <p className="t-notice" role="status">
              The latest sample is {ago(latestMs, nowMs).replace(' ago', '')} old. Collection runs on a best-effort
              schedule, so these comparisons describe {formatIstTime(latestMs)} IST, not this minute.
            </p>
          )}

          {loadError ? (
            <div className="t-notice" role="alert">
              <p>Corridor data could not be loaded ({loadError}).</p>
              <button type="button" className="btn btn-line" onClick={load}>
                <RotateCw size={16} aria-hidden="true" /> Try again
              </button>
            </div>
          ) : (
            <Board rows={rows} onRoute={onRoute} loading={!data} />
          )}
        </section>

        <section className="t-section" aria-labelledby="t-method-title">
          <h2 id="t-method-title" className="t-h2">
            How this works
          </h2>
          <dl className="t-method">
            <div>
              <dt>Sampling</dt>
              <dd>
                Each corridor&apos;s live travel time is polled several times an hour, more often at peak, together with
                rainfall. Collection runs free on GitHub Actions, which does not guarantee every run.
              </dd>
            </div>
            <div>
              <dt>Normal</dt>
              <dd>
                The median travel time for each corridor, per hour, on weekdays or weekends and holidays. Hours with fewer
                than 8 samples are marked with their sample count.
              </dd>
            </div>
            <div>
              <dt>Forecast</dt>
              <dd>
                Your live ETA is scaled by how the corridors on your route normally change over the next 8 hours. Parts of
                the route outside the monitored corridors are assumed to follow the same pattern.
              </dd>
            </div>
            <div>
              <dt>Privacy</dt>
              <dd>Your places and route are looked up live and never stored.</dd>
            </div>
            <div>
              <dt>Driving</dt>
              <dd>
                Driving can be dangerous. Route times come from the Mapbox Directions API and do not replace what you
                see on the road: where signals, signs or police direct otherwise, follow them, and observe all traffic
                laws.
              </dd>
            </div>
          </dl>
          <ul className="links">
            <li>
              <a className="ext" href={REPO_URL} target="_blank" rel="noopener noreferrer">
                Source code <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            </li>
            <li>
              <a className="ext" href={`${REPO_URL}/blob/master/docs/decisions.md`} target="_blank" rel="noopener noreferrer">
                Design decisions <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            </li>
            <li>
              <a className="ext" href={`${REPO_URL}/blob/master/docs/incidents.md`} target="_blank" rel="noopener noreferrer">
                Incident log <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            </li>
          </ul>
        </section>

        <footer className="doc-foot mono">
          <span>blore-trf · local, non-production use</span>
          <span>Routing and maps © Mapbox · Weather Open-Meteo</span>
        </footer>
      </main>
    </>
  );
}
