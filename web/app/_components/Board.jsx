'use client';

import { useLayoutEffect, useRef } from 'react';
import { minutes, signedPct } from '../_lib/format';

// Bars saturate here; most hours sit within ±15%, so a wider scale flattens them to slivers.
const SCALE_PCT = 30;

function DeltaBar({ pct, reliable }) {
  if (pct == null) return <span className="t-bar is-empty" aria-hidden="true" />;
  const width = Math.min(Math.abs(pct), SCALE_PCT) / SCALE_PCT / 2;
  const style = pct >= 0 ? { left: '50%', width: `${width * 100}%` } : { right: '50%', width: `${width * 100}%` };
  return (
    <span className={`t-bar${reliable ? '' : ' is-thin'}`} aria-hidden="true">
      <span className={`t-bar-fill ${pct >= 0 ? 'is-slower' : 'is-faster'}`} style={style} />
    </span>
  );
}

function useReorderMotion(listRef, order) {
  const previous = useRef(new Map());

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const rows = [...list.querySelectorAll('[data-row]')];
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    for (const row of rows) {
      const before = previous.current.get(row.dataset.row);
      const after = row.getBoundingClientRect().top;
      if (!reduce && before != null && before !== after) {
        row.animate([{ transform: `translateY(${before - after}px)` }, { transform: 'none' }], {
          duration: 520,
          easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
        });
      }
    }
    previous.current = new Map(rows.map((r) => [r.dataset.row, r.getBoundingClientRect().top]));
  }, [listRef, order]);
}

export default function Board({ rows, onRoute, loading }) {
  const listRef = useRef(null);
  const focused = onRoute.size > 0;
  const ordered = focused
    ? [...rows.filter((r) => onRoute.has(r.id)), ...rows.filter((r) => !onRoute.has(r.id))]
    : rows;
  useReorderMotion(listRef, ordered.map((r) => r.id).join('|'));

  if (loading) {
    return (
      <ol className="t-board" aria-busy="true" aria-label="Loading corridors">
        {Array.from({ length: 8 }, (_, i) => (
          <li key={i} className="t-row is-skeleton" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </li>
        ))}
      </ol>
    );
  }

  return (
    <div className="t-board-wrap" data-focused={focused}>
      <div className="t-row t-head mono" aria-hidden="true">
        <span>Corridor</span>
        <span>Now</span>
        <span>Normal</span>
        <span>Now vs normal</span>
      </div>
      <ol className="t-board" ref={listRef}>
        {ordered.map((r) => {
          const on = onRoute.has(r.id);
          return (
            <li key={r.id} data-row={r.id} className="t-row" data-on-route={on || undefined}>
              <span className="t-name">
                {r.name}
                {on && <span className="t-tag mono">On your route</span>}
              </span>
              <span className="mono">{minutes(r.nowSeconds)}</span>
              <span className="mono t-normal">
                {r.normalSeconds == null ? 'no history' : minutes(r.normalSeconds)}
                {r.normalSeconds != null && !r.reliable && <span className="t-n"> n={r.n}</span>}
              </span>
              <span className="t-delta">
                <DeltaBar pct={r.deltaPct} reliable={r.reliable} />
                <span className="mono t-pct">{signedPct(r.deltaPct)}</span>
                <span className="sr-only">
                  {r.deltaPct == null
                    ? 'No baseline for this hour yet.'
                    : Math.round(r.deltaPct) === 0
                      ? 'Same as normal.'
                      : `${Math.abs(Math.round(r.deltaPct))}% ${r.deltaPct > 0 ? 'slower' : 'faster'} than normal.`}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
