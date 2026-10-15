'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { LocateFixed } from 'lucide-react';
import { geocode, inBangalore } from '../_lib/mapbox';

const MIN_QUERY = 3;
const DEBOUNCE_MS = 300;

export default function PlaceField({ label, value, onChange, onText, disabled, allowLocate }) {
  const id = useId();
  const listId = `${id}-list`;
  const [text, setText] = useState(value?.name ?? '');
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState('idle');
  const [locating, setLocating] = useState(false);
  const typed = useRef(false);

  useEffect(() => {
    // Typing clears the selection; only a chosen place should overwrite the text.
    if (value) setText(value.name);
  }, [value]);

  useEffect(() => {
    if (!typed.current || text.trim().length < MIN_QUERY) {
      setOptions([]);
      setStatus('idle');
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setStatus('loading');
      try {
        const found = await geocode(text.trim(), controller.signal);
        setOptions(found);
        setActive(found.length ? 0 : -1);
        setStatus(found.length ? 'ready' : 'empty');
        setOpen(true);
      } catch (err) {
        if (err.name !== 'AbortError') {
          setStatus('error');
          setOpen(true);
        }
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  const choose = (place) => {
    typed.current = false;
    onChange(place);
    setText(place.name);
    setOpen(false);
    setOptions([]);
  };

  const onKeyDown = (e) => {
    if (!open || !options.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (i + 1) % options.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (i - 1 + options.length) % options.length);
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  const locate = () => {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocating(false);
        const here = { id: 'here', name: 'Current location', detail: '', lat: coords.latitude, lon: coords.longitude };
        if (inBangalore(here)) {
          choose(here);
        } else {
          setStatus('outside');
          setOpen(true);
        }
      },
      () => {
        setLocating(false);
        setStatus('denied');
        setOpen(true);
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  };

  const message = {
    loading: 'Searching…',
    empty: 'No matches in Bangalore. Try a landmark or area name.',
    error: 'Place search is unavailable right now.',
    outside: 'Your location is outside Bangalore.',
    denied: 'Location access was blocked. Type a place instead.',
  }[status];

  return (
    <div className="t-field" data-open={open && (options.length > 0 || Boolean(message))}>
      <label htmlFor={id} className="mono">
        {label}
      </label>
      <div className="t-input-wrap">
        <input
          id={id}
          type="text"
          role="combobox"
          aria-expanded={open && options.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          spellCheck="false"
          placeholder={allowLocate ? 'Area, landmark or address' : 'Where to?'}
          value={text}
          disabled={disabled}
          onChange={(e) => {
            typed.current = true;
            setText(e.target.value);
            onText?.(e.target.value);
            if (value) onChange(null);
          }}
          onKeyDown={onKeyDown}
          onFocus={() => options.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
        />
        {allowLocate && (
          <button
            type="button"
            className="t-locate"
            onClick={locate}
            disabled={disabled || locating}
            aria-label="Use my current location"
            title="Use my current location"
          >
            <LocateFixed size={18} aria-hidden="true" />
          </button>
        )}
      </div>
      {open && (
        <div className="t-pop">
          {options.length > 0 ? (
            <ul id={listId} role="listbox" aria-label={`${label} suggestions`}>
              {options.map((o, i) => (
                <li
                  key={o.id ?? `${o.lat},${o.lon}`}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(o)}
                >
                  <span>{o.name}</span>
                  {o.detail && <span className="t-pop-detail">{o.detail}</span>}
                </li>
              ))}
            </ul>
          ) : (
            message && <p role="status">{message}</p>
          )}
        </div>
      )}
    </div>
  );
}
