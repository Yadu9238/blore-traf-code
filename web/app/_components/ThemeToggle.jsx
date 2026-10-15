'use client';

import { useCallback, useEffect, useState } from 'react';

export default function ThemeToggle({ compact = false }) {
  const [dark, setDark] = useState(true);

  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setDark(root.classList.contains('dark'));
    sync();
    // Two toggles exist (rail and mobile bar); keep both in step.
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const toggle = useCallback((event) => {
    const root = document.documentElement;
    const apply = () => {
      const next = root.classList.toggle('dark');
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', next ? '#0b0b0b' : '#f5f5f3');
      try {
        localStorage.setItem('theme', next ? 'dark' : 'light');
      } catch {
        // Storage can be unavailable in private mode; the switch still applies.
      }
    };

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!document.startViewTransition || reduce) {
      apply();
      return;
    }

    const rect = event.currentTarget.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    root.style.setProperty('--vt-x', `${x}px`);
    root.style.setProperty('--vt-y', `${y}px`);
    root.style.setProperty('--vt-r', `${r}px`);
    document.startViewTransition(apply);
  }, []);

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      className={`theme-toggle${compact ? ' is-compact' : ''}`}
      onClick={toggle}
    >
      <span className="track" aria-hidden="true">
        <span className="knob" />
      </span>
      <span className={compact ? 'sr-only' : undefined}>Dark mode</span>
    </button>
  );
}
