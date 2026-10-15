'use client';

import { useState } from 'react';
import { formatIstTime, MIN_RELIABLE_N } from '../_lib/forecast';
import { minutes } from '../_lib/format';

export default function DepartureStrip({ forecast }) {
  const { slots, best } = forecast;
  const [inspected, setInspected] = useState(null);
  const max = Math.max(...slots.map((s) => s.seconds));
  const min = Math.min(...slots.map((s) => s.seconds));
  // Bars start at 35% height so small differences stay visible without implying zero.
  const height = (s) => 35 + (max === min ? 65 : ((s - min) / (max - min)) * 65);

  const shown = inspected ?? best;
  const label = (s) => (s === slots[0] ? 'Now' : formatIstTime(s.t));

  return (
    <figure className="t-strip">
      <figcaption className="mono t-strip-title">Leave at… (journey time, next 8 hours)</figcaption>
      <ol className="t-strip-bars" onMouseLeave={() => setInspected(null)}>
        {slots.map((s, i) => {
          const isBest = s.t === best.t;
          return (
            <li key={s.t} data-best={isBest || undefined} data-thin={s.n < MIN_RELIABLE_N || undefined}>
              <button
                type="button"
                className="t-slot"
                aria-pressed={inspected?.t === s.t}
                aria-label={`Leave ${label(s) === 'Now' ? 'now' : `at ${label(s)}`}: about ${minutes(s.seconds)}${
                  isBest ? ', best' : ''
                }`}
                onMouseEnter={() => setInspected(s)}
                onFocus={() => setInspected(s)}
                onBlur={() => setInspected(null)}
                onClick={() => setInspected(s)}
              >
                <span className="t-slot-bar" style={{ height: `${height(s.seconds)}%` }} />
              </button>
              <span className="mono t-slot-label" aria-hidden="true" data-show={i === 0 || i % 4 === 0 || isBest}>
                {label(s)}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="t-strip-caption" aria-live="polite">
        <strong>{shown === slots[0] ? 'Leave now' : `Leave at ${formatIstTime(shown.t)}`}</strong>: about{' '}
        {minutes(shown.seconds)}
        {shown.n < MIN_RELIABLE_N ? `, from only ${shown.n} past samples at that hour` : ''}.
      </p>
    </figure>
  );
}
